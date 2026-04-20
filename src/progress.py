# SPDX-License-Identifier: Apache-2.0
"""Pure formatting helpers for stay-awake's start line, countdown, and summary.

No I/O, no wall-clock access — the caller passes `target_hhmm` as a string so
this module stays trivially testable.
"""


def format_duration(seconds: int) -> str:
    """Render seconds as `Xh Ym` / `Xm Ys` / `Xs` (2 units above 60s, 1 below)."""
    if seconds < 60:
        return f"{max(0, seconds)}s"
    if seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"{m}m {s}s"
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    return f"{h}h {m}m"


def pick_update_interval(seconds_left: int) -> int:
    """Pick countdown update cadence: 1s below 1m, 10s below 1h, 60s above."""
    if seconds_left < 60:
        return 1
    if seconds_left < 3600:
        return 10
    return 60


def format_remaining(seconds_left: int, target_hhmm: str) -> str:
    clamped = max(0, seconds_left)
    return f"{format_duration(clamped)} remaining (until {target_hhmm})"


def format_start_line(seconds: int, target_hhmm: str) -> str:
    return (
        f"stay-awake: holding sleep inhibitor until {target_hhmm} "
        f"({format_duration(seconds)})"
    )


def format_start_line_command(command_str: str) -> str:
    return f"stay-awake: holding sleep inhibitor for: {command_str}"


def format_end_line(
    elapsed_seconds: int,
    reason: str,
    target_hhmm: str | None = None,
) -> str:
    suffix = f", target was {target_hhmm}" if target_hhmm else ""
    return (
        f"stay-awake: released after {format_duration(elapsed_seconds)} "
        f"({reason}{suffix})"
    )
