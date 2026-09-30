"""Single choke point for external processes.

ffprobe/ffmpeg/toucan-render invocations all go through :func:`run` so
every command line, exit code and stderr line lands in ``sp.log``; any
failure can be replayed by hand from the log.  Callers inject their own
``runner`` callable in tests instead of spawning processes.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence

from .errors import ProcessError
from .logging_setup import get_logger

log = get_logger("process")

#: Signature shared by every runner injection point.
Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def run(
    cmd: Sequence[str],
    *,
    timeout: float | None = 600,
) -> subprocess.CompletedProcess[str]:
    """Run *cmd*, log everything, raise :class:`ProcessError` on failure."""
    display = " ".join(f'"{a}"' if " " in str(a) else str(a) for a in cmd)
    log.debug("exec: %s", display)
    try:
        proc = subprocess.run(  # noqa: S603 - command lines are built in code, not by users
            [str(c) for c in cmd],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise ProcessError(list(cmd), -1, str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise ProcessError(list(cmd), -1, f"timed out after {timeout}s") from exc
    log.debug("exit %d for: %s", proc.returncode, display)
    if proc.stderr:
        log.debug("stderr: %s", proc.stderr.strip())
    if proc.returncode != 0:
        raise ProcessError(list(cmd), proc.returncode, proc.stderr or proc.stdout or "")
    return proc
