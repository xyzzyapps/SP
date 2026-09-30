"""Logging bootstrap.

Profuse logging goes to ``sp.log``: every REPL input, every external
command line, exit code, stderr line and every state-machine transition.
The console stays terse (warnings/errors only) so REPL results remain
readable; ``--verbose`` mirrors the file log to the console.
"""

from __future__ import annotations

import logging
from pathlib import Path

#: Log file written in the current working directory.
LOG_FILE = Path("sp.log")

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(
    verbose: bool = False,
    log_file: Path | str = LOG_FILE,
    *,
    force: bool = False,
) -> logging.Logger:
    """Configure the root ``sp`` logger; idempotent unless ``force=True``."""
    logger = logging.getLogger("sp")
    if logger.handlers:
        if not force:
            return logger
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
    logger.setLevel(logging.DEBUG)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if verbose else logging.WARNING)
    console.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(console)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger (``sp.<name>``)."""
    return logging.getLogger(f"sp.{name}")
