"""Tests for cli.py — arg parsing, dispatch, default duration, -- delimiter."""

import pytest

from cli import main


class _FakeExecutor:
    """Spy that records execvp-style calls instead of execing."""

    def __init__(self):
        self.calls: list[tuple[str, list[str]]] = []

    def __call__(self, file: str, args: list[str]) -> None:
        self.calls.append((file, list(args)))


@pytest.fixture
def exe():
    return _FakeExecutor()


class TestDurationMode:
    def test_duration_invokes_systemd_inhibit(self, exe):
        rc = main(["8h"], executor=exe)
        assert rc == 0
        assert len(exe.calls) == 1
        file, args = exe.calls[0]
        assert file == "systemd-inhibit"
        assert args[0] == "systemd-inhibit"
        assert "--what=sleep" in args
        assert "--who=stay-awake" in args
        assert args[-2:] == ["sleep", "28800"]

    def test_minutes(self, exe):
        main(["30m"], executor=exe)
        _, args = exe.calls[0]
        assert args[-2:] == ["sleep", "1800"]

    def test_default_is_eight_hours(self, exe):
        rc = main([], executor=exe)
        assert rc == 0
        _, args = exe.calls[0]
        assert args[-2:] == ["sleep", "28800"]

    def test_invalid_duration_is_usage_error(self, exe, capsys):
        rc = main(["bogus"], executor=exe)
        assert rc == 2
        assert exe.calls == []
        err = capsys.readouterr().err
        assert "bogus" in err


class TestCommandMode:
    def test_command_after_dash_dash(self, exe):
        rc = main(["--", "bash", "-c", "echo hi"], executor=exe)
        assert rc == 0
        file, args = exe.calls[0]
        assert file == "systemd-inhibit"
        assert args[-3:] == ["bash", "-c", "echo hi"]

    def test_command_mode_has_inhibit_flags(self, exe):
        main(["--", "true"], executor=exe)
        _, args = exe.calls[0]
        assert "--what=sleep" in args
        assert "--who=stay-awake" in args

    def test_empty_command_after_dash_dash_is_usage_error(self, exe, capsys):
        rc = main(["--"], executor=exe)
        assert rc == 2
        assert exe.calls == []
        assert capsys.readouterr().err  # some message printed

    def test_command_with_flags_passed_through(self, exe):
        main(["--", "python3", "-m", "pytest", "-q"], executor=exe)
        _, args = exe.calls[0]
        assert args[-4:] == ["python3", "-m", "pytest", "-q"]


class TestListMode:
    def test_list_execs_systemd_inhibit_list(self, exe):
        rc = main(["--list"], executor=exe)
        assert rc == 0
        file, args = exe.calls[0]
        assert file == "systemd-inhibit"
        assert "--list" in args


class TestHelp:
    def test_help_prints_usage_and_returns_zero(self, exe, capsys):
        rc = main(["--help"], executor=exe)
        assert rc == 0
        assert exe.calls == []
        out = capsys.readouterr().out
        assert "stay-awake" in out.lower()
        assert "usage" in out.lower()

    def test_short_help(self, exe, capsys):
        rc = main(["-h"], executor=exe)
        assert rc == 0
        out = capsys.readouterr().out
        assert "usage" in out.lower()


class TestUnknownFlags:
    def test_unknown_flag_is_usage_error(self, exe, capsys):
        rc = main(["--unknown"], executor=exe)
        assert rc == 2
        assert exe.calls == []


class TestWhy:
    def test_why_mentions_stay_awake_and_duration(self, exe):
        main(["2h"], executor=exe)
        _, args = exe.calls[0]
        why_arg = next(a for a in args if a.startswith("--why="))
        # Human-readable; include something identifying.
        assert "2h" in why_arg or "7200" in why_arg

    def test_why_mentions_command_in_command_mode(self, exe):
        main(["--", "make", "train"], executor=exe)
        _, args = exe.calls[0]
        why_arg = next(a for a in args if a.startswith("--why="))
        assert "make" in why_arg


class TestDurationBeforeDashDash:
    """`stay-awake 8h -- cmd` is ambiguous; reject as usage error."""

    def test_duration_and_command_together_rejected(self, exe, capsys):
        rc = main(["8h", "--", "true"], executor=exe)
        assert rc == 2
        assert exe.calls == []
