# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`stay-awake` is a thin, tested wrapper over `systemd-inhibit` that holds a `sleep` inhibitor for a duration or for the lifetime of a wrapped command. Its purpose is to keep the machine from suspending during long-running jobs (overnight data analytics, builds, training runs).

The Python layer is small by design — the interesting work is delegated to `systemd-inhibit` via `os.execvp`. What stay-awake adds on top:

1. A duration mini-grammar (`8h`, `30m`, `5400s`) with a clean error message on bad input.
2. A `-- <cmd>` mode that wraps arbitrary user commands.
3. A default (`8h`) so `stay-awake` with no args does the common thing.
4. A `--list` shortcut to inspect active inhibitors.

See `HOST_UAT.md` for the end-to-end acceptance checklist. `PLAN.md` is the original planning doc, kept as history.

## Project Structure

```
src/
  stay-awake            # Entry point (#!/usr/bin/env python3) — thin, dispatches to cli.main
  cli.py                # arg parsing, dispatch, executor injection
  duration.py           # parse("8h") -> 28800; pure
  inhibit.py            # build_argv(seconds=..., why=...) -> list[str]; pure
tests/
  conftest.py           # adds src/ to sys.path
  test_duration.py      # parser: valid/invalid inputs, whitespace, grammar edges
  test_inhibit.py       # argv builder: shape, exclusivity, tail contents
  test_cli.py           # dispatch via injected executor: default 8h, -- delimiter, --list, --help
```

## Running Tests

```bash
pytest tests/ -q              # Fast summary — the normal dev loop
pytest tests/ -v              # Verbose per-test output
pytest tests/ -v -x           # Stop on first failure
pytest tests/test_cli.py -v   # Single file
pytest tests/ -k duration     # Name-pattern filter
```

Tests are hardware-free and do not actually exec `systemd-inhibit` — the CLI takes an `executor` callable whose default is `os.execvp`; tests pass a spy that records the call and returns.

## Development Methodology: TDD Red/Green

**All new functionality MUST follow Test-Driven Development:**

1. **RED**: Write a failing test first, run `pytest tests/ -v -x` to prove it fails.
2. **GREEN**: Write minimal code to pass, run to prove it passes.
3. **REFACTOR**: Clean up while keeping tests green.
4. **REPEAT**: Build functionality incrementally with test coverage.

### Key Principles

- Never skip the RED step — running before implementation proves the test can fail.
- Small increments — each test covers one small behavior.
- Pure functions first — `duration.parse()` and `inhibit.build_argv()` are pure (no I/O), so they are trivially testable.
- Dependency injection at the edges — `cli.main(argv, *, executor=os.execvp)` lets tests assert the argv that would be exec'd without actually exec'ing.
- Test the argv, not the subprocess — we verify what stay-awake would run, not that `systemd-inhibit` actually inhibits.

### Testing gap: the logind inhibitor itself is not unit-tested

The Python code path ends at "we would exec this argv." Whether `systemd-inhibit --what=sleep` actually prevents suspend, whether Ctrl-C releases the inhibitor, and whether `systemctl suspend` becomes a no-op while the inhibitor is held are **end-to-end** concerns covered by `HOST_UAT.md`. Do not add "integration" tests that spawn real inhibitors under pytest — keep that in the UAT.

## Architecture

### CLI dispatch (`cli.py`)

`main(argv, *, executor=os.execvp)` returns an exit code on error or delegates to `executor("systemd-inhibit", [...])` on success. Three modes:

- **Duration mode** (`stay-awake 8h` or `stay-awake` with no args): parse duration, build `systemd-inhibit ... sleep <N>`, exec.
- **Command mode** (`stay-awake -- <cmd> args...`): split argv at `--`, pass the tail verbatim, exec.
- **List mode** (`stay-awake --list`): exec `systemd-inhibit --list`.

Usage errors (bad duration, unknown flag, `--` with no command, duration + `--` together) print to stderr and return exit code 2. `--help`/`-h` prints usage and returns 0.

### Duration parser (`duration.py`)

Single regex: `^([1-9][0-9]*)([hms])$` applied to stripped input. Raises `InvalidDuration` (a `ValueError` subclass) on anything that doesn't match. No mixed units, no floats, no uppercase. Whitespace at the ends is tolerated; everywhere else it fails.

### Inhibit argv builder (`inhibit.py`)

Pure function `build_argv(*, why, seconds=None, command=None)` that returns a `list[str]` suitable for `os.execvp`. Exactly one of `seconds` or `command` must be provided. The `--who=stay-awake` tag is hard-coded — it's the handle users look for in `systemd-inhibit --list`.

### Why `os.execvp` and not `subprocess.run`

Replacing the Python process means:

- No orphan parent watching a child.
- Ctrl-C is delivered directly to `systemd-inhibit`, which releases the inhibitor.
- A crash of stay-awake's parent doesn't leave a held inhibitor behind (the inhibitor's lifetime is tied to the `systemd-inhibit` process itself, not some saved state).

Changing this to `subprocess.run` would reintroduce an orphaned-child class of bug. Don't.

### Why the duration grammar is intentionally narrow

`<N>h|m|s` covers ~100% of overnight-job usage. Mixed units (`1h30m`) and absolute times (`--until 06:00`) are Phase 2 work — do not add them without extending `duration.py` behind a `parse()` API that keeps the error messages specific.

## Do Not Do (Safety Rules)

1. **Never use `subprocess.run` or `subprocess.Popen` on the success path** — the tool must `exec` so the inhibitor lifetime equals the process lifetime. Ctrl-C behavior depends on it.
2. **Never add `--what=idle`** on the overnight-job path. On hosts where idle is driven by X11 (not logind), `--what=idle` is a no-op *and* a lie — the screen still locks and DPMS still kicks in. If the screen needs to stay on, that is a separate Phase 2 feature (`--no-lock` that stops the idle-driver temporarily) with its own UAT.
3. **Never silently drop bad input** — an invalid duration must exit non-zero with a human-readable message. An overnight job that silently falls back to a default is exactly the failure mode this tool exists to prevent.

## Dependencies

### Runtime (all stdlib, no pip)
- Python 3.10+ (for `str | None` unions and `list[str]` typing)
- `systemd-inhibit` (systemd; present on any systemd distro)

### Test
- `python3-pytest` (system package)

## Install / Uninstall

```bash
./install.sh        # Symlinks src/stay-awake -> ~/.local/bin/stay-awake
./uninstall.sh      # Removes the symlink
```

No config, no state, no daemon. Uninstall is a `rm`.

## Git Workflow

- Single `main` branch for development.
- No CI — tests run locally via `pytest tests/ -v`.
- Commit test + implementation together after the GREEN step.
