"""Explicit state machine for the render confirmation flow.

Vex-style safety: before anything is rendered, the planned command is
shown and an explicit ``y`` is required.  Modelling this as a small FSM
keeps the interaction testable without a terminal and gives the logging
layer a single place to trace transitions.

::

    READY --RENDER_REQUESTED--> CONFIRM --CONFIRMED--> READY
                                    |
                                    +----REJECTED----> READY
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum

from sp.media.render import RenderPlan
from sp.shared.errors import CommandError
from sp.shared.logging_setup import get_logger

log = get_logger("repl.state")


class State(Enum):
    """REPL input-routing states."""

    READY = "ready"  # input is an s-expression command
    CONFIRM = "confirm"  # input is a y/N answer to a pending render


class Event(Enum):
    """FSM events driving the transitions above."""

    RENDER_REQUESTED = "render_requested"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


#: Listener signature: (event, old_state, new_state).
TransitionListener = Callable[[Event, "State", "State"], None]


class ReplFsm:
    """Render-confirmation state machine.

    Attributes:
        state: current :class:`State`.
        pending: ``(plan, out)`` awaiting confirmation, or ``None``.
    """

    def __init__(self, on_transition: TransitionListener | None = None) -> None:
        self._state = State.READY
        self._pending: tuple[RenderPlan, str] | None = None
        self._on_transition = on_transition

    @property
    def state(self) -> State:
        """Current state."""
        return self._state

    @property
    def pending(self) -> tuple[RenderPlan, str] | None:
        """Pending render request, if any."""
        return self._pending

    def _fire(self, event: Event, new_state: State) -> None:
        old = self._state
        self._state = new_state
        log.debug("fsm: %s  %s -> %s", event.value, old.value, new_state.value)
        if self._on_transition is not None:
            self._on_transition(event, old, new_state)

    def request_render(self, plan: RenderPlan, out: str) -> None:
        """READY -> CONFIRM, parking *plan*/*out* as pending."""
        if self._state is not State.READY:
            raise CommandError("another command is already awaiting confirmation")
        self._pending = (plan, out)
        self._fire(Event.RENDER_REQUESTED, State.CONFIRM)

    def confirm(self) -> tuple[RenderPlan, str]:
        """CONFIRM -> READY; returns the pending ``(plan, out)``."""
        if self._state is not State.CONFIRM or self._pending is None:
            raise CommandError("nothing to confirm")
        pending = self._pending
        self._pending = None
        self._fire(Event.CONFIRMED, State.READY)
        return pending

    def reject(self) -> None:
        """CONFIRM -> READY, discarding the pending render."""
        if self._state is not State.CONFIRM:
            raise CommandError("nothing to reject")
        self._pending = None
        self._fire(Event.REJECTED, State.READY)
