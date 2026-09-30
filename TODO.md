# TODO — `sp`: minimum video editor REPL

Vision: an IRB-like REPL where you type s-expressions to edit video.
Real wheels do the heavy lifting: **sexpistol** (ported to Python, syntax),
**OpenTimelineIO** (timeline model), **FFmpeg** (probe/render), **toucan** (renderer, deferred).

Status: **Phases 0–7 complete** — 107 tests green, ruff clean, smoke-tested end-to-end.

## Phase 0 — Setup

- [x] 0.1 Create `.venv` from Python 3.13 (OTIO has no cp314 wheels); install `opentimelineio`, `pytest`, `ruff`
- [x] 0.2 `git init`, `.gitignore`
- [x] 0.3 `pyproject.toml`: package `sp`, console script `sp`, pytest + ruff config

## Phase 1 — Shared modules (interfaces, data structures, service locator)

- [x] 1.1 `shared/errors.py` — `SpError` → `ParseError` (`.incomplete`), `CommandError`, `ProcessError`
- [x] 1.2 `shared/logging_setup.py` — stdlib logging: verbose file log `sp.log` + terse console (`-v` mirrors)
- [x] 1.3 `shared/services.py` — service locator (register/get by name, lazy cache, `reset()`)
- [x] 1.4 `shared/process.py` — single choke point for subprocess calls; logs argv, exit code, stderr to `sp.log`

## Phase 2 — Feature slice: `sexp` (sexpistol port)

- [x] 2.1 `sexp/parser.py` — `Symbol`, `parse()`, `to_sexp()` incl. `scheme_compatible`, opt-in `python_literals`
- [x] 2.2 `tests/test_sexp_parser.py` — sexpistol README examples verbatim + round-trip + error cases

## Phase 3 — Feature slice: `media` (ffmpeg)

- [x] 3.1 Data structures: `MediaInfo`, `Segment`, `RenderPlan` (+ `validate()`)
- [x] 3.2 `Probe` protocol; `Ffprobe` impl (JSON → `MediaInfo`); fake lives in `tests/fakes.py`
- [x] 3.3 `Renderer` protocol; `FfmpegRenderer` (filter-graph, `explain()` for the confirm prompt); `ToucanRenderer` (PATH-detected via `default_renderer()`)
- [x] 3.4 Tests: probe parsing from captured ffprobe JSON; render command construction (no subprocess)

## Phase 4 — Feature slice: `timeline` (OTIO)

- [x] 4.1 `timeline/session.py` — `TimelineSession`: `open`, `trim`, `summary`, `flatten`, `to_otio_json`, `write_otio`
- [x] 4.2 Tests with `FakeProbe`: append, trim bounds, flatten offsets, `.otio` round-trip via real adapter

## Phase 5 — Feature slice: `repl`

- [x] 5.1 `repl/commands.py` — `open`, `trim`, `timeline`, `render`, `doctor`, `help`, `quit`; arity checked pre-dispatch
- [x] 5.2 `repl/state.py` — FSM `READY ↔ CONFIRM` with events + transition listener (vex-style plan/y-N)
- [x] 5.3 `repl/loop.py` — `sp> ` prompt, multiline buffering via `ParseError.incomplete`, `-c` one-shot mode, clean EOF/Ctrl-C exit; `__main__.py`
- [x] 5.4 Tests: dispatch, arity errors, FSM transitions, scripted REPL sessions (confirm/cancel/multiline/EOF)

## Phase 6 — Integration

- [x] 6.1 Fixture generator: ffmpeg lavfi (`testsrc`/`sine`) inside `tmp_path` (no external assets)
- [x] 6.2 End-to-end test (skipped if ffmpeg missing): open → trim → render → ffprobe validates duration/geometry; `.otio` artifact round-trips

## Phase 7 — Quality + docs

- [x] 7.1 `ruff format` + `ruff check` + `pytest` all green (107 tests)
- [x] 7.2 `SPEC.md` — SRS with architecture, data-flow, FSM diagrams; command reference; extension points
- [x] 7.3 `README.md` — install, run, example session
- [x] 7.4 Final commit

## Deferred (explicitly out of scope for "absolute minimum")

- [ ] D.1 Build toucan on Windows (`sbuild-win.bat`, VS2022+CMake+MSYS2 superbuild) — until then `render` uses FFmpeg, auto-switches when `toucan-render` appears on PATH (no code change needed)
- [ ] D.2 Undo/redo, projects, persistence beyond writing `.otio`
- [ ] D.3 Multi-track, transitions, effects
- [ ] D.4 Frame-accurate argument notation (`123f`) — `_number()` in `sp/repl/commands.py`
