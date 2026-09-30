"""IRB-like read-eval-print loop.

Reads one line at a time, accumulates lines until the s-expression is
balanced (multiline input), dispatches through the command table and
prints the result.  Parse/command errors never kill the session — they
are logged with tracebacks to ``sp.log`` and shown as one-liners —
mirroring the IRB experience.  EOF (Ctrl-D/Ctrl-Z) and Ctrl-C exit
cleanly.

Input routing is state-driven: in ``READY`` the line is an s-expression;
in ``CONFIRM`` (after ``(render ...)``) the line is a ``y``/``N`` answer.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from sp import __version__
from sp.media.probe import Ffprobe
from sp.media.render import default_renderer
from sp.sexp import parse
from sp.shared.errors import CommandError, ParseError, SpError
from sp.shared.logging_setup import get_logger, setup_logging
from sp.shared.services import registry
from sp.timeline.session import TimelineSession

from .commands import ReplContext, build_commands
from .state import ReplFsm, State

log = get_logger("repl")

#: Prompt -> line (raises EOFError when input ends).
InputFn = Callable[[str], str]
#: Result/error printers.
Printer = Callable[[str], None]

BANNER = f"""SP {__version__} — minimum video editor repl
type (help) for commands, (quit) to exit; every session logs to sp.log"""


def bootstrap() -> ReplContext:
    """Register default services in the locator and build a session context."""
    registry.register("probe", Ffprobe)
    registry.register("renderer", default_renderer)
    registry.register("session", lambda: TimelineSession(registry.get("probe")))
    ctx = ReplContext(
        session=registry.get("session"),
        renderer=registry.get("renderer"),
        fsm=ReplFsm(),
    )
    ctx.commands = build_commands()
    log.debug("bootstrap complete (renderer=%s)", ctx.renderer.name)
    return ctx


def _is_complete(source: str) -> bool:
    """True when *source* parses (or is blank); False while incomplete."""
    if not source.strip():
        return True
    try:
        parse(source)
    except ParseError as exc:
        return not exc.incomplete
    return True


def _prompt(state: State, buffer: str) -> str:
    """Prompt for the current FSM state and buffer fill."""
    if state is State.CONFIRM:
        return "sp(y/N)> "
    return "... " if buffer.strip() else "sp> "


def _execute(
    ctx: ReplContext,
    source: str,
    out: Printer,
    err: Printer,
) -> None:
    """Parse and dispatch one complete input; never raises SpError."""
    try:
        form = parse(source)
        if not isinstance(form, list):
            raise CommandError(f"expected a (command ...) form, got {form!r}")
        if ctx.commands is None:
            raise CommandError("no commands registered")
        result = ctx.commands.dispatch(form, ctx)
        if result:
            out(result)
    except SpError as exc:
        log.debug("input rejected: %s", exc, exc_info=True)
        err(f"** {exc}")


def _handle_confirm(ctx: ReplContext, line: str, out: Printer, err: Printer) -> None:
    """Resolve a pending render: ``y`` renders, anything else cancels."""
    answer = line.strip().lower()
    if answer in ("y", "yes"):
        try:
            plan, target = ctx.fsm.confirm()
            ctx.renderer.render(plan, target)
            out(f"rendered {target} ({plan.duration:.3f}s, {plan.width}x{plan.height})")
        except SpError as exc:
            log.debug("render failed: %s", exc, exc_info=True)
            err(f"** {exc}")
    else:
        ctx.fsm.reject()
        out("cancelled")


def run_repl(
    ctx: ReplContext,
    *,
    input_fn: InputFn = input,
    out: Printer = print,
    err: Printer = print,
) -> int:
    """Run the read-eval-print loop until quit/EOF; returns an exit code.

    Args:
        ctx: session context (built by :func:`bootstrap` or tests).
        input_fn: prompt -> line; raises EOFError when input ends.
        out: printer for successful results.
        err: printer for error one-liners.
    """
    out(BANNER)
    buffer = ""
    while ctx.running:
        prompt = _prompt(ctx.fsm.state, buffer)
        try:
            line = input_fn(prompt)
        except (EOFError, KeyboardInterrupt):
            out("")
            break
        log.debug("input: %r", line)

        if ctx.fsm.state is State.CONFIRM:
            buffer = ""
            _handle_confirm(ctx, line, out, err)
            continue

        buffer = f"{buffer}\n{line}" if buffer else line
        if not _is_complete(buffer):
            continue
        source, buffer = buffer, ""
        if not source.strip():
            continue
        _execute(ctx, source, out, err)

    log.info("repl loop finished")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``sp`` console script and ``python -m sp``."""
    parser = argparse.ArgumentParser(
        prog="sp",
        description="minimum video editor REPL (sexpistol s-expressions over OTIO + FFmpeg)",
    )
    parser.add_argument(
        "-c", "--command", metavar="SEXP", help="evaluate one s-expression and exit"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="mirror sp.log to the console")
    parser.add_argument("--version", action="version", version=f"sp {__version__}")
    args = parser.parse_args(argv)

    setup_logging(verbose=args.verbose)
    log.debug("starting sp (argv=%r, command=%r)", argv, args.command)
    ctx = bootstrap()
    try:
        if args.command is not None:
            results: list[str] = []
            errors: list[str] = []
            _execute(ctx, args.command, results.append, errors.append)
            for line in results:
                print(line)
            for line in errors:
                print(line, file=sys.stderr)
            return 1 if errors else 0
        return run_repl(ctx)
    except KeyboardInterrupt:
        print()
        log.info("interrupted")
        return 130
