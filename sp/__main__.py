"""Allow ``python -m sp`` to behave like the ``sp`` console script."""

from .repl.loop import main

raise SystemExit(main())
