"""Timeline slice: OTIO session — open, trim, flatten, summary, write."""

from __future__ import annotations

import opentimelineio as otio
import pytest
from fakes import FakeProbe, media_info

from sp.shared.errors import CommandError
from sp.timeline.session import TimelineSession

INFOS = {
    "a.mp4": media_info("a.mp4", duration=4.0, rate=25.0, width=640, height=360, has_audio=True),
    "b.mp4": media_info(
        "b.mp4", duration=6.0, rate=30.0, width=320, height=240, has_audio=False, codec="hevc"
    ),
}


@pytest.fixture()
def session() -> TimelineSession:
    return TimelineSession(FakeProbe(INFOS))


def test_open_appends_a_clip(session: TimelineSession):
    info = session.open("a.mp4")
    assert info.duration == pytest.approx(4.0)
    assert session.clip_count == 1
    assert session.duration == pytest.approx(4.0)
    clip = session.clips[0]
    assert clip.name == "a.mp4"
    assert clip.media_reference.target_url == "a.mp4"
    assert clip.media_reference.available_range.duration.to_seconds() == pytest.approx(4.0)


def test_open_missing_file_surfaces_probe_error(session: TimelineSession):
    with pytest.raises(CommandError, match="no such file"):
        session.open("missing.mp4")
    assert session.clip_count == 0


def test_trim_narrows_the_last_clip(session: TimelineSession):
    session.open("a.mp4")
    start, end = session.trim(1.0, 3.0)
    assert (start, end) == (1.0, 3.0)
    assert session.duration == pytest.approx(2.0)
    clip = session.clips[0]
    assert clip.source_range.start_time.to_seconds() == pytest.approx(1.0)
    assert clip.source_range.duration.to_seconds() == pytest.approx(2.0)


def test_trim_bounds_are_validated(session: TimelineSession):
    session.open("a.mp4")
    with pytest.raises(CommandError, match="beyond"):
        session.trim(0.0, 99.0)
    with pytest.raises(CommandError, match="after start"):
        session.trim(3.0, 1.0)
    with pytest.raises(CommandError, match=">= 0"):
        session.trim(-1.0, 2.0)
    # media untouched by failed trims
    assert session.duration == pytest.approx(4.0)


def test_trim_on_empty_timeline_explains_itself(session: TimelineSession):
    with pytest.raises(CommandError, match='open "clip.mp4"'):
        session.trim(0.0, 1.0)


def test_flatten_projects_ordered_segments(session: TimelineSession):
    session.open("a.mp4")
    session.trim(1.0, 2.0)  # a.mp4 now plays 1s
    session.open("b.mp4")  # full 6s, silent
    plan = session.flatten()
    assert [(s.url, s.source_in, s.source_out) for s in plan.segments] == [
        ("a.mp4", 1.0, 2.0),
        ("b.mp4", 0.0, 6.0),
    ]
    assert [s.has_audio for s in plan.segments] == [True, False]  # mixed -> renderer rejects
    assert plan.duration == pytest.approx(7.0)
    # first clip decides output geometry
    assert (plan.width, plan.height, plan.rate) == (640, 360, 25.0)
    assert plan.otio_json and "OTIO_SCHEMA" in plan.otio_json


def test_flatten_empty_timeline_explains_itself(session: TimelineSession):
    with pytest.raises(CommandError, match="empty"):
        session.flatten()


def test_summary_lists_every_clip(session: TimelineSession):
    session.open("a.mp4")
    session.trim(0.0, 2.0)
    session.open("b.mp4")
    text = session.summary()
    assert 'timeline "sp"' in text
    assert "V1:" in text
    assert "[1] a.mp4" in text and "[2] b.mp4" in text
    assert "640x360" in text and "320x240" in text
    assert "2 clip(s)" in text


def test_summary_of_empty_timeline(session: TimelineSession):
    assert "(empty)" in session.summary()


def test_write_otio_round_trips_through_the_real_adapter(session: TimelineSession, tmp_path):
    session.open("a.mp4")
    session.open("b.mp4")
    path = session.write_otio(tmp_path / "cut.otio")
    assert path.exists()
    loaded = otio.adapters.read_from_file(str(path))
    clips = list(loaded.find_clips())
    assert [c.name for c in clips] == ["a.mp4", "b.mp4"]


def test_timeline_property_exposes_raw_otio(session: TimelineSession):
    session.open("a.mp4")
    assert isinstance(session.timeline, otio.schema.Timeline)
    assert session.timeline.name == "sp"
    assert len(session.timeline.tracks) == 1
    assert session.timeline.tracks[0].name == "V1"
