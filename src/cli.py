# SPDX-License-Identifier: Apache-2.0
"""stay-awake CLI — argparse + supervision of a `systemd-inhibit` child."""

import ctypes
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from typing import IO, Callable, Protocol

from duration import parse as parse_duration, InvalidDuration
from inhibit import build_argv
from progress import (
    format_end_line,
    format_remaining,
    format_start_line,
    format_start_line_command,
    pick_update_interval,
)


DEFAULT_DURATION = "8h"

USAGE = (
    "Usage:\n"
    "  stay-awake [<duration>]        hold sleep inhibitor for <duration> (default 8h)\n"
    "  stay-awake -- <cmd> [args...]  run <cmd> under the inhibitor; release on exit\n"
    "  stay-awake --list              list active systemd inhibitors\n"
    "  stay-awake --quiet ...         suppress start/countdown/end lines\n"
    "  stay-awake --help              show this help\n"
    "\n"
    "Duration grammar: <N>h, <N>m, or <N>s  (e.g. 8h, 30m, 5400s)"
)


class ProcessLike(Protocol):
    returncode: int | None
    def poll(self) -> int | None: ...
    def wait(self, timeout: float | None = ...) -> int: ...
    def terminate(self) -> None: ...
    def kill(self) -> None: ...
    def send_signal(self, sig: int) -> None: ...


Spawner = Callable[[list[str]], ProcessLike]
SignalHook = Callable[[int, Callable], object]


# PR_SET_PDEATHSIG: if the parent dies, deliver this signal to the child.
# This is the kernel-backed defense against an orphaned inhibitor when Python
# is SIGKILL'd or segfaults. Linux-only.
_PR_SET_PDEATHSIG = 1


def _preexec() -> None:
    """Runs in the child between fork() and exec(). Must not touch Python state."""
    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    libc.prctl(_PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0)
    os.setpgrp()
    signal.signal(signal.SIGINT, signal.SIG_DFL)


def _default_spawner(argv: list[str]) -> ProcessLike:
    return subprocess.Popen(argv, preexec_fn=_preexec)


def _split_dash_dash(argv: list[str]) -> tuple[list[str], list[str] | None]:
    try:
        i = argv.index("--")
    except ValueError:
        return argv, None
    return argv[:i], argv[i + 1 :]


def _install_forward(proc: ProcessLike, signal_hook: SignalHook) -> None:
    def _handler(sig, _frame):
        try:
            proc.send_signal(sig)
        except Exception:
            pass
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal_hook(sig, _handler)


def _normalize_rc(rc: int | None) -> int:
    """Map a `subprocess.Popen.returncode` to a POSIX shell exit code.

    Python reports signal death as `-N`; shells use `128+N`. Normalize so the
    end-line message and our own exit code agree with `$?` in the shell.
    """
    if rc is None:
        return 0
    if rc < 0:
        return 128 + (-rc)
    return rc


def _ensure_dead(proc: ProcessLike) -> int:
    """Make sure proc is terminated. Return its final rc."""
    if proc.returncode is not None:
        return proc.returncode
    try:
        proc.terminate()
        rc = proc.wait(timeout=2)
        if rc is not None:
            return rc
    except Exception:
        pass
    try:
        proc.kill()
        rc = proc.wait(timeout=2)
        if rc is not None:
            return rc
    except Exception:
        pass
    return proc.returncode if proc.returncode is not None else -9


def _run_duration(
    seconds: int,
    argv_out: list[str],
    *,
    spawner: Spawner,
    clock: Callable[[], float],
    now_fn: Callable[[], datetime],
    sleeper: Callable[[float], None],
    out: IO[str],
    is_tty: bool,
    quiet: bool,
    signal_hook: SignalHook,
) -> int:
    target_dt = now_fn() + timedelta(seconds=seconds)
    target_hhmm = target_dt.strftime("%H:%M")

    if not quiet:
        print(format_start_line(seconds, target_hhmm), file=out, flush=True)

    try:
        proc = spawner(argv_out)
    except FileNotFoundError:
        print("stay-awake: systemd-inhibit not found on PATH", file=out, flush=True)
        if not quiet:
            print(
                format_end_line(0, "error: systemd-inhibit not found",
                                target_hhmm=target_hhmm),
                file=out, flush=True,
            )
        return 127

    _install_forward(proc, signal_hook)
    start_t = clock()
    deadline = start_t + seconds
    reason: str | None = None
    rc: int | None = None

    try:
        rc = proc.poll()
        while rc is None:
            remaining = max(0, int(deadline - clock()))
            if remaining <= 0:
                break
            if is_tty and not quiet:
                out.write(f"\r{format_remaining(remaining, target_hhmm)}")
                out.flush()
            sleeper(pick_update_interval(remaining))
            rc = proc.poll()
        if rc is None:
            rc = proc.wait(timeout=5)
    except KeyboardInterrupt:
        reason = "interrupted"
    finally:
        if is_tty and not quiet:
            # Clear the countdown line before the end line.
            out.write("\r\033[2K")
            out.flush()
        if rc is None:
            rc = _ensure_dead(proc)
        rc_norm = _normalize_rc(rc)
        elapsed = max(0, int(clock() - start_t))
        if reason is None:
            if rc_norm == 0:
                reason = "timer elapsed"
            else:
                reason = f"systemd-inhibit exited rc={rc_norm}"
        if not quiet:
            print(
                format_end_line(elapsed, reason, target_hhmm=target_hhmm),
                file=out, flush=True,
            )

    if reason == "interrupted":
        return 130
    return rc_norm


def _run_command(
    argv_out: list[str],
    cmd_str: str,
    *,
    spawner: Spawner,
    clock: Callable[[], float],
    out: IO[str],
    quiet: bool,
    signal_hook: SignalHook,
) -> int:
    if not quiet:
        print(format_start_line_command(cmd_str), file=out, flush=True)

    try:
        proc = spawner(argv_out)
    except FileNotFoundError:
        print("stay-awake: systemd-inhibit not found on PATH", file=out, flush=True)
        if not quiet:
            print(
                format_end_line(0, "error: systemd-inhibit not found"),
                file=out, flush=True,
            )
        return 127

    _install_forward(proc, signal_hook)
    start_t = clock()
    reason: str | None = None
    rc: int | None = None

    try:
        rc = proc.wait()
    except KeyboardInterrupt:
        reason = "interrupted"
    finally:
        if rc is None:
            rc = _ensure_dead(proc)
        rc_norm = _normalize_rc(rc)
        elapsed = max(0, int(clock() - start_t))
        if reason is None:
            reason = f"command exited rc={rc_norm}"
        if not quiet:
            print(format_end_line(elapsed, reason), file=out, flush=True)

    if reason == "interrupted":
        return 130
    return rc_norm


def main(
    argv: list[str],
    *,
    spawner: Spawner = _default_spawner,
    clock: Callable[[], float] = time.monotonic,
    now_fn: Callable[[], datetime] = datetime.now,
    sleeper: Callable[[float], None] = time.sleep,
    out: IO[str] = sys.stderr,
    is_tty: bool | None = None,
    signal_hook: SignalHook = signal.signal,
) -> int:
    before, after = _split_dash_dash(list(argv))

    if "--help" in before or "-h" in before:
        print(USAGE)
        return 0

    quiet = "--quiet" in before
    if quiet:
        before = [t for t in before if t != "--quiet"]

    if "--list" in before:
        if len(before) != 1 or after is not None:
            print("stay-awake: --list takes no other arguments", file=sys.stderr)
            print(USAGE, file=sys.stderr)
            return 2
        try:
            proc = spawner(["systemd-inhibit", "--list"])
        except FileNotFoundError:
            print("stay-awake: systemd-inhibit not found on PATH", file=sys.stderr)
            return 127
        return proc.wait() or 0

    for tok in before:
        if tok.startswith("-") and tok not in ("--",):
            print(f"stay-awake: unknown option: {tok}", file=sys.stderr)
            print(USAGE, file=sys.stderr)
            return 2

    if is_tty is None:
        is_tty = bool(getattr(out, "isatty", lambda: False)())

    if after is not None:
        if before:
            print(
                "stay-awake: duration and '-- <command>' are mutually exclusive",
                file=sys.stderr,
            )
            print(USAGE, file=sys.stderr)
            return 2
        if not after:
            print("stay-awake: '--' requires a command", file=sys.stderr)
            print(USAGE, file=sys.stderr)
            return 2
        cmd_str = " ".join(after)
        why = f"stay-awake running: {cmd_str}"
        argv_out = build_argv(command=after, why=why)
        return _run_command(
            argv_out, cmd_str,
            spawner=spawner, clock=clock, out=out, quiet=quiet,
            signal_hook=signal_hook,
        )

    if len(before) > 1:
        print("stay-awake: too many arguments", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2

    raw = before[0] if before else DEFAULT_DURATION
    try:
        seconds = parse_duration(raw)
    except InvalidDuration as e:
        print(f"stay-awake: {e}", file=sys.stderr)
        return 2

    why = f"stay-awake sleep inhibit for {raw} ({seconds}s)"
    argv_out = build_argv(seconds=seconds, why=why)
    return _run_duration(
        seconds, argv_out,
        spawner=spawner, clock=clock, now_fn=now_fn, sleeper=sleeper,
        out=out, is_tty=is_tty, quiet=quiet, signal_hook=signal_hook,
    )


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
