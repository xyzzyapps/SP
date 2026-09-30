"""The REPL loop: prompts, multiline buffering, confirm flow, resilience."""

from __future__ import annotations

import pytest
from fakes import FakeProbe, FakeRenderer, ScriptedInput, media_info

from sp.repl.commands import ReplContext, build_commands
from sp.repl.loop import BANNER, main, run_repl
from sp.repl.state import ReplFsm, State
from sp.timeline.session import TimelineSession

INFOS = {
    "a.mp4": media_info("a.mp4", duration=4.0, rate=25.0),
    "b.mp4": media_info("b.mp4", duration=6.0, rate=30.0, width=320, height=240, has_audio=False),
}


def make_ctx() -> ReplContext:
    """Build a REPL context wired with fakes (no subprocesses)."""
    ctx = ReplContext(
        session=TimelineSession(FakeProbe(INFOS)),
        renderer=FakeRenderer(),
        fsm=ReplFsm(),
    )
    ctx.commands = build_commands()
    return ctx


def run_script(lines: list[str], ctx: ReplContext | None = None):
    """Feed *lines* through run_repl; returns (ctx, script, outs, errs, code)."""
    ctx = ctx or make_ctx()
    script = ScriptedInput(lines)
    outs: list[str] = []
    errs: list[str] = []
    code = run_repl(ctx, input_fn=script, out=outs.append, err=errs.append)
    return ctx, script, outs, errs, code


# --- session flows ---------------------------------------------------------


def test_banner_help_quit():
    _, script, outs, errs, code = run_script(["(help)", "(quit)"])
    assert code == 0
    assert outs[0] == BANNER
    assert any("(trim start end)" in line for line in outs)
    assert "bye" in outs
    assert errs == []
    assert script.prompts[0] == "sp> "


def test_unknown_command_does_not_kill_the_session():
    _, _, outs, errs, _ = run_script(["(bogus)", "(help)", "(quit)"])
    assert any("unknown command: bogus" in e for e in errs)
    assert any("commands:" in o for o in outs)  # session kept going


def test_parse_error_does_not_kill_the_session():
    _, _, outs, errs, _ = run_script(["(open))", "(quit)"])
    assert any("** " in e for e in errs)
    assert "bye" in outs


def test_multiline_input_is_buffered_until_balanced():
    ctx = make_ctx()
    ctx.session.open("a.mp4")
    _, script, outs, errs, _ = run_script(["(trim 0", "2)", "(timeline)", "(quit)"], ctx)
    assert errs == []
    assert "... " in script.prompts  # continuation prompt while buffering
    assert ctx.session.duration == pytest.approx(2.0)
    assert any("[1] a.mp4" in o for o in outs)


def test_blank_lines_are_ignored():
    _, _, outs, errs, _ = run_script(["", "   ", "(quit)"])
    assert errs == []
    assert "bye" in outs


def test_open_trim_timeline_flow():
    ctx, _, outs, errs, _ = run_script(
        ['(open "a.mp4")', "(trim 0 3)", "(timeline)", "(quit)"],
        ctx=None,
    )
    assert errs == []
    assert any(o.startswith("opened:") for o in outs)
    assert any("trimmed a.mp4" in o for o in outs)
    assert ctx.session.duration == pytest.approx(3.0)


# --- render confirmation flow ----------------------------------------------


def test_render_confirm_yes_uses_fake_renderer():
    ctx = make_ctx()
    _, script, outs, errs, _ = run_script(
        ['(open "a.mp4")', '(render "out.mp4")', "y", "(quit)"],
        ctx,
    )
    assert errs == []
    assert "sp(y/N)> " in script.prompts
    renderer = ctx.renderer
    assert isinstance(renderer, FakeRenderer)
    assert len(renderer.rendered) == 1
    plan, target = renderer.rendered[0]
    assert target == "out.mp4"
    assert plan.duration == pytest.approx(4.0)
    assert any(o.startswith("rendered out.mp4") for o in outs)


def test_render_reject_cancels_without_rendering():
    ctx = make_ctx()
    _, _, outs, errs, _ = run_script(
        ['(open "a.mp4")', '(render "out.mp4")', "n", "(quit)"],
        ctx,
    )
    assert errs == []
    assert "cancelled" in outs
    assert ctx.renderer.rendered == []  # type: ignore[attr-defined]
    assert ctx.fsm.state is State.READY


def test_render_failure_is_reported_not_raised():
    from sp.shared.errors import ProcessError

    class ExplodingRenderer(FakeRenderer):
        def render(self, plan, out):  # noqa: D102 - test double
            raise ProcessError(["ffmpeg"], 1, "disk full")

    ctx = make_ctx()
    ctx.renderer = ExplodingRenderer()
    _, script, outs, errs, _ = run_script(
        ['(open "a.mp4")', '(render "out.mp4")', "yes", "(quit)"],
        ctx,
    )
    # the SpError was printed, the session survived to (quit)
    assert any("disk full" in e for e in errs)
    assert "bye" in outs
    assert script.prompts[-1] == "sp> "  # back to READY after failed render


# --- termination -----------------------------------------------------------


def test_eof_ends_cleanly_even_mid_buffer():
    _, _, outs, errs, code = run_script(['(open "a.mp4"'])  # script ends -> EOFError
    assert code == 0
    assert errs == []
    assert outs[0] == BANNER


def test_quit_stops_before_script_exhausts():
    _, script, _, _, _ = run_script(["(quit)", "(help)"])
    # only one prompt was consumed: the loop exited after quit
    assert len(script.prompts) == 1


# --- CLI entry -------------------------------------------------------------


def test_main_single_command_mode(capsys):
    assert main(["-c", "(help)"]) == 0
    captured = capsys.readouterr()
    assert "commands:" in captured.out
    assert captured.err == ""


def test_main_reports_errors_with_nonzero_status(capsys):
    assert main(["-c", "(bogus)"]) == 1
    captured = capsys.readouterr()
    assert "unknown command" in captured.err
