"""Test doubles for every sp interface.

No subprocesses are spawned outside ``test_integration.py``: probes,
renderers, runners and the input loop are all replaced by these fakes.
"""

from __future__ import annotations

import subprocess

from sp.media.probe import MediaInfo
from sp.media.render import RenderPlan
from sp.shared.errors import CommandError, ProcessError


def media_info(
    path: str = "clip.mp4",
    *,
    duration: float = 4.0,
    rate: float = 25.0,
    width: int = 640,
    height: int = 360,
    has_audio: bool = True,
    codec: str = "h264",
) -> MediaInfo:
    """Shorthand builder for :class:`MediaInfo` test data."""
    return MediaInfo(
        path=path,
        duration=duration,
        rate=rate,
        width=width,
        height=height,
        has_video=True,
        has_audio=has_audio,
        codec=codec,
    )


class FakeProbe:
    """``Probe`` double: fixed path -> MediaInfo mapping."""

    def __init__(self, infos: dict[str, MediaInfo]) -> None:
        self.infos = dict(infos)
        self.probed: list[str] = []

    def probe(self, path: str) -> MediaInfo:
        self.probed.append(path)
        if path not in self.infos:
            raise CommandError(f"no such file: {path}")
        return self.infos[path]


class RecordingRunner:
    """Runner double (``shared.process.run`` shape): records calls.

    Raises :class:`ProcessError` for a configured nonzero returncode,
    mimicking the real runner's contract.
    """

    def __init__(self, stdout: str = "", returncode: int = 0, stderr: str = "") -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr
        self.calls: list[list[str]] = []

    def __call__(self, cmd, **kwargs) -> subprocess.CompletedProcess[str]:
        args = [str(c) for c in cmd]
        self.calls.append(args)
        if self.returncode != 0:
            raise ProcessError(args, self.returncode, self.stderr)
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout=self.stdout, stderr=self.stderr
        )


class FakeRenderer:
    """``Renderer`` double: records rendered plans, never touches disk."""

    name = "fake"

    def __init__(self) -> None:
        self.rendered: list[tuple[RenderPlan, str]] = []

    def explain(self, plan: RenderPlan, out: str) -> str:
        return f"fake-render {len(plan.segments)} segment(s) -> {out}"

    def render(self, plan: RenderPlan, out: str) -> None:
        self.rendered.append((plan, out))


class ScriptedInput:
    """``input()`` double: feeds scripted lines and records prompts.

    Raises EOFError once the script is exhausted, exactly like a
    terminal hitting Ctrl-D.
    """

    def __init__(self, lines: list[str]) -> None:
        self._lines = iter(lines)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        try:
            return next(self._lines)
        except StopIteration as exc:
            raise EOFError from exc
