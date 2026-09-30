"""REPL state machine: render confirmation transitions."""

from __future__ import annotations

import pytest

from sp.media.render import RenderPlan, Segment
from sp.repl.state import Event, ReplFsm, State
from sp.shared.errors import CommandError


@pytest.fixture()
def plan() -> RenderPlan:
    return RenderPlan(segments=(Segment("a.mp4", 0.0, 1.0),), width=640, height=360, rate=25.0)


def test_starts_ready():
    fsm = ReplFsm()
    assert fsm.state is State.READY
    assert fsm.pending is None


def test_render_request_transitions_to_confirm(plan: RenderPlan):
    fsm = ReplFsm()
    fsm.request_render(plan, "out.mp4")
    assert fsm.state is State.CONFIRM
    assert fsm.pending == (plan, "out.mp4")


def test_confirm_returns_pending_and_returns_to_ready(plan: RenderPlan):
    fsm = ReplFsm()
    fsm.request_render(plan, "out.mp4")
    pending_plan, target = fsm.confirm()
    assert pending_plan is plan
    assert target == "out.mp4"
    assert fsm.state is State.READY
    assert fsm.pending is None


def test_reject_discards_pending(plan: RenderPlan):
    fsm = ReplFsm()
    fsm.request_render(plan, "out.mp4")
    fsm.reject()
    assert fsm.state is State.READY
    assert fsm.pending is None


def test_second_request_while_pending_is_rejected(plan: RenderPlan):
    fsm = ReplFsm()
    fsm.request_render(plan, "out.mp4")
    with pytest.raises(CommandError, match="awaiting confirmation"):
        fsm.request_render(plan, "other.mp4")


def test_confirm_without_pending_errors():
    with pytest.raises(CommandError, match="nothing to confirm"):
        ReplFsm().confirm()


def test_reject_without_pending_errors():
    with pytest.raises(CommandError, match="nothing to reject"):
        ReplFsm().reject()


def test_transition_listener_observes_the_full_cycle(plan: RenderPlan):
    seen: list[tuple[Event, State, State]] = []
    fsm = ReplFsm(on_transition=lambda ev, old, new: seen.append((ev, old, new)))
    fsm.request_render(plan, "out.mp4")
    fsm.reject()
    fsm.request_render(plan, "out.mp4")
    fsm.confirm()
    assert [ev for ev, _, _ in seen] == [
        Event.RENDER_REQUESTED,
        Event.REJECTED,
        Event.RENDER_REQUESTED,
        Event.CONFIRMED,
    ]
    assert all(new is not old for _, old, new in seen)
