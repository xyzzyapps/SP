"""Shared modules: service locator, process runner, logging bootstrap."""

from __future__ import annotations

import sys

import pytest

from sp.shared.errors import ProcessError, SpError
from sp.shared.logging_setup import get_logger, setup_logging
from sp.shared.process import run
from sp.shared.services import ServiceLocator

# --- service locator -------------------------------------------------------


def test_get_creates_and_caches_the_instance():
    loc = ServiceLocator()
    calls: list[int] = []
    loc.register("thing", lambda: calls.append(1) or object())
    first = loc.get("thing")
    second = loc.get("thing")
    assert first is second
    assert calls == [1]


def test_register_replaces_factory_and_invalidates_cache():
    loc = ServiceLocator()
    loc.register("thing", lambda: "old")
    assert loc.get("thing") == "old"
    loc.register("thing", lambda: "new")
    assert loc.get("thing") == "new"


def test_unknown_service_raises_sperror():
    with pytest.raises(SpError, match="unknown service"):
        ServiceLocator().get("nope")


def test_reset_drops_cached_instances_but_keeps_factories():
    loc = ServiceLocator()
    calls: list[int] = []
    loc.register("thing", lambda: calls.append(1) or object())
    loc.get("thing")
    loc.reset()
    loc.get("thing")
    assert calls == [1, 1]


# --- process runner --------------------------------------------------------


def test_run_captures_stdout():
    proc = run([sys.executable, "-c", "print('hello-sp')"])
    assert "hello-sp" in proc.stdout
    assert proc.returncode == 0


def test_run_failure_raises_with_command_and_stderr_tail():
    cmd = [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"]
    with pytest.raises(ProcessError) as exc:
        run(cmd)
    assert "exited 3" in str(exc.value)
    assert "boom" in str(exc.value)
    assert exc.value.cmd[0] == sys.executable
    assert exc.value.returncode == 3


def test_run_missing_executable_raises_process_error():
    with pytest.raises(ProcessError, match="not-a-real-executable-xyz"):
        run(["not-a-real-executable-xyz", "--version"])


# --- logging ---------------------------------------------------------------


def test_setup_logging_writes_named_records_to_the_file(tmp_path):
    log_file = tmp_path / "sp-test.log"
    logger = setup_logging(log_file=log_file, force=True)
    assert logger.name == "sp"
    get_logger("unittest").warning("canary-in-the-log")
    text = log_file.read_text(encoding="utf-8")
    assert "canary-in-the-log" in text
    assert "sp.unittest" in text
    assert "WARNING" in text


def test_setup_logging_is_idempotent_without_force(tmp_path):
    first = setup_logging(log_file=tmp_path / "a.log", force=True)
    second = setup_logging(log_file=tmp_path / "b.log")
    assert first is second
    # the forced configuration is untouched: no b.log handler appeared
    assert not (tmp_path / "b.log").exists()
    setup_logging(log_file=tmp_path / "c.log", force=True)  # restore a file handler
