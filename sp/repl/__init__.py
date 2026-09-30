"""Feature slice: the IRB-like REPL (parser + commands + loop)."""

from .loop import bootstrap, main, run_repl

__all__ = ["bootstrap", "main", "run_repl"]
