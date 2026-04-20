# SPDX-License-Identifier: Apache-2.0
"""Build the systemd-inhibit argv for stay-awake.

Kept pure (no subprocess, no os.execvp) so tests can assert the exact argv
that would be executed without actually execing it.
"""


def build_argv(
    *,
    why: str,
    seconds: int | None = None,
    command: list[str] | None = None,
) -> list[str]:
    """Return the argv for `systemd-inhibit ... <tail>`.

    Exactly one of `seconds` or `command` must be given. With `seconds`, the
    tail is `sleep N`. With `command`, the tail is the user's command verbatim.
    """
    if not why:
        raise ValueError("why must be a non-empty string")
    if (seconds is None) == (command is None):
        raise ValueError("pass exactly one of seconds= or command=")

    argv = [
        "systemd-inhibit",
        "--what=sleep",
        "--who=stay-awake",
        f"--why={why}",
    ]

    if seconds is not None:
        if seconds <= 0:
            raise ValueError(f"seconds must be positive, got {seconds}")
        argv += ["sleep", str(seconds)]
    else:
        if not command:
            raise ValueError("command must be a non-empty list")
        argv += list(command)

    return argv
