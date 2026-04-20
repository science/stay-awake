# SPDX-License-Identifier: Apache-2.0
"""Parse human duration strings (e.g. "8h", "30m", "5400s") to seconds."""

import re


_UNIT_SECONDS = {"h": 3600, "m": 60, "s": 1}
_PATTERN = re.compile(r"^([1-9][0-9]*)([hms])$")


class InvalidDuration(ValueError):
    """Raised when a duration string cannot be parsed."""


def parse(text: str) -> int:
    """Return seconds for a `\\d+[hms]` duration string.

    Grammar is intentionally tight: one positive integer followed by one of
    h/m/s. No mixed units ("1h30m"), no floats, no uppercase.
    """
    if text is None:
        raise InvalidDuration("duration is required")
    stripped = text.strip()
    m = _PATTERN.match(stripped)
    if not m:
        raise InvalidDuration(f"invalid duration: {text!r} (expected e.g. 8h, 30m, 5400s)")
    value = int(m.group(1))
    unit = m.group(2)
    return value * _UNIT_SECONDS[unit]
