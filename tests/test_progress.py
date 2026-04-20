"""Tests for progress.py — pure formatting helpers for countdown + summary."""

import pytest

from progress import (
    format_duration,
    format_end_line,
    format_remaining,
    format_start_line,
    pick_update_interval,
)


class TestFormatDuration:
    """Human-readable duration: 2 units when >= 60s, 1 unit when < 60s."""

    def test_seconds_only(self):
        assert format_duration(0) == "0s"
        assert format_duration(1) == "1s"
        assert format_duration(59) == "59s"

    def test_minutes_and_seconds(self):
        assert format_duration(60) == "1m 0s"
        assert format_duration(61) == "1m 1s"
        assert format_duration(3599) == "59m 59s"

    def test_hours_and_minutes_no_seconds(self):
        assert format_duration(3600) == "1h 0m"
        assert format_duration(3660) == "1h 1m"
        assert format_duration(28800) == "8h 0m"
        assert format_duration(36000) == "10h 0m"


class TestPickUpdateInterval:
    def test_below_one_minute_is_one_second(self):
        assert pick_update_interval(1) == 1
        assert pick_update_interval(59) == 1

    def test_one_minute_to_one_hour_is_ten_seconds(self):
        assert pick_update_interval(60) == 10
        assert pick_update_interval(3599) == 10

    def test_one_hour_plus_is_one_minute(self):
        assert pick_update_interval(3600) == 60
        assert pick_update_interval(28800) == 60

    def test_zero_or_negative_is_one_second(self):
        # Shouldn't occur in practice (loop exits), but be defensive.
        assert pick_update_interval(0) == 1
        assert pick_update_interval(-5) == 1


class TestFormatRemaining:
    """Countdown line. Always includes `until HH:MM`."""

    def test_seconds_only(self):
        assert format_remaining(13, "05:30") == "13s remaining (until 05:30)"
        assert format_remaining(59, "05:30") == "59s remaining (until 05:30)"

    def test_minutes_and_seconds(self):
        assert format_remaining(60, "05:30") == "1m 0s remaining (until 05:30)"
        assert format_remaining(133, "06:15") == "2m 13s remaining (until 06:15)"

    def test_hours_and_minutes(self):
        assert format_remaining(3600, "05:30") == "1h 0m remaining (until 05:30)"
        assert format_remaining(27720, "05:30") == "7h 42m remaining (until 05:30)"

    def test_zero_or_negative_clamps_to_zero_seconds(self):
        assert format_remaining(0, "05:30") == "0s remaining (until 05:30)"
        assert format_remaining(-3, "05:30") == "0s remaining (until 05:30)"


class TestFormatStartLine:
    def test_hours(self):
        s = format_start_line(28800, "05:30")
        assert s == "stay-awake: holding sleep inhibitor until 05:30 (8h 0m)"

    def test_minutes(self):
        s = format_start_line(1800, "09:00")
        assert s == "stay-awake: holding sleep inhibitor until 09:00 (30m 0s)"

    def test_seconds(self):
        s = format_start_line(45, "12:01")
        assert s == "stay-awake: holding sleep inhibitor until 12:01 (45s)"

    def test_command_mode_variant(self):
        # Command mode has no duration known up-front; expose a separate helper.
        from progress import format_start_line_command

        s = format_start_line_command("make train")
        assert s == "stay-awake: holding sleep inhibitor for: make train"


class TestFormatEndLine:
    def test_timer_elapsed_with_target(self):
        s = format_end_line(28800, "timer elapsed", target_hhmm="05:30")
        assert s == "stay-awake: released after 8h 0m (timer elapsed, target was 05:30)"

    def test_interrupted_with_target(self):
        s = format_end_line(7980, "interrupted", target_hhmm="05:30")
        assert s == "stay-awake: released after 2h 13m (interrupted, target was 05:30)"

    def test_command_rc_no_target(self):
        s = format_end_line(47, "command exited rc=0", target_hhmm=None)
        assert s == "stay-awake: released after 47s (command exited rc=0)"

    def test_command_rc_nonzero_no_target(self):
        s = format_end_line(600, "command exited rc=7", target_hhmm=None)
        assert s == "stay-awake: released after 10m 0s (command exited rc=7)"

    def test_error_reason(self):
        s = format_end_line(0, "error: systemd-inhibit not found", target_hhmm=None)
        assert s == "stay-awake: released after 0s (error: systemd-inhibit not found)"
