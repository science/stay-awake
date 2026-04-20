"""Tests for inhibit.py — pure systemd-inhibit argv builder."""

import pytest

from inhibit import build_argv


class TestDurationMode:
    """Duration mode wraps `sleep N` under systemd-inhibit."""

    def test_basic_shape(self):
        argv = build_argv(seconds=60, why="overnight analytics")
        assert argv[0] == "systemd-inhibit"

    def test_what_is_sleep(self):
        argv = build_argv(seconds=60, why="overnight")
        assert "--what=sleep" in argv

    def test_who_is_stay_awake(self):
        argv = build_argv(seconds=60, why="x")
        assert "--who=stay-awake" in argv

    def test_why_is_passed_through(self):
        argv = build_argv(seconds=60, why="running ETL")
        assert "--why=running ETL" in argv

    def test_tail_is_sleep_seconds(self):
        argv = build_argv(seconds=3600, why="x")
        # Last two argv entries are the command under the inhibitor.
        assert argv[-2] == "sleep"
        assert argv[-1] == "3600"

    def test_zero_or_negative_seconds_rejected(self):
        with pytest.raises(ValueError):
            build_argv(seconds=0, why="x")
        with pytest.raises(ValueError):
            build_argv(seconds=-1, why="x")

    def test_why_must_be_non_empty(self):
        with pytest.raises(ValueError):
            build_argv(seconds=60, why="")


class TestCommandMode:
    """Command mode wraps an arbitrary user command under systemd-inhibit."""

    def test_basic_shape(self):
        argv = build_argv(command=["bash", "-c", "echo hi"], why="x")
        assert argv[0] == "systemd-inhibit"
        assert "--what=sleep" in argv
        assert "--who=stay-awake" in argv

    def test_why_is_passed_through(self):
        argv = build_argv(command=["make", "train"], why="GPU training")
        assert "--why=GPU training" in argv

    def test_tail_is_user_command_verbatim(self):
        cmd = ["python3", "script.py", "--flag", "value"]
        argv = build_argv(command=cmd, why="x")
        assert argv[-len(cmd):] == cmd

    def test_empty_command_rejected(self):
        with pytest.raises(ValueError):
            build_argv(command=[], why="x")

    def test_command_with_special_chars_passed_through(self):
        # No shell; args are literal. Quotes/spaces should not be escaped.
        argv = build_argv(command=["echo", "hello world"], why="x")
        assert argv[-1] == "hello world"


class TestExclusivity:
    """Exactly one of seconds / command must be given."""

    def test_both_modes_rejected(self):
        with pytest.raises(ValueError):
            build_argv(seconds=60, command=["true"], why="x")

    def test_neither_mode_rejected(self):
        with pytest.raises(ValueError):
            build_argv(why="x")


class TestArgvIsList:
    """Return value must be a plain list suitable for os.execvp."""

    def test_return_type(self):
        argv = build_argv(seconds=60, why="x")
        assert isinstance(argv, list)
        for item in argv:
            assert isinstance(item, str)
