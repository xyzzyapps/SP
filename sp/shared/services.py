"""Service locator.

Interfaces (``probe``, ``renderer``, ``session``) are registered as
factory callables by name and resolved lazily.  Tests swap in fakes by
re-registering a factory on the shared :data:`registry` instance and
calling :meth:`ServiceLocator.reset`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .errors import SpError


class ServiceLocator:
    """A minimal register/get registry of named service factories."""

    def __init__(self) -> None:
        self._factories: dict[str, Callable[[], Any]] = {}
        self._instances: dict[str, Any] = {}

    def register(self, name: str, factory: Callable[[], Any]) -> None:
        """Register (or replace) the factory for *name*; clears its instance."""
        self._factories[name] = factory
        self._instances.pop(name, None)

    def get(self, name: str) -> Any:
        """Resolve *name*, creating and caching the instance on first use."""
        if name not in self._instances:
            factory = self._factories.get(name)
            if factory is None:
                raise SpError(f"unknown service: {name!r}")
            self._instances[name] = factory()
        return self._instances[name]

    def reset(self) -> None:
        """Drop cached instances (factories are kept)."""
        self._instances.clear()


#: Shared process-wide locator used by the application bootstrap.
registry = ServiceLocator()
