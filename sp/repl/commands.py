"""Command table for the REPL: s-expression head -> handler function.

Handlers receive the :class:`ReplContext` plus parsed arguments and
return a string to print (or ``None``).  Failures raise
:class:`~sp.shared.errors.SpError` subclasses; arity is validated by
:func:`Commands.dispatch` before the handler runs, mirroring an IRB
method-call experience.
"""

from __future__ import annotations

import platform
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import opentimelineio as otio

from sp import __version__
from sp.media.render import Renderer
from sp.shared.errors import CommandError, ProcessError
from sp.shared.logging_setup import get_logger
from sp.shared.process import run
from sp.timeline.session import TimelineSession

from .state import ReplFsm

log = get_logger("repl.commands")

Handler = Callable[..., "str | None"]


@dataclass
class ReplContext:
    """Everything a command handler may touch during one REPL session."""

    session: TimelineSession
    renderer: Renderer
    fsm: ReplFsm
    commands: Commands | None = None
    running: bool = True


@dataclass(frozen=True)
class Command:
    """One registered REPL command."""

    name: str
    usage: str
    min_args: int
    max_args: int
    handler: Handler

    @property
    def doc(self) -> str:
        """First line of the handler docstring (shown by ``(help)``)."""
        doc = self.handler.__doc__ or ""
        return doc.strip().splitlines()[0] if doc.strip() else ""


class Commands:
    """Arity-checked dispatch table for REPL commands."""

    def __init__(self) -> None:
        self._commands: dict[str, Command] = {}

    def register(
        self,
        name: str,
        usage: str,
        min_args: int,
        max_args: int,
        handler: Handler,
    ) -> None:
        """Register *handler* under *name* with an arity range."""
        if name in self._commands:
            raise CommandError(f"command already registered: {name}")
        self._commands[name] = Command(name, usage, min_args, max_args, handler)
        log.debug("registered command %s (%s)", name, usage)

    @property
    def names(self) -> list[str]:
        """Registered command names in registration order."""
        return list(self._commands)

    def help(self) -> str:
        """The ``(help)`` payload: usage line per command."""
        lines = ["commands:"]
        for cmd in self._commands.values():
            lines.append(f"  {cmd.usage:<24} {cmd.doc}")
        lines.append("")
        lines.append('numbers are seconds; strings need double quotes, e.g. (open "a.mp4")')
        return "\n".join(lines)

    def dispatch(self, form: list, ctx: ReplContext) -> str | None:
        """Run one parsed command form against *ctx*.

        Raises:
            CommandError: unknown command, bad shape, or wrong arity.
        """
        if not form:
            raise CommandError("expected a (command ...) form, got ()")
        head = form[0]
        if not isinstance(head, str):
            raise CommandError(f"command name must be a symbol, got {head!r}")
        name = str(head)
        cmd = self._commands.get(name)
        if cmd is None:
            raise CommandError(f"unknown command: {name} — (help) lists commands")
        args = form[1:]
        if len(args) < cmd.min_args or len(args) > cmd.max_args:
            raise CommandError(f"usage: {cmd.usage}")
        log.info("command %s args=%r", name, args)
        return cmd.handler(ctx, *args)


# --------------------------------------------------------------------------
# handlers
# --------------------------------------------------------------------------
def _number(value: object, label: str) -> float:
    """Coerce a parsed argument to a non-bool float."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CommandError(f"{label} must be a number, got {value!r}")
    return float(value)


def _require_string(value: object, usage: str) -> str:
    """Coerce a parsed argument to a string (quotes in the s-expression)."""
    if not isinstance(value, str):
        raise CommandError(f"usage: {usage}")
    return str(value)


def _open(ctx: ReplContext, path: object) -> str:
    """(open "file") — probe a media file and append it to the timeline."""
    target = _require_string(path, '(open "clip.mp4")')
    info = ctx.session.open(target)
    return f"opened: {info.describe()}"


def _trim(ctx: ReplContext, start: object, end: object) -> str:
    """(trim start end) — keep [start, end) seconds of the last clip."""
    s = _number(start, "start")
    e = _number(end, "end")
    ctx.session.trim(s, e)
    clip = ctx.session.clips[-1]
    return f"trimmed {clip.name} to [{s:g}, {e:g})s — timeline {ctx.session.duration:.3f}s"


def _timeline(ctx: ReplContext) -> str:
    """(timeline) — show the timeline structure and per-clip details."""
    return ctx.session.summary()


def _render(ctx: ReplContext, out: object) -> str:
    """(render "out.mp4") — plan the render, show the command, ask y/N."""
    target = _require_string(out, '(render "out.mp4")')
    parent = Path(target).parent
    if not parent.exists():
        raise CommandError(f"directory does not exist: {parent}")
    plan = ctx.session.flatten()
    ctx.fsm.request_render(plan, target)
    return (
        f"render {len(plan.segments)} segment(s), {plan.duration:.3f}s, "
        f"{plan.width}x{plan.height} @{plan.rate:g}fps via {ctx.renderer.name}:\n"
        f"  {ctx.renderer.explain(plan, target)}\n"
        "Proceed? [y/N]"
    )


def _tool_line(exe: str, args: list[str]) -> str:
    """Format ``<exe> <args>`` availability/version for ``(doctor)``."""
    path = shutil.which(exe)
    if path is None:
        return f"  {exe:<16} NOT FOUND"
    try:
        proc = run([path, *args])
    except ProcessError as exc:
        return f"  {exe:<16} error: {exc}"
    first = (proc.stdout or "").strip().splitlines()
    return f"  {exe:<16} {first[0] if first else path}"


def _doctor(ctx: ReplContext) -> str:
    """(doctor) — report interpreter, OTIO and external tool availability."""
    lines = [
        f"sp {__version__}",
        f"  {'python':<16} {platform.python_version()} ({platform.platform()})",
        f"  {'opentimelineio':<16} {otio.__version__}",
        "tools:",
        _tool_line("ffmpeg", ["-version"]),
        _tool_line("ffprobe", ["-version"]),
        _tool_line("toucan-render", ["-h"]),
        "state:",
        f"  {'renderer':<16} {ctx.renderer.name}",
        f"  {'timeline':<16} {ctx.session.clip_count} clip(s), {ctx.session.duration:.3f}s",
    ]
    if shutil.which("toucan-render") is None:
        lines.insert(7, "  (toucan-render absent: render falls back to ffmpeg)")
    return "\n".join(lines)


def _help(ctx: ReplContext) -> str:
    """(help) — list every command with usage."""
    if ctx.commands is None:
        return "no commands registered"
    return ctx.commands.help()


def _quit(ctx: ReplContext) -> str:
    """(quit) — leave the REPL."""
    ctx.running = False
    return "bye"


def build_commands() -> Commands:
    """Assemble the default command table (the whole command surface)."""
    table = Commands()
    table.register("open", '(open "file")', 1, 1, _open)
    table.register("trim", "(trim start end)", 2, 2, _trim)
    table.register("timeline", "(timeline)", 0, 0, _timeline)
    table.register("render", '(render "out.mp4")', 1, 1, _render)
    table.register("doctor", "(doctor)", 0, 0, _doctor)
    table.register("help", "(help)", 0, 0, _help)
    table.register("quit", "(quit)", 0, 0, _quit)
    return table
