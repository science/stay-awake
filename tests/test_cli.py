"""Tests for cli.py — arg parsing, dispatch, supervision loop, failure paths."""

from datetime import datetime
import io
import signal

import pytest

from cli import main


# ---------------------------------------------------------------------------
# Test doubles

class _FakeClock:
    """Virtual clock for testing the supervision loop deterministically."""

    def __init__(self, start: float = 1000.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


class _FakeProcess:
    """Process-like. `runtime_s` = virtual seconds before `poll()` returns rc."""

    def __init__(self, *, rc: int = 0, runtime_s: float | None = None,
                 clock: _FakeClock | None = None):
        self.rc = rc
        self.runtime_s = runtime_s
        self.clock = clock
        self.start_t = clock() if clock else 0.0
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False
        self.signals: list[int] = []

    def poll(self) -> int | None:
        if self.returncode is not None:
            return self.returncode
        if self.runtime_s is not None and self.clock:
            if self.clock() - self.start_t >= self.runtime_s:
                self.returncode = self.rc
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        p = self.poll()
        if p is not None:
            return p
        # Simulate the child finishing; tests advance the clock manually when
        # they want a pre-deadline finish, so reaching wait means "we're done".
        self.returncode = self.rc
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        if self.returncode is None:
            self.returncode = 143

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def send_signal(self, sig: int) -> None:
        self.signals.append(sig)


class _FakeSpawner:
    """Records argvs; returns a pre-built FakeProcess (or raises)."""

    def __init__(self, *, proc: _FakeProcess | None = None,
                 raise_on_spawn: BaseException | None = None):
        self.calls: list[list[str]] = []
        self._proc = proc
        self._raise = raise_on_spawn
        self.last_proc: _FakeProcess | None = None

    def __call__(self, argv: list[str]) -> _FakeProcess:
        self.calls.append(list(argv))
        if self._raise is not None:
            raise self._raise
        if self._proc is None:
            self._proc = _FakeProcess(rc=0)
        self.last_proc = self._proc
        return self._proc


class _SignalRecorder:
    def __init__(self):
        self.calls: list[tuple[int, object]] = []

    def __call__(self, sig: int, handler) -> None:
        self.calls.append((sig, handler))


def _fixed_now(dt: datetime):
    """Return a `now_fn` that always returns `dt`."""
    return lambda: dt


# ---------------------------------------------------------------------------
# Fixtures

@pytest.fixture
def clock():
    return _FakeClock()


@pytest.fixture
def now_fn():
    # Wed 2026-04-19 21:30:00 → target for 8h is 05:30 the next day
    return _fixed_now(datetime(2026, 4, 19, 21, 30, 0))


@pytest.fixture
def sig_hook():
    return _SignalRecorder()


def _spy_call(spawner, clock, proc=None):
    """Convenience to build a spawner backed by a process bound to clock."""
    if proc is None:
        proc = _FakeProcess(clock=clock)
    sp = _FakeSpawner(proc=proc)
    return sp


# ---------------------------------------------------------------------------
# Argv shape (carried over from the exec-wrapper tests)

def _call(main_args, spawner, clock, now_fn, sig_hook, *, is_tty=False, out=None):
    out = out if out is not None else io.StringIO()
    return main(
        main_args,
        spawner=spawner,
        clock=clock,
        now_fn=now_fn,
        sleeper=clock.sleep,
        out=out,
        is_tty=is_tty,
        signal_hook=sig_hook,
    ), out


class TestArgvShape:
    """What we hand to the spawner — preserved from the exec-wrapper era."""

    def test_duration_argv(self, clock, now_fn, sig_hook):
        proc = _FakeProcess(rc=0, runtime_s=28800, clock=clock)
        sp = _FakeSpawner(proc=proc)
        rc, _ = _call(["8h"], sp, clock, now_fn, sig_hook)
        assert rc == 0
        assert len(sp.calls) == 1
        argv = sp.calls[0]
        assert argv[0] == "systemd-inhibit"
        assert "--what=sleep" in argv
        assert "--who=stay-awake" in argv
        assert argv[-2:] == ["sleep", "28800"]

    def test_minutes(self, clock, now_fn, sig_hook):
        proc = _FakeProcess(runtime_s=1800, clock=clock)
        sp = _FakeSpawner(proc=proc)
        _call(["30m"], sp, clock, now_fn, sig_hook)
        assert sp.calls[0][-2:] == ["sleep", "1800"]

    def test_default_is_eight_hours(self, clock, now_fn, sig_hook):
        proc = _FakeProcess(runtime_s=28800, clock=clock)
        sp = _FakeSpawner(proc=proc)
        rc, _ = _call([], sp, clock, now_fn, sig_hook)
        assert rc == 0
        assert sp.calls[0][-2:] == ["sleep", "28800"]

    def test_command_after_dash_dash(self, clock, now_fn, sig_hook):
        sp = _FakeSpawner(proc=_FakeProcess(rc=0))
        rc, _ = _call(["--", "bash", "-c", "echo hi"], sp, clock, now_fn, sig_hook)
        assert rc == 0
        argv = sp.calls[0]
        assert argv[-3:] == ["bash", "-c", "echo hi"]
        assert "--what=sleep" in argv
        assert "--who=stay-awake" in argv

    def test_command_with_flags(self, clock, now_fn, sig_hook):
        sp = _FakeSpawner(proc=_FakeProcess(rc=0))
        _call(["--", "python3", "-m", "pytest", "-q"], sp, clock, now_fn, sig_hook)
        assert sp.calls[0][-4:] == ["python3", "-m", "pytest", "-q"]

    def test_why_mentions_duration(self, clock, now_fn, sig_hook):
        proc = _FakeProcess(runtime_s=7200, clock=clock)
        sp = _FakeSpawner(proc=proc)
        _call(["2h"], sp, clock, now_fn, sig_hook)
        why = next(a for a in sp.calls[0] if a.startswith("--why="))
        assert "2h" in why or "7200" in why

    def test_why_mentions_command(self, clock, now_fn, sig_hook):
        sp = _FakeSpawner(proc=_FakeProcess(rc=0))
        _call(["--", "make", "train"], sp, clock, now_fn, sig_hook)
        why = next(a for a in sp.calls[0] if a.startswith("--why="))
        assert "make" in why


# ---------------------------------------------------------------------------
# Usage errors

class TestUsageErrors:
    def test_invalid_duration(self, clock, now_fn, sig_hook):
        sp = _FakeSpawner()
        rc, out = _call(["bogus"], sp, clock, now_fn, sig_hook)
        assert rc == 2
        assert sp.calls == []

    def test_empty_command_after_dash_dash(self, clock, now_fn, sig_hook):
        sp = _FakeSpawner()
        rc, _ = _call(["--"], sp, clock, now_fn, sig_hook)
        assert rc == 2
        assert sp.calls == []

    def test_duration_and_command_together(self, clock, now_fn, sig_hook):
        sp = _FakeSpawner()
        rc, _ = _call(["8h", "--", "true"], sp, clock, now_fn, sig_hook)
        assert rc == 2
        assert sp.calls == []

    def test_unknown_flag(self, clock, now_fn, sig_hook):
        sp = _FakeSpawner()
        rc, _ = _call(["--unknown"], sp, clock, now_fn, sig_hook)
        assert rc == 2
        assert sp.calls == []


# ---------------------------------------------------------------------------
# Help and --list

class TestHelpAndList:
    def test_help_prints_usage(self, clock, now_fn, sig_hook, capsys):
        sp = _FakeSpawner()
        rc, _ = _call(["--help"], sp, clock, now_fn, sig_hook)
        assert rc == 0
        assert sp.calls == []
        assert "usage" in capsys.readouterr().out.lower()

    def test_short_help(self, clock, now_fn, sig_hook, capsys):
        sp = _FakeSpawner()
        rc, _ = _call(["-h"], sp, clock, now_fn, sig_hook)
        assert rc == 0
        assert "usage" in capsys.readouterr().out.lower()

    def test_list_spawns_systemd_inhibit_list(self, clock, now_fn, sig_hook):
        sp = _FakeSpawner(proc=_FakeProcess(rc=0))
        rc, _ = _call(["--list"], sp, clock, now_fn, sig_hook)
        assert rc == 0
        assert sp.calls[0] == ["systemd-inhibit", "--list"]


# ---------------------------------------------------------------------------
# Supervision: duration mode

class TestDurationSupervision:
    def test_prints_start_and_end_lines(self, clock, now_fn, sig_hook):
        proc = _FakeProcess(runtime_s=28800, clock=clock)
        sp = _FakeSpawner(proc=proc)
        rc, out = _call(["8h"], sp, clock, now_fn, sig_hook, is_tty=False)
        text = out.getvalue()
        assert rc == 0
        assert "holding sleep inhibitor until 05:30 (8h 0m)" in text
        assert "released after 8h 0m (timer elapsed, target was 05:30)" in text

    def test_countdown_rendered_when_tty(self, clock, now_fn, sig_hook):
        proc = _FakeProcess(runtime_s=60, clock=clock)
        sp = _FakeSpawner(proc=proc)
        rc, out = _call(["60s"], sp, clock, now_fn, sig_hook, is_tty=True)
        text = out.getvalue()
        assert rc == 0
        assert "\r" in text
        # At least one intermediate countdown frame
        assert " remaining (until" in text

    def test_no_countdown_when_not_tty(self, clock, now_fn, sig_hook):
        proc = _FakeProcess(runtime_s=60, clock=clock)
        sp = _FakeSpawner(proc=proc)
        rc, out = _call(["60s"], sp, clock, now_fn, sig_hook, is_tty=False)
        text = out.getvalue()
        assert rc == 0
        assert "\r" not in text
        # Start and end lines still present
        assert "holding" in text
        assert "released after" in text

    def test_signal_handlers_installed(self, clock, now_fn, sig_hook):
        proc = _FakeProcess(runtime_s=60, clock=clock)
        sp = _FakeSpawner(proc=proc)
        _call(["60s"], sp, clock, now_fn, sig_hook)
        signums = {s for s, _ in sig_hook.calls}
        assert signal.SIGTERM in signums
        assert signal.SIGHUP in signums

    def test_immediate_child_crash(self, clock, now_fn, sig_hook):
        # Process already has a returncode from the first poll
        proc = _FakeProcess(rc=5, clock=clock)
        proc.returncode = 5  # pre-crashed
        sp = _FakeSpawner(proc=proc)
        rc, out = _call(["10m"], sp, clock, now_fn, sig_hook, is_tty=False)
        assert rc == 5
        text = out.getvalue()
        assert "systemd-inhibit exited rc=5" in text


# ---------------------------------------------------------------------------
# Supervision: command mode

class TestCommandSupervision:
    def test_command_rc_propagates(self, clock, now_fn, sig_hook):
        sp = _FakeSpawner(proc=_FakeProcess(rc=7))
        rc, out = _call(["--", "false"], sp, clock, now_fn, sig_hook, is_tty=False)
        assert rc == 7
        text = out.getvalue()
        assert "holding sleep inhibitor for: false" in text
        assert "command exited rc=7" in text

    def test_command_success(self, clock, now_fn, sig_hook):
        sp = _FakeSpawner(proc=_FakeProcess(rc=0))
        rc, out = _call(["--", "true"], sp, clock, now_fn, sig_hook, is_tty=False)
        assert rc == 0
        assert "command exited rc=0" in out.getvalue()

    def test_command_mode_no_countdown_even_on_tty(self, clock, now_fn, sig_hook):
        sp = _FakeSpawner(proc=_FakeProcess(rc=0))
        rc, out = _call(["--", "true"], sp, clock, now_fn, sig_hook, is_tty=True)
        text = out.getvalue()
        assert "\r" not in text  # no in-place frames in command mode


# ---------------------------------------------------------------------------
# Failure paths

class TestFailurePaths:
    def test_systemd_inhibit_missing_duration_mode(self, clock, now_fn, sig_hook):
        sp = _FakeSpawner(raise_on_spawn=FileNotFoundError("systemd-inhibit"))
        rc, out = _call(["1h"], sp, clock, now_fn, sig_hook, is_tty=False)
        assert rc == 127
        text = out.getvalue()
        assert "systemd-inhibit not found" in text

    def test_systemd_inhibit_missing_command_mode(self, clock, now_fn, sig_hook):
        sp = _FakeSpawner(raise_on_spawn=FileNotFoundError("systemd-inhibit"))
        rc, out = _call(["--", "true"], sp, clock, now_fn, sig_hook, is_tty=False)
        assert rc == 127
        assert "systemd-inhibit not found" in out.getvalue()

    def test_keyboard_interrupt_duration_mode(self, clock, now_fn, sig_hook):
        """sleeper raises KeyboardInterrupt mid-loop → rc=130, interrupted."""
        proc = _FakeProcess(runtime_s=3600, clock=clock)
        sp = _FakeSpawner(proc=proc)

        original_sleep = clock.sleep
        call_count = [0]

        def kaboom_sleep(s):
            call_count[0] += 1
            if call_count[0] >= 2:
                raise KeyboardInterrupt
            original_sleep(s)

        rc = main(
            ["1h"],
            spawner=sp,
            clock=clock,
            now_fn=now_fn,
            sleeper=kaboom_sleep,
            out=io.StringIO(),
            is_tty=False,
            signal_hook=sig_hook,
        )
        assert rc == 130
        # Child was terminated as part of cleanup
        assert proc.terminated is True


# ---------------------------------------------------------------------------
# Quiet mode

class TestRcNormalization:
    """Negative proc.returncode (signal death) → POSIX 128+signo convention."""

    def test_duration_mode_sigterm(self, clock, now_fn, sig_hook):
        # Child dies of SIGTERM before deadline → proc.returncode = -15
        proc = _FakeProcess(clock=clock)
        proc.returncode = -15  # pre-set; first poll() will return it
        sp = _FakeSpawner(proc=proc)
        rc, out = _call(["10m"], sp, clock, now_fn, sig_hook, is_tty=False)
        assert rc == 143  # 128 + 15
        assert "systemd-inhibit exited rc=143" in out.getvalue()

    def test_command_mode_sigkill(self, clock, now_fn, sig_hook):
        proc = _FakeProcess(rc=-9)
        sp = _FakeSpawner(proc=proc)
        rc, out = _call(["--", "true"], sp, clock, now_fn, sig_hook, is_tty=False)
        assert rc == 137  # 128 + 9
        assert "command exited rc=137" in out.getvalue()


class TestQuiet:
    def test_quiet_suppresses_all_stderr_output(self, clock, now_fn, sig_hook):
        proc = _FakeProcess(runtime_s=60, clock=clock)
        sp = _FakeSpawner(proc=proc)
        rc, out = _call(["--quiet", "60s"], sp, clock, now_fn, sig_hook, is_tty=True)
        assert rc == 0
        assert out.getvalue() == ""  # nothing printed

    def test_quiet_still_supervises(self, clock, now_fn, sig_hook):
        proc = _FakeProcess(runtime_s=60, clock=clock)
        sp = _FakeSpawner(proc=proc)
        rc, out = _call(["--quiet", "60s"], sp, clock, now_fn, sig_hook, is_tty=True)
        assert len(sp.calls) == 1  # did spawn the child
        assert rc == 0

    def test_quiet_in_command_mode(self, clock, now_fn, sig_hook):
        sp = _FakeSpawner(proc=_FakeProcess(rc=0))
        rc, out = _call(["--quiet", "--", "true"], sp, clock, now_fn, sig_hook)
        assert rc == 0
        assert out.getvalue() == ""
