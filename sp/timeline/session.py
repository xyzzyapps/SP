"""OTIO-backed edit session: wraps the real OpenTimelineIO timeline model.

The session owns one in-memory :class:`otio.schema.Timeline` with a
single video track (``V1``).  Commands mutate it:

- :meth:`TimelineSession.open` probes a file and appends a ``Clip``
  carrying an ``ExternalReference`` with the file's available range,
- :meth:`TimelineSession.trim` narrows the last clip's ``source_range``,
- :meth:`TimelineSession.flatten` projects the timeline into a
  ``RenderPlan`` for the media slice,
- :meth:`TimelineSession.write_otio` persists a real ``.otio`` file.

All times exposed to callers are **seconds** (floats); conversion to
:class:`opentimelineio.opentime.RationalTime` happens internally at the
clip's frame rate.
"""

from __future__ import annotations

import os
from pathlib import Path

import opentimelineio as otio
from opentimelineio import opentime

from sp.media.probe import MediaInfo, Probe
from sp.media.render import RenderPlan, Segment
from sp.shared.errors import CommandError
from sp.shared.logging_setup import get_logger

log = get_logger("timeline")


def _rt(seconds: float, rate: float) -> opentime.RationalTime:
    """Seconds -> RationalTime at *rate* (frame-granular)."""
    return opentime.RationalTime(value=round(seconds * rate), rate=rate)


def _seconds(rt: opentime.RationalTime) -> float:
    """RationalTime -> seconds."""
    return rt.to_seconds()


class TimelineSession:
    """Interactive edit state: one OTIO timeline, one video track."""

    def __init__(self, probe: Probe) -> None:
        self._probe = probe
        self._timeline = otio.schema.Timeline(name="sp")
        self._track = otio.schema.Track(name="V1", kind=otio.schema.TrackKind.Video)
        self._timeline.tracks.append(self._track)
        #: path -> MediaInfo for every file ever opened in this session
        self._infos: dict[str, MediaInfo] = {}
        log.debug("TimelineSession created")

    # -- introspection -----------------------------------------------------
    @property
    def timeline(self) -> otio.schema.Timeline:
        """The underlying OpenTimelineIO timeline."""
        return self._timeline

    @property
    def clips(self) -> list[otio.schema.Clip]:
        """Clips of track V1 in timeline order."""
        return [e for e in self._track if isinstance(e, otio.schema.Clip)]

    @property
    def clip_count(self) -> int:
        """Number of clips on the timeline."""
        return len(self.clips)

    @property
    def duration(self) -> float:
        """Timeline duration in seconds."""
        return _seconds(self._timeline.duration())

    def _last_clip(self) -> otio.schema.Clip:
        clips = self.clips
        if not clips:
            raise CommandError('timeline is empty — start with (open "clip.mp4")')
        return clips[-1]

    # -- editing operations ------------------------------------------------
    def open(self, path: str) -> MediaInfo:
        """Probe *path* and append it as a new clip to the timeline."""
        info = self._probe.probe(path)
        rate = info.rate
        available = opentime.TimeRange(
            start_time=_rt(0.0, rate),
            duration=_rt(info.duration, rate),
        )
        clip = otio.schema.Clip(
            name=os.path.basename(path),
            source_range=available,
            media_reference=otio.schema.ExternalReference(
                target_url=path,
                available_range=available,
            ),
        )
        self._track.append(clip)
        self._infos[path] = info
        log.info(
            "opened %s (%.2fs %dx%d @%g) as clip #%d",
            path,
            info.duration,
            info.width,
            info.height,
            info.rate,
            self.clip_count,
        )
        return info

    def trim(self, start: float, end: float) -> tuple[float, float]:
        """Keep only ``[start, end)`` seconds of the **last** clip.

        Args:
            start: new in-point, seconds into the source file.
            end: new out-point, seconds into the source file.

        Returns:
            The applied ``(start, end)``.

        Raises:
            CommandError: empty timeline, inverted range, or a range that
                leaves the clip's available media.
        """
        clip = self._last_clip()
        ref = clip.media_reference
        if ref is None or ref.available_range is None:
            raise CommandError(f"clip {clip.name!r} has no media reference")
        available = _seconds(ref.available_range.duration)
        if start < 0:
            raise CommandError(f"start must be >= 0 (got {start})")
        if end <= start:
            raise CommandError(f"end ({end}) must be after start ({start})")
        if end > available + 1e-6:
            raise CommandError(f"end {end}s is beyond the clip's media ({available:.3f}s)")
        rate = clip.source_range.start_time.rate
        clip.source_range = opentime.TimeRange(
            start_time=_rt(start, rate),
            duration=_rt(end - start, rate),
        )
        log.info("trimmed clip %r to [%.3f, %.3f)", clip.name, start, end)
        return start, end

    # -- projection / persistence ------------------------------------------
    def flatten(self) -> RenderPlan:
        """Project the timeline into an ordered :class:`RenderPlan`.

        Segments are cut in timeline order; the first clip decides the
        output geometry and frame rate.
        """
        clips = self.clips
        if not clips:
            raise CommandError("timeline is empty — nothing to render")
        segments: list[Segment] = []
        for clip in clips:
            url = clip.media_reference.target_url  # type: ignore[union-attr]
            info = self._infos[url]
            src_start = _seconds(clip.source_range.start_time)
            segments.append(
                Segment(
                    url=url,
                    source_in=src_start,
                    source_out=src_start + _seconds(clip.source_range.duration),
                    has_audio=info.has_audio,
                )
            )
        first_info = self._infos[clips[0].media_reference.target_url]  # type: ignore[union-attr]
        plan = RenderPlan(
            segments=tuple(segments),
            width=first_info.width,
            height=first_info.height,
            rate=first_info.rate,
            otio_json=self.to_otio_json(),
        )
        log.debug(
            "flattened timeline: %d segments, %.3fs total",
            len(segments),
            plan.duration,
        )
        return plan

    def to_otio_json(self) -> str:
        """Serialize the timeline to OTIO's native JSON format."""
        return self._timeline.to_json_string()

    def write_otio(self, path: str | Path) -> Path:
        """Write a real ``.otio`` file and return its path."""
        path = Path(path)
        otio.adapters.write_to_file(self._timeline, str(path))
        log.info("wrote timeline to %s", path)
        return path

    # -- human output -------------------------------------------------------
    def summary(self) -> str:
        """Multi-line, IRB-style picture of the timeline structure."""
        lines = [
            f'timeline "sp"  {self.duration:.3f}s  {self.clip_count} clip(s)  '
            f"rate {self._timeline.duration().rate:g}"
        ]
        lines.append("  V1:")
        if not self.clip_count:
            lines.append("    (empty)")
        for i, clip in enumerate(self.clips, start=1):
            start = _seconds(clip.source_range.start_time)
            end = start + _seconds(clip.source_range.duration)
            url = clip.media_reference.target_url  # type: ignore[union-attr]
            info = self._infos[url]
            lines.append(
                f"    [{i}] {clip.name}  timeline {start:.3f}->{end:.3f}s  "
                f"({info.width}x{info.height} @{info.rate:g}fps, {info.codec})"
            )
        return "\n".join(lines)
