"""Tests for duration.py — parse human duration strings to seconds."""

import pytest

from duration import parse, InvalidDuration


class TestParseHours:
    def test_single_hour(self):
        assert parse("1h") == 3600

    def test_eight_hours(self):
        assert parse("8h") == 28800

    def test_zero_hours_rejected(self):
        with pytest.raises(InvalidDuration):
            parse("0h")


class TestParseMinutes:
    def test_single_minute(self):
        assert parse("1m") == 60

    def test_thirty_minutes(self):
        assert parse("30m") == 1800

    def test_ninety_minutes(self):
        assert parse("90m") == 5400


class TestParseSeconds:
    def test_single_second(self):
        assert parse("1s") == 1

    def test_5400_seconds(self):
        assert parse("5400s") == 5400


class TestInvalid:
    def test_empty_string(self):
        with pytest.raises(InvalidDuration):
            parse("")

    def test_no_suffix(self):
        with pytest.raises(InvalidDuration):
            parse("30")

    def test_wrong_suffix(self):
        with pytest.raises(InvalidDuration):
            parse("30d")

    def test_negative(self):
        with pytest.raises(InvalidDuration):
            parse("-5m")

    def test_float(self):
        with pytest.raises(InvalidDuration):
            parse("1.5h")

    def test_whitespace_only(self):
        with pytest.raises(InvalidDuration):
            parse("   ")

    def test_suffix_only(self):
        with pytest.raises(InvalidDuration):
            parse("h")

    def test_mixed_not_supported_yet(self):
        # Phase 1 grammar is single-unit only; reject "1h30m" until Phase 2.
        with pytest.raises(InvalidDuration):
            parse("1h30m")

    def test_uppercase_rejected(self):
        # Keep the grammar tight; 'H' is not 'h'.
        with pytest.raises(InvalidDuration):
            parse("8H")


class TestWhitespaceTolerant:
    def test_leading_whitespace(self):
        assert parse(" 8h") == 28800

    def test_trailing_whitespace(self):
        assert parse("8h ") == 28800


class TestErrorMessages:
    def test_exception_includes_input(self):
        try:
            parse("bogus")
        except InvalidDuration as e:
            assert "bogus" in str(e)
        else:
            pytest.fail("expected InvalidDuration")
