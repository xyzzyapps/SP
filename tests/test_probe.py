"""Probe slice: ffprobe JSON normalization and the Probe interface."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fakes import RecordingRunner

from sp.media.probe import Ffprobe, _media_info_from_json
from sp.shared.errors import CommandError, ProcessError

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    # utf-8-sig tolerates the BOM some PowerShell redirects add
    return json.loads((FIXTURES / name).read_text(encoding="utf-8-sig"))


def test_parses_captured_ffprobe_json_with_audio():
    info = _media_info_from_json("a.mp4", _load("a.ffprobe.json"))
    assert info.duration == pytest.approx(4.0)
    assert info.rate == pytest.approx(25.0)
    assert (info.width, info.height) == (640, 360)
    assert info.has_video and info.has_audio
    assert info.codec == "h264"


def test_parses_video_only_file():
    info = _media_info_from_json("b.mp4", _load("b_silent.ffprobe.json"))
    assert info.duration == pytest.approx(3.0)
    assert info.rate == pytest.approx(30.0)
    assert (info.width, info.height) == (320, 240)
    assert not info.has_audio


def test_audio_only_file_rejected():
    data = {"streams": [{"codec_type": "audio"}], "format": {"duration": "1.0"}}
    with pytest.raises(CommandError, match="no video stream"):
        _media_info_from_json("x.m4a", data)


def test_nonsense_frame_rate_falls_back_to_default():
    data = _load("a.ffprobe.json")
    data["streams"][0]["r_frame_rate"] = "0/0"
    data["streams"][0]["avg_frame_rate"] = "0/0"
    info = _media_info_from_json("a.mp4", data)
    assert info.rate == pytest.approx(24.0)


def test_fractional_frame_rate():
    data = _load("a.ffprobe.json")
    data["streams"][0]["r_frame_rate"] = "30000/1001"
    info = _media_info_from_json("a.mp4", data)
    assert info.rate == pytest.approx(29.97, abs=0.01)


def test_missing_file_raises_before_running_anything():
    runner = RecordingRunner()
    with pytest.raises(CommandError, match="no such file"):
        Ffprobe(runner=runner).probe("does/not/exist.mp4")
    assert runner.calls == []


def test_ffprobe_invocation_and_json_stdout():
    dummy = FIXTURES / "a.ffprobe.json"  # any existing path
    runner = RecordingRunner(stdout=dummy.read_text(encoding="utf-8-sig"))
    info = Ffprobe(runner=runner).probe(str(dummy))
    assert info.duration == pytest.approx(4.0)
    cmd = runner.calls[0]
    assert cmd[0] == "ffprobe"
    assert "-print_format" in cmd and "json" in cmd
    assert cmd[-1] == str(dummy)


def test_invalid_json_raises_command_error():
    dummy = FIXTURES / "a.ffprobe.json"
    runner = RecordingRunner(stdout="this is not json")
    with pytest.raises(CommandError, match="invalid JSON"):
        Ffprobe(runner=runner).probe(str(dummy))


def test_failing_ffprobe_propagates_process_error():
    dummy = FIXTURES / "a.ffprobe.json"
    runner = RecordingRunner(returncode=1, stderr="boom")
    with pytest.raises(ProcessError, match="exited 1"):
        Ffprobe(runner=runner).probe(str(dummy))


def test_describe_is_one_line():
    info = _media_info_from_json("a.mp4", _load("a.ffprobe.json"))
    line = info.describe()
    assert "\n" not in line
    assert "640x360" in line and "4.00s" in line
