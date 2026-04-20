# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`stay-awake` is a thin, tested wrapper over `systemd-inhibit` that holds a `sleep` inhibitor for a duration or for the lifetime of a wrapped command. Its purpose is to keep the machine from suspending during long-running jobs (overnight data analytics, builds, training runs).

The Python layer supervises a `systemd-inhibit` child process (via `subprocess.Popen`, not `exec`) so it can render a live countdown during duration-mode runs and print a summary line when the inhibitor is released. Supervision introduces a class of bug the earlier `exec`-based design avoided (orphaned inhibitor if Python dies unexpectedly), mitigated by a three-layer defense described under **Supervision leak defense** below.

What stay-awake adds on top of `systemd-inhibit`:

1. A duration mini-grammar (`8h`, `30m`, `5400s`) with a clean error message on bad input.
2. A `-- <cmd>` mode that wraps arbitrary user commands; the command's rc is propagated.
3. A default (`8h`) so `stay-awake` with no args does the common thing.
4. A `--list` shortcut to inspect active inhibitors.
5. A live countdown on stderr when it's a TTY (duration mode only; command mode only gets start/end lines so the child's own stdout/stderr isn't clobbered).
6. A `--quiet` flag to suppress all status output.
7. Summary on exit with an unambiguous reason: `timer elapsed`, `interrupted`, `command exited rc=<N>`, `systemd-inhibit exited rc=<N>`, or `error: <msg>`.

See `HOST_UAT.md` for the end-to-end acceptance checklist. `PLAN.md` is the original planning doc, kept as history.

## Project Structure

```
src/
  stay-awake            # Entry point (#!/usr/bin/env python3) — thin, dispatches to cli.main
  cli.py                # arg parsing, dispatch, supervision loop (spawner/clock/sleeper injected)
  duration.py           # parse("8h") -> 28800; pure
  inhibit.py            # build_argv(seconds=..., why=...) -> list[str]; pure
  progress.py           # format_remaining / format_start_line / format_end_line / pick_update_interval; pure
tests/
  conftest.py           # adds src/ to sys.path
  test_duration.py      # parser: valid/invalid inputs, whitespace, grammar edges
  test_inhibit.py       # argv builder: shape, exclusivity, tail contents
  test_progress.py      # pure-formatter tests
  test_cli.py           # dispatch + supervision via injected spawner/clock/sleeper/signal_hook
```

## Running Tests

```bash
pytest tests/ -q              # Fast summary — the normal dev loop
pytest tests/ -v              # Verbose per-test output
pytest tests/ -v -x           # Stop on first failure
pytest tests/test_cli.py -v   # Single file
pytest tests/ -k duration     # Name-pattern filter
```

Tests are hardware-free and do not actually spawn `systemd-inhibit`. `cli.main()` takes a `spawner` callable (default `subprocess.Popen`-based), plus injected `clock` / `sleeper` / `now_fn` / `out` / `is_tty` / `signal_hook`; tests pass `_FakeSpawner` + `_FakeProcess` + `_FakeClock` from `tests/test_cli.py` so the supervision loop is fully deterministic.

## Development Methodology: TDD Red/Green

**All new functionality MUST follow Test-Driven Development:**

1. **RED**: Write a failing test first, run `pytest tests/ -v -x` to prove it fails.
2. **GREEN**: Write minimal code to pass, run to prove it passes.
3. **REFACTOR**: Clean up while keeping tests green.
4. **REPEAT**: Build functionality incrementally with test coverage.

### Key Principles

- Never skip the RED step — running before implementation proves the test can fail.
- Small increments — each test covers one small behavior.
- Pure functions first — `duration.parse()`, `inhibit.build_argv()`, and everything in `progress.py` are pure (no I/O, no clock) and trivially testable.
- Dependency injection at the edges — `cli.main(argv, *, spawner=..., clock=..., sleeper=..., now_fn=..., out=..., is_tty=..., signal_hook=...)` lets tests drive the supervision loop deterministically.
- Test the argv and the supervision behavior, not the subprocess — we verify what stay-awake would run, how it renders output, how it handles `KeyboardInterrupt`/`FileNotFoundError`/non-zero child rc, but not that `systemd-inhibit` actually inhibits.

### Testing gap: the logind inhibitor and the supervision leak defense are not unit-tested

The Python code path verifies what stay-awake *would* do: the argv it would spawn, the lines it would print, the exit code it would return, the signal hooks it would install. It does **not** verify:

- Whether `systemd-inhibit --what=sleep` actually prevents suspend.
- Whether `systemctl suspend` becomes a no-op while the inhibitor is held.
- Whether `Ctrl-C` at a real terminal actually releases the inhibitor.
- Whether `PR_SET_PDEATHSIG` fires when Python is SIGKILL'd.

These end-to-end concerns are covered by `HOST_UAT.md`. Do not add "integration" tests that spawn real inhibitors under pytest — keep that in the UAT.

## Architecture

### CLI dispatch (`cli.py`)

`main()` validates args, resolves the mode, builds the argv, then hands off to `_run_duration()` or `_run_command()` which supervise a `systemd-inhibit` child.

Modes:

- **Duration mode** (`stay-awake 8h` or `stay-awake` with no args): parse duration, spawn `systemd-inhibit ... sleep <N>`, loop polling the child and rendering a countdown (stderr-TTY only), print summary on exit.
- **Command mode** (`stay-awake -- <cmd> args...`): spawn `systemd-inhibit ... <cmd> args...`, wait for the child, print summary. No countdown — there is no meaningful target.
- **List mode** (`stay-awake --list`): spawn `systemd-inhibit --list`, wait for its exit code.

Usage errors (bad duration, unknown flag, `--` with no command, duration + `--` together) print to stderr and return exit code 2. `--help`/`-h` prints usage and returns 0.

### Supervision loop (`_run_duration`)

1. Compute `target_hhmm` from `now_fn()` + duration; print the start line (unless `--quiet`).
2. Spawn the child via `spawner(argv)`. Catch `FileNotFoundError` → clear stderr message + rc=127.
3. Install signal handlers for SIGTERM/SIGHUP that forward the signal to the child.
4. Record `start_t = clock()`, `deadline = start_t + seconds`.
5. Poll once before the first sleep (catches immediate child crash).
6. Loop: compute `remaining = max(0, int(deadline - clock()))`; render `\r{format_remaining(remaining, target_hhmm)}` if TTY and not quiet; sleep `pick_update_interval(remaining)` seconds; poll again.
7. On `KeyboardInterrupt`: set `reason = "interrupted"`, fall into `finally`.
8. `finally`: clear the countdown line (`\r\033[2K`); `_ensure_dead(proc)` if needed (terminate → wait(2) → kill → wait(2) → -9); compute `elapsed`; pick `reason` = `"timer elapsed"` if `rc == 0` else `"systemd-inhibit exited rc={rc}"`; print end line.
9. Return `130` if interrupted, else `rc`.

`_run_command` is the same shape minus the countdown. Its `reason` is `"command exited rc={rc}"`.

All times are `int` seconds. `clock` uses `time.monotonic()` by default to be immune to wall-clock jumps (NTP, suspend/resume). `now_fn` is `datetime.now` by default and is only used to compute the user-visible `HH:MM` target string.

### Supervision leak defense (three layers — all required)

When Python was `exec`ing into `systemd-inhibit` (the earlier design), the inhibitor lifetime was the Python process lifetime, so any way Python died also killed the inhibitor. With supervision, Python is the *parent* of `systemd-inhibit`, and a Python crash/SIGKILL would reparent the child to `init` with the inhibit fd still held. The three layers:

1. **`PR_SET_PDEATHSIG(SIGTERM)` in `_preexec`.** Kernel-enforced: if the parent dies for *any* reason (including SIGKILL/segfault/OOM), the child immediately gets SIGTERM. This is the only defense that survives an unclean Python death. Linux-only (we are Linux-only). There is a microsecond race between `fork()` and `prctl()` where a parent death leaks — acceptable.
2. **`os.setpgrp()` in `_preexec`.** Puts the child in its own process group, insulating it from terminal signals and allowing pgroup-wide kills if we ever need them. Also makes `signal.signal(SIGINT, SIG_DFL)` meaningful by removing the child from Python's signal inheritance.
3. **`try/finally` calling `_ensure_dead(proc)`.** Covers the orderly-Python-exit path (uncaught exceptions, normal returns): terminate → wait 2s → kill → wait 2s.

Never remove any of the three. Each covers a different failure mode the others don't.

### Why not stay with `os.execvp`?

The earlier exec-based design was simpler and had no supervision-leak risk, but it provided **zero feedback** during the run: no countdown, no summary, no failure visibility. That defeats the tool's purpose — overnight-job users need to know the inhibitor was actually held for the full duration, and which reason it ended on. Supervision lets us print that information. The leak risk is mitigated by PR_SET_PDEATHSIG; the remaining microsecond race window is acceptable.

### Duration parser (`duration.py`)

Single regex: `^([1-9][0-9]*)([hms])$` applied to stripped input. Raises `InvalidDuration` (a `ValueError` subclass) on anything that doesn't match. No mixed units, no floats, no uppercase. Whitespace at the ends is tolerated; everywhere else it fails.

### Inhibit argv builder (`inhibit.py`)

Pure function `build_argv(*, why, seconds=None, command=None)` that returns a `list[str]` suitable for `subprocess.Popen`. Exactly one of `seconds` or `command` must be provided. The `--who=stay-awake` tag is hard-coded — it's the handle users look for in `systemd-inhibit --list`.

### Progress formatters (`progress.py`)

Pure, no I/O, no clock access:

- `format_duration(seconds)` — `"8h 0m"` / `"30m 0s"` / `"45s"` (2 units above 60s, 1 below).
- `format_remaining(seconds_left, target_hhmm)` — the countdown line.
- `format_start_line(seconds, target_hhmm)` / `format_start_line_command(cmd_str)` — the opening line per mode.
- `format_end_line(elapsed, reason, target_hhmm=None)` — the summary line.
- `pick_update_interval(seconds_left)` — adaptive cadence: 1s below 1m, 10s below 1h, 60s above. Caps per-second chatter on overnight runs.

The caller (cli.py) passes `target_hhmm` as a pre-formatted string so this module has no clock dependency.

### Why the duration grammar is intentionally narrow

`<N>h|m|s` covers ~100% of overnight-job usage. Mixed units (`1h30m`) and absolute times (`--until 06:00`) are Phase 2 work — do not add them without extending `duration.py` behind a `parse()` API that keeps the error messages specific.

## Do Not Do (Safety Rules)

1. **Never remove any of the three supervision-leak-defense layers** — `PR_SET_PDEATHSIG` + `os.setpgrp()` in `_preexec`, and `_ensure_dead(proc)` in the `finally`. Each covers a different failure mode. The earlier "never use subprocess.run" rule was correct for the exec-based design but has been replaced: supervision is required for the countdown/summary feature, and the three-layer defense is what makes supervision safe for overnight runs.
2. **Never add `--what=idle`** on the overnight-job path. On hosts where idle is driven by X11 (not logind), `--what=idle` is a no-op *and* a lie — the screen still locks and DPMS still kicks in. If the screen needs to stay on, that is a separate Phase 2 feature (`--no-lock` that stops the idle-driver temporarily) with its own UAT.
3. **Never silently drop bad input** — an invalid duration must exit non-zero with a human-readable message. An overnight job that silently falls back to a default is exactly the failure mode this tool exists to prevent.
4. **Never write the countdown to stdout** — stdout stays clean for pipelines. All status output (start line, countdown, end line, errors) goes to stderr. The wrapped command's stdout in command mode is untouched.
5. **Never render the countdown in command mode** — the child's stdout/stderr would race with our `\r` writes. Command mode gets only the start and end lines.

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
