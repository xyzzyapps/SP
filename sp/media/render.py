"""Rendering behind the ``Renderer`` interface.

:class:`RenderPlan` is the seam between slices: the timeline slice
flattens an OTIO timeline into ordered :class:`Segment` values; renderers
turn a plan into pixels.  ``FfmpegRenderer`` builds a single
filter-graph FFmpeg command; ``ToucanRenderer`` renders the serialized
``.otio`` timeline when ``toucan-render`` is available on PATH.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from sp.shared.errors import CommandError
from sp.shared.logging_setup import get_logger
from sp.shared.process import Runner, run

log = get_logger("render")


@dataclass(frozen=True)
class Segment:
    """One source movie cut: use ``[source_in, source_out)`` seconds."""

    url: str
    source_in: float  #: seconds into the source file (inclusive)
    source_out: float  #: seconds into the source file (exclusive)
    has_audio: bool = True

    @property
    def duration(self) -> float:
        """Segment length in seconds."""
        return self.source_out - self.source_in


@dataclass(frozen=True)
class RenderPlan:
    """Everything a renderer needs: ordered cuts plus output geometry.

    Attributes:
        segments: cuts in timeline order.
        width/height: output frame size (normalized by the renderer).
        rate: output frames per second.
        otio_json: serialized OpenTimelineIO timeline (used by toucan).
    """

    segments: tuple[Segment, ...]
    width: int
    height: int
    rate: float
    otio_json: str | None = field(default=None, compare=False)

    @property
    def duration(self) -> float:
        """Total timeline duration in seconds."""
        return sum(seg.duration for seg in self.segments)

    @property
    def has_audio(self) -> bool:
        """Whether every segment carries an audio track."""
        return bool(self.segments) and all(seg.has_audio for seg in self.segments)

    def validate(self) -> None:
        """Reject plans no renderer could honour; raises CommandError."""
        if not self.segments:
            raise CommandError("timeline is empty — nothing to render")
        for i, seg in enumerate(self.segments, start=1):
            if seg.source_in < 0:
                raise CommandError(f"segment {i} starts before zero: {seg.source_in}")
            if seg.source_out <= seg.source_in:
                raise CommandError(f"segment {i} has non-positive duration")
        if len({seg.has_audio for seg in self.segments}) > 1:
            raise CommandError("mixed audio/no-audio segments are not supported yet")
        if self.width <= 0 or self.height <= 0:
            raise CommandError(f"invalid output size: {self.width}x{self.height}")
        if self.rate <= 0:
            raise CommandError(f"invalid output frame rate: {self.rate}")


@runtime_checkable
class Renderer(Protocol):
    """Interface: turn a :class:`RenderPlan` into a movie file."""

    name: str

    def explain(self, plan: RenderPlan, out: str) -> str:
        """One-line description of what rendering *plan* would do."""
        ...

    def render(self, plan: RenderPlan, out: str) -> None:
        """Render *plan* to *out*; raises SpError on failure."""
        ...


class FfmpegRenderer:
    """Renders a plan with one FFmpeg filter-graph command.

    Each input is trimmed (``-ss``/``-t``), normalized to the plan's
    geometry/fps, then concatenated.  All inputs are re-encoded, so
    mixed codecs/resolutions are fine; only mixed audio/no-audio is
    rejected (see :meth:`RenderPlan.validate`).
    """

    name = "ffmpeg"

    def __init__(self, exe: str = "ffmpeg", runner: Runner = run) -> None:
        self._exe = exe
        self._runner = runner

    # -- command construction (pure, unit-tested) --------------------------
    def build_command(self, plan: RenderPlan, out: str) -> list[str]:
        """Build the exact FFmpeg argv for *plan* without running it."""
        plan.validate()
        with_audio = plan.has_audio

        cmd: list[str] = [self._exe, "-hide_banner", "-loglevel", "error", "-y"]
        for seg in plan.segments:
            cmd += ["-ss", f"{seg.source_in:.6f}", "-t", f"{seg.duration:.6f}", "-i", seg.url]

        filters: list[str] = []
        for i, _seg in enumerate(plan.segments):
            filters.append(
                f"[{i}:v]scale={plan.width}:{plan.height}:force_original_aspect_ratio=decrease,"
                f"pad={plan.width}:{plan.height}:(ow-iw)/2:(oh-ih)/2,"
                f"fps={plan.rate:g},format=yuv420p[v{i}]"
            )
            if with_audio:
                filters.append(f"[{i}:a]aresample=48000[a{i}]")

        labels = "".join(
            f"[v{i}]" + (f"[a{i}]" if with_audio else "") for i in range(len(plan.segments))
        )
        if with_audio:
            # concat with a=1 emits two pads: label both so -map can find them
            filters.append(f"{labels}concat=n={len(plan.segments)}:v=1:a=1[v][a]")
        else:
            filters.append(f"{labels}concat=n={len(plan.segments)}:v=1:a=0[v]")

        cmd += ["-filter_complex", ";".join(filters), "-map", "[v]"]
        if with_audio:
            cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", out]
        return cmd

    # -- Renderer interface ------------------------------------------------
    def explain(self, plan: RenderPlan, out: str) -> str:
        """Quote the FFmpeg command that would run (shown before confirm)."""
        return " ".join(f'"{a}"' if " " in a else a for a in self.build_command(plan, out))

    def render(self, plan: RenderPlan, out: str) -> None:
        """Run the FFmpeg command built by :meth:`build_command`."""
        cmd = self.build_command(plan, out)
        log.info("rendering %d segments (%.2fs) -> %s", len(plan.segments), plan.duration, out)
        self._runner(cmd, timeout=3600)
        log.info("rendered %s", out)


class ToucanRenderer:
    """Renders the serialized ``.otio`` timeline with ``toucan-render``.

    The timeline JSON is written next to *out* as ``<out>.otio`` — an
    interoperable artifact that other OTIO tools can consume.
    """

    name = "toucan"

    def __init__(self, exe: str = "toucan-render", runner: Runner = run) -> None:
        self._exe = exe
        self._runner = runner

    def _timeline_path(self, out: str) -> Path:
        return Path(out).with_suffix(".otio")

    def explain(self, plan: RenderPlan, out: str) -> str:
        """Describe the toucan invocation (writes the .otio first)."""
        return f'{self._exe} "{self._timeline_path(out)}" "{out}"'

    def render(self, plan: RenderPlan, out: str) -> None:
        """Write ``<out>.otio`` from the plan, then render it."""
        plan.validate()
        if plan.otio_json is None:
            raise CommandError("render plan carries no .otio timeline (required by toucan)")
        otio_path = self._timeline_path(out)
        otio_path.write_text(plan.otio_json, encoding="utf-8")
        log.info("wrote %s (%d bytes)", otio_path, len(plan.otio_json))
        self._runner([self._exe, str(otio_path), out], timeout=3600)
        log.info("rendered %s via toucan", out)


def default_renderer() -> Renderer:
    """Pick the best available renderer: toucan when on PATH, else FFmpeg."""
    if shutil.which("toucan-render"):
        log.info("toucan-render found on PATH; using ToucanRenderer")
        return ToucanRenderer()
    log.info("toucan-render not found; using FfmpegRenderer")
    return FfmpegRenderer()


__all__ = [
    "FfmpegRenderer",
    "RenderPlan",
    "Renderer",
    "Segment",
    "ToucanRenderer",
    "default_renderer",
]
