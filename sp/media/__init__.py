"""Feature slice: media probing and rendering (FFmpeg behind interfaces).

- :mod:`sp.media.probe` — ``Probe`` interface, ``Ffprobe`` implementation
- :mod:`sp.media.render` — ``Renderer`` interface, ``FfmpegRenderer`` /
  ``ToucanRenderer`` implementations, ``RenderPlan`` data structures
"""

from .probe import Ffprobe, MediaInfo, Probe
from .render import FfmpegRenderer, Renderer, RenderPlan, Segment, ToucanRenderer, default_renderer

__all__ = [
    "Ffprobe",
    "FfmpegRenderer",
    "MediaInfo",
    "Probe",
    "RenderPlan",
    "Renderer",
    "Segment",
    "ToucanRenderer",
    "default_renderer",
]
