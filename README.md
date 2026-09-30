# sp — minimum video editor REPL

An IRB-like REPL for editing video by typing s-expressions.
Three wheels do the heavy lifting — nothing is reinvented:

- **[sexpistol](https://github.com/aarongough/sexpistol)** grammar, ported to Python → the command syntax
- **OpenTimelineIO** → the real timeline model (`.otio` in memory)
- **FFmpeg** → probe + render (auto-switches to **toucan** when `toucan-render` is on PATH)

```
sp 0.1.0 — minimum video editor repl
type (help) for commands, (quit) to exit; every session logs to sp.log
sp> (open "tests/fixtures/a.mp4")
opened: tests/fixtures/a.mp4: 640x360 @25fps, 4.00s, h264 + audio
sp> (trim 1 3)
trimmed a.mp4 to [1, 3)s — timeline 2.000s
sp> (timeline)
timeline "sp"  2.000s  1 clip(s)  rate 25
  V1:
    [1] a.mp4  timeline 1.000->3.000s  (640x360 @25fps, h264)
sp> (render "out.mp4")
render 1 segment(s), 2.000s, 640x360 @25fps via ffmpeg:
  ffmpeg -hide_banner ... -crf 20 out.mp4
Proceed? [y/N]
sp(y/N)> y
rendered out.mp4 (2.000s, 640x360)
```

## Requirements

- **Python 3.13** (OpenTimelineIO wheels do not exist for 3.14 yet)
- **ffmpeg / ffprobe** on `PATH`
- Windows, macOS or Linux

## Install

```powershell
# from the repo root
py -V:3.13 -m venv .venv        # or any Python 3.13 interpreter
.venv\Scripts\pip install -e .[dev]
```

## Usage

```powershell
.venv\Scripts\sp                 # interactive REPL
.venv\Scripts\sp -c "(doctor)"   # one-shot command (exit 1 on error)
.venv\Scripts\sp -v              # mirror the log to the console
python -m sp                     # equivalent entry point
```

### Commands

| Form | Effect |
|---|---|
| `(open "file")` | probe the file, append it to the timeline |
| `(trim start end)` | keep `[start, end)` seconds of the **last** clip |
| `(timeline)` | print the timeline structure |
| `(render "out.mp4")` | show the planned FFmpeg command, ask `y/N`, render |
| `(doctor)` | report tool availability (ffmpeg, ffprobe, toucan…) |
| `(help)` | command list |
| `(quit)` | exit (EOF/Ctrl-C also works) |

Multi-line input is supported — keep typing until the parens balance.
Strings use backslash escapes, so on Windows prefer forward slashes:
`(open "tests/fixtures/a.mp4")`.

## Development

```powershell
.venv\Scripts\ruff format .
.venv\Scripts\ruff check .
.venv\Scripts\python -m pytest      # 107 tests; integration tests generate their own media
```

Everything external is behind an interface (`Probe`, `Renderer`, `Runner`),
so tests run without spawning processes; the end-to-end test is skipped
automatically when FFmpeg is missing. Every REPL input, external command
line and state transition is written to **`sp.log`** — when something
breaks, the logged FFmpeg command can be copied out and replayed by hand.

See [SPEC.md](SPEC.md) for the full architecture (slice diagram, data
flow, FSM, interfaces, extension points) and [TODO.md](TODO.md) for the
task board incl. deferred work (toucan build, undo/redo, multi-track).

## Layout

```
sp/shared/    errors, logging, service locator, subprocess choke point
sp/sexp/      sexpistol port: parse() / to_sexp()
sp/media/     ffprobe + ffmpeg/toucan renderers + RenderPlan
sp/timeline/  OTIO session: open / trim / flatten / write .otio
sp/repl/      FSM, command table, REPL loop + CLI entry
tests/        fakes + unit + integration tests
```

MIT licensed.
