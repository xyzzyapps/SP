"""Command table: dispatch, arity, handlers, context wiring."""

from __future__ import annotations

import pytest
from fakes import FakeProbe, FakeRenderer, media_info

from sp.repl.commands import ReplContext, build_commands
from sp.repl.state import ReplFsm, State
from sp.shared.errors import CommandError
from sp.timeline.session import TimelineSession

INFOS = {
    "a.mp4": media_info("a.mp4", duration=4.0, rate=25.0),
    "b.mp4": media_info("b.mp4", duration=6.0, rate=30.0, width=320, height=240, has_audio=False),
}


@pytest.fixture()
def ctx() -> ReplContext:
    context = ReplContext(
        session=TimelineSession(FakeProbe(INFOS)),
        renderer=FakeRenderer(),
        fsm=ReplFsm(),
    )
    context.commands = build_commands()
    return context


def dispatch(ctx: ReplContext, *form: object) -> str | None:
    assert ctx.commands is not None
    return ctx.commands.dispatch(list(form), ctx)


# --- table shape -----------------------------------------------------------


def test_default_command_surface():
    assert build_commands().names == [
        "open",
        "trim",
        "timeline",
        "render",
        "doctor",
        "help",
        "quit",
    ]


def test_help_lists_every_usage(ctx: ReplContext):
    text = dispatch(ctx, "help")
    assert text is not None
    for usage in ['(open "file")', "(trim start end)", "(timeline)", '(render "out.mp4")']:
        assert usage in text


def test_duplicate_registration_rejected():
    from sp.repl.commands import Commands

    table = Commands()
    table.register("x", "(x)", 0, 0, lambda c: "")
    with pytest.raises(CommandError, match="already registered"):
        table.register("x", "(x)", 0, 0, lambda c: "")


# --- dispatch errors -------------------------------------------------------


def test_unknown_command(ctx: ReplContext):
    with pytest.raises(CommandError, match="unknown command: bogus"):
        dispatch(ctx, "bogus")


def test_arity_is_enforced_before_the_handler_runs(ctx: ReplContext):
    with pytest.raises(CommandError, match=r"usage: \(trim start end\)"):
        dispatch(ctx, "trim", 0)
    with pytest.raises(CommandError, match="usage"):
        dispatch(ctx, "trim", 0, 1, 2)
    with pytest.raises(CommandError, match="usage"):
        dispatch(ctx, "open")


def test_empty_form_rejected(ctx: ReplContext):
    with pytest.raises(CommandError, match="command"):
        dispatch(ctx, [])


def test_non_symbol_head_rejected(ctx: ReplContext):
    with pytest.raises(CommandError, match="symbol"):
        dispatch(ctx, 42)


# --- handlers --------------------------------------------------------------


def test_open_appends_and_describes(ctx: ReplContext):
    text = dispatch(ctx, "open", "a.mp4")
    assert text is not None and text.startswith("opened:")
    assert "640x360" in text and "4.00s" in text
    assert ctx.session.clip_count == 1


def test_open_requires_a_quoted_string(ctx: ReplContext):
    with pytest.raises(CommandError, match=r'\(open "clip.mp4"\)'):
        dispatch(ctx, "open", 42)
    assert ctx.session.clip_count == 0


def test_trim_updates_timeline(ctx: ReplContext):
    dispatch(ctx, "open", "a.mp4")
    text = dispatch(ctx, "trim", 0, 2)
    assert text is not None and "trimmed a.mp4" in text
    assert ctx.session.duration == pytest.approx(2.0)


def test_trim_requires_numbers_not_bools(ctx: ReplContext):
    dispatch(ctx, "open", "a.mp4")
    with pytest.raises(CommandError, match="start must be a number"):
        dispatch(ctx, "trim", "start", 2)
    with pytest.raises(CommandError, match="start must be a number"):
        dispatch(ctx, "trim", True, 2)


def test_timeline_shows_structure(ctx: ReplContext):
    dispatch(ctx, "open", "a.mp4")
    text = dispatch(ctx, "timeline")
    assert text is not None and "[1] a.mp4" in text


def test_render_plans_and_arms_confirmation(ctx: ReplContext):
    dispatch(ctx, "open", "a.mp4")
    text = dispatch(ctx, "render", "out.mp4")
    assert text is not None
    assert "1 segment(s)" in text
    assert "fake-render" in text  # explain() of the FakeRenderer
    assert "Proceed? [y/N]" in text
    assert ctx.fsm.state is State.CONFIRM


def test_render_rejects_missing_directory(ctx: ReplContext):
    dispatch(ctx, "open", "a.mp4")
    with pytest.raises(CommandError, match="directory does not exist"):
        dispatch(ctx, "render", "no/such/dir/out.mp4")
    assert ctx.fsm.state is State.READY


def test_render_of_empty_timeline_errors(ctx: ReplContext):
    with pytest.raises(CommandError, match="empty"):
        dispatch(ctx, "render", "out.mp4")


def test_doctor_reports_environment(ctx: ReplContext):
    text = dispatch(ctx, "doctor")
    assert text is not None
    assert "SP 0.1.0" in text
    assert "opentimelineio" in text
    assert "renderer" in text and "fake" in text
    assert "timeline" in text


def test_quit_flips_the_running_flag(ctx: ReplContext):
    assert ctx.running
    assert dispatch(ctx, "quit") == "bye"
    assert not ctx.running
