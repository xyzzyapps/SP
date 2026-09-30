"""End-to-end pipeline against the real FFmpeg (skipped when absent).

Generates its own media with lavfi sources (``testsrc``/``sine``), so no
external assets or pre-made fixtures are required.
"""

from __future__ import annotations

import shutil
import subprocess

import opentimelineio as otio
import pytest

from sp.media.probe import Ffprobe
from sp.media.render import FfmpegRenderer
from sp.timeline.session import TimelineSession

pytestmark = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
    reason="ffmpeg/ffprobe not on PATH",
)


def _make_clip(path, *, source: str, size: str, rate: int) -> None:
    """Generate a 2s clip with audio via lavfi (no external assets)."""
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"{source}=duration=2:size={size}:rate={rate}",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=2",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def test_full_pipeline_open_trim_render_probe(tmp_path):
    """open -> trim -> flatten -> render -> ffprobe validates the output."""
    one = tmp_path / "one.mp4"
    two = tmp_path / "two.mp4"
    _make_clip(one, source="testsrc", size="320x240", rate=25)
    _make_clip(two, source="testsrc2", size="640x360", rate=30)

    session = TimelineSession(Ffprobe())
    session.open(str(one))
    session.trim(0, 1)  # keep 1s of the first clip
    session.open(str(two))  # full 2s of the second

    plan = session.flatten()
    assert plan.duration == pytest.approx(3.0, abs=0.1)

    out = tmp_path / "out.mp4"
    FfmpegRenderer().render(plan, str(out))
    assert out.exists()

    info = Ffprobe().probe(str(out))
    assert info.duration == pytest.approx(3.0, abs=0.25)
    assert (info.width, info.height) == (320, 240)  # geometry of the first clip
    assert info.has_audio


def test_otio_artifact_round_trip(tmp_path):
    clip = tmp_path / "clip.mp4"
    _make_clip(clip, source="testsrc", size="320x240", rate=25)

    session = TimelineSession(Ffprobe())
    session.open(str(clip))
    session.trim(0.5, 1.5)
    path = session.write_otio(tmp_path / "cut.otio")

    loaded = otio.adapters.read_from_file(str(path))
    clips = list(loaded.find_clips())
    assert len(clips) == 1
    assert clips[0].source_range.duration.to_seconds() == pytest.approx(1.0, abs=0.01)
