"""Feature slice: the OTIO-backed edit session (timeline model).

Uses the real OpenTimelineIO data model — no reinvented timeline types.
"""

from .session import TimelineSession

__all__ = ["TimelineSession"]
