"""Media probing behind the ``Probe`` interface.

``Ffprobe`` shells out to ``ffprobe`` and normalizes its JSON into
:class:`MediaInfo`; tests inject their own ``Probe``-shaped fake, so no
processes are spawned outside integration tests.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from sp.shared.errors import CommandError
from sp.shared.logging_setup import get_logger
from sp.shared.process import Runner, run

log = get_logger("probe")

#: Fallback frame rate when a file reports a nonsense rate (e.g. "0/0").
DEFAULT_RATE = 24.0


@dataclass(frozen=True)
class MediaInfo:
    """Normalized facts about one media file (seconds and frames)."""

    path: str
    duration: float  #: seconds
    rate: float  #: frames per second of the video stream
    width: int  #: pixels
    height: int  #: pixels
    has_video: bool
    has_audio: bool
    codec: str  #: video codec name, "" when there is no video stream

    def describe(self) -> str:
        """One-line human summary used by REPL output."""
        audio = "audio" if self.has_audio else "no audio"
        return (
            f"{self.path}: {self.width}x{self.height} @{self.rate:g}fps, "
            f"{self.duration:.2f}s, {self.codec or '?'} + {audio}"
        )


@runtime_checkable
class Probe(Protocol):
    """Interface: answer facts about a media file."""

    def probe(self, path: str) -> MediaInfo:
        """Return :class:`MediaInfo` for *path*.

        Raises:
            CommandError: file missing or unusable as video.
            ProcessError: the underlying tool failed.
        """
        ...


def _parse_rate(text: str | None) -> float:
    """Parse ffprobe's ``"num/den"`` frame-rate strings."""
    if not text:
        return 0.0
    try:
        num, _, den = text.partition("/")
        denominator = float(den or 1)
        if denominator == 0:
            return 0.0
        return float(num) / denominator
    except ValueError:
        return 0.0


def _first_float(*values: object) -> float:
    for value in values:
        try:
            result = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if result > 0:
            return result
    return 0.0


class Ffprobe:
    """``Probe`` implementation backed by the ``ffprobe`` CLI (JSON mode)."""

    def __init__(self, exe: str = "ffprobe", runner: Runner = run) -> None:
        self._exe = exe
        self._runner = runner

    def probe(self, path: str) -> MediaInfo:
        if not os.path.exists(path):
            raise CommandError(f"no such file: {path}")
        cmd = [
            self._exe,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            path,
        ]
        proc = self._runner(cmd)
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise CommandError(f"ffprobe returned invalid JSON for {path}") from exc
        return _media_info_from_json(path, data)


def _media_info_from_json(path: str, data: dict) -> MediaInfo:
    """Pure JSON -> :class:`MediaInfo` mapping (unit-testable, no process)."""
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        raise CommandError(f"no video stream in {path}")

    fmt = data.get("format") or {}
    rate = _parse_rate(video.get("r_frame_rate")) or _parse_rate(video.get("avg_frame_rate"))
    if rate <= 0:
        rate = DEFAULT_RATE
        log.warning("%s reports no usable frame rate; assuming %g", path, rate)

    duration = _first_float(fmt.get("duration"), video.get("duration"))
    if duration <= 0:
        raise CommandError(f"could not determine duration of {path}")

    return MediaInfo(
        path=path,
        duration=duration,
        rate=rate,
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        has_video=True,
        has_audio=audio is not None,
        codec=str(video.get("codec_name") or ""),
    )
