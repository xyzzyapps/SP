"""Error hierarchy for sp.

Every error raised by sp derives from :class:`SpError` so the REPL loop
can catch a single type, log the traceback, print a friendly message and
keep the session alive (IRB style).
"""

from __future__ import annotations

from collections.abc import Sequence


class SpError(Exception):
    """Base class for all errors raised by sp."""


class ParseError(SpError):
    """An s-expression could not be parsed.

    Attributes:
        pos: character offset where parsing failed, or ``-1`` if unknown.
        incomplete: ``True`` when the input ended prematurely (open list
            or unterminated string) so the REPL can request more lines.
    """

    def __init__(self, message: str, pos: int = -1, incomplete: bool = False) -> None:
        super().__init__(message)
        self.pos = pos
        self.incomplete = incomplete

    def __str__(self) -> str:
        base = super().__str__()
        return f"{base} (at char {self.pos})" if self.pos >= 0 else base


class CommandError(SpError):
    """A REPL command was misused or failed (bad arity, trim out of range...)."""


class ProcessError(SpError):
    """An external process (ffprobe/ffmpeg/toucan-render) failed.

    The message always contains the full command line and the tail of
    stderr so the invocation can be replayed by hand from ``sp.log``.
    """

    def __init__(self, cmd: Sequence[str], returncode: int, stderr: str = "") -> None:
        self.cmd = list(cmd)
        self.returncode = returncode
        self.stderr = stderr
        tail = stderr.strip().splitlines()[-1] if stderr.strip() else ""
        message = f"{' '.join(str(c) for c in cmd)} exited {returncode}"
        if tail:
            message = f"{message}: {tail}"
        super().__init__(message)
