# SPDX-License-Identifier: Apache-2.0
"""stay-awake CLI — argparse + dispatch to systemd-inhibit."""

import os
import sys
from typing import Callable

from duration import parse as parse_duration, InvalidDuration
from inhibit import build_argv


DEFAULT_DURATION = "8h"

USAGE = (
    "Usage:\n"
    "  stay-awake [<duration>]        hold sleep inhibitor for <duration> (default 8h)\n"
    "  stay-awake -- <cmd> [args...]  run <cmd> under the inhibitor; release on exit\n"
    "  stay-awake --list              list active systemd inhibitors\n"
    "  stay-awake --help              show this help\n"
    "\n"
    "Duration grammar: <N>h, <N>m, or <N>s  (e.g. 8h, 30m, 5400s)"
)


Executor = Callable[[str, list[str]], None]


def _split_dash_dash(argv: list[str]) -> tuple[list[str], list[str] | None]:
    """Split argv at the first `--`. Returns (before, after or None)."""
    try:
        i = argv.index("--")
    except ValueError:
        return argv, None
    return argv[:i], argv[i + 1 :]


def _print_help() -> None:
    print(USAGE)


def main(argv: list[str], *, executor: Executor = os.execvp) -> int:
    """Parse `argv` (no program name) and dispatch.

    Returns an exit code on error. On the success path, the executor replaces
    this process and does not return; for tests, the executor is a spy that
    records the call and returns normally.
    """
    before, after = _split_dash_dash(list(argv))

    # Help takes precedence everywhere.
    if "--help" in before or "-h" in before:
        _print_help()
        return 0

    # --list is a standalone command.
    if "--list" in before:
        if len(before) != 1 or after is not None:
            print("stay-awake: --list takes no other arguments", file=sys.stderr)
            print(USAGE, file=sys.stderr)
            return 2
        executor("systemd-inhibit", ["systemd-inhibit", "--list"])
        return 0

    # Reject unknown flags before trying to interpret them as durations.
    for tok in before:
        if tok.startswith("-") and tok not in ("--",):
            print(f"stay-awake: unknown option: {tok}", file=sys.stderr)
            print(USAGE, file=sys.stderr)
            return 2

    if after is not None:
        # Command mode: no duration before --.
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
        why = f"stay-awake running: {' '.join(after)}"
        argv_out = build_argv(command=after, why=why)
        executor("systemd-inhibit", argv_out)
        return 0

    # Duration mode.
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
    executor("systemd-inhibit", argv_out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
