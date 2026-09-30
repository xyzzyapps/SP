"""Render slice: plan validation, FFmpeg command construction, renderers."""

from __future__ import annotations

import pytest
from fakes import RecordingRunner

from sp.media.render import FfmpegRenderer, RenderPlan, Segment, ToucanRenderer, default_renderer
from sp.shared.errors import CommandError, ProcessError


def make_plan(
    segments: list[Segment],
    *,
    width: int = 640,
    height: int = 360,
    rate: float = 25.0,
    otio_json: str | None = None,
) -> RenderPlan:
    return RenderPlan(
        segments=tuple(segments),
        width=width,
        height=height,
        rate=rate,
        otio_json=otio_json,
    )


AUDIO = [Segment("a.mp4", 0.0, 1.5, True), Segment("b.mp4", 2.0, 4.0, True)]
SILENT = [Segment("a.mp4", 0.0, 2.0, False)]


# --- plan data structure --------------------------------------------------


def test_plan_duration_and_audio_properties():
    plan = make_plan(AUDIO)
    assert plan.duration == pytest.approx(3.5)
    assert plan.has_audio
    assert not make_plan(SILENT).has_audio


def test_validate_rejects_empty_plan():
    with pytest.raises(CommandError, match="empty"):
        make_plan([]).validate()


def test_validate_rejects_inverted_range():
    with pytest.raises(CommandError, match="non-positive"):
        make_plan([Segment("a.mp4", 3.0, 1.0)]).validate()


def test_validate_rejects_negative_start():
    with pytest.raises(CommandError, match="before zero"):
        make_plan([Segment("a.mp4", -0.5, 1.0)]).validate()


def test_validate_rejects_mixed_audio():
    mixed = [Segment("a.mp4", 0, 1, True), Segment("b.mp4", 0, 1, False)]
    with pytest.raises(CommandError, match="mixed audio"):
        make_plan(mixed).validate()


def test_validate_rejects_bad_geometry_or_rate():
    with pytest.raises(CommandError, match="invalid output size"):
        make_plan(AUDIO, width=0).validate()
    with pytest.raises(CommandError, match="frame rate"):
        make_plan(AUDIO, rate=0).validate()


# --- FFmpeg command construction (pure) -----------------------------------


def test_command_shape_with_audio():
    plan = make_plan(AUDIO)
    cmd = FfmpegRenderer().build_command(plan, "out.mp4")
    assert cmd[0] == "ffmpeg"
    assert "-y" in cmd
    # inputs arrive as -ss/-t/-i triples, in plan order
    inputs = [cmd[i + 1] for i, token in enumerate(cmd) if token == "-i"]
    assert inputs == ["a.mp4", "b.mp4"]
    assert cmd[cmd.index("-ss") + 1] == "0.000000"
    assert cmd[cmd.index("-t") + 1] == "1.500000"
    assert "a.mp4" in cmd and "b.mp4" in cmd
    assert cmd[-1] == "out.mp4"


def test_filter_graph_normalizes_and_concatenates():
    plan = make_plan(AUDIO, width=320, height=240, rate=25.0)
    cmd = FfmpegRenderer().build_command(plan, "out.mp4")
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "scale=320:240:force_original_aspect_ratio=decrease" in fc
    assert "fps=25" in fc
    assert "format=yuv420p" in fc
    assert "aresample=48000" in fc
    assert "concat=n=2:v=1:a=1[v][a]" in fc
    # explicit stream mapping + codecs
    assert cmd[cmd.index("-map") + 1] == "[v]"
    assert "[a]" in cmd
    assert "libx264" in cmd and "aac" in cmd


def test_command_without_audio_drops_audio_stages():
    cmd = FfmpegRenderer().build_command(make_plan(SILENT), "out.mp4")
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "aresample" not in fc
    assert "concat=n=1:v=1:a=0[v]" in fc
    assert "-c:a" not in cmd
    assert cmd.count("-map") == 1


def test_build_command_validates_plan():
    with pytest.raises(CommandError):
        FfmpegRenderer().build_command(make_plan([]), "out.mp4")


def test_explain_shows_the_command_for_confirmation():
    text = FfmpegRenderer().explain(make_plan(AUDIO), "out.mp4")
    assert text.startswith("ffmpeg")
    assert "out.mp4" in text


# --- rendering (runner injected) ------------------------------------------


def test_render_runs_the_built_command():
    runner = RecordingRunner()
    FfmpegRenderer(runner=runner).render(make_plan(AUDIO), "out.mp4")
    assert len(runner.calls) == 1
    cmd = runner.calls[0]
    assert cmd[0] == "ffmpeg"
    assert cmd[-1] == "out.mp4"


def test_render_failure_propagates_process_error():
    runner = RecordingRunner(returncode=1, stderr="encode failed")
    with pytest.raises(ProcessError, match="encode failed"):
        FfmpegRenderer(runner=runner).render(make_plan(AUDIO), "out.mp4")


# --- toucan renderer -------------------------------------------------------


def test_toucan_writes_otio_artifact_then_renders(tmp_path):
    runner = RecordingRunner()
    out = tmp_path / "out.mp4"
    plan = make_plan(AUDIO, otio_json='{"OTIO_SCHEMA": "Timeline.1"}')
    ToucanRenderer(runner=runner).render(plan, str(out))
    artifact = tmp_path / "out.otio"
    assert artifact.read_text(encoding="utf-8") == '{"OTIO_SCHEMA": "Timeline.1"}'
    cmd = runner.calls[0]
    assert cmd[0] == "toucan-render"
    assert str(artifact) in cmd
    assert str(out) in cmd


def test_toucan_requires_serialized_timeline(tmp_path):
    with pytest.raises(CommandError, match="no .otio"):
        ToucanRenderer(runner=RecordingRunner()).render(make_plan(AUDIO), str(tmp_path / "o.mp4"))


def test_default_renderer_returns_a_renderer():
    renderer = default_renderer()
    assert renderer.name in {"ffmpeg", "toucan"}
