# stay-awake

Tiny, tested wrapper over `systemd-inhibit` for running long jobs (overnight builds, analytics runs) without the machine suspending. Holds a `sleep` inhibitor for a duration, or runs a command under one and releases on exit.

## What it does

- Holds a logind `sleep` inhibitor (`systemd-inhibit --what=sleep`) so anything that calls `systemctl suspend` becomes a no-op while the inhibitor is held.
- Supervises `systemd-inhibit` as a child process so it can render a live countdown on stderr (duration mode, TTY only) and print a summary line when the inhibitor is released (`timer elapsed`, `interrupted`, `command exited rc=N`, etc.) — the feedback you want when the tool is running overnight.
- Three-layer leak defense (`PR_SET_PDEATHSIG`, own process group, `try/finally` cleanup) so the inhibitor is released even if Python is SIGKILL'd or crashes — the inhibitor's lifetime still tracks the visible process lifetime.
- Does **not** touch screen lock, DPMS, or idle timers — if you use `xidlehook` or the desktop's idle-lock, the screen may still lock after its normal idle period. CPU/disk work keeps running regardless.

## Requirements

- Linux with systemd + logind (anything Ubuntu/Fedora/Arch-ish in the last decade)
- `systemd-inhibit` (from systemd; already installed on any systemd system)
- Python 3.10+ (stdlib only — no pip, no venv)

## Install

```bash
./install.sh
```

Symlinks `src/stay-awake` to `~/.local/bin/stay-awake`. `./uninstall.sh` reverses it.

## CLI

```bash
stay-awake                     # default: hold inhibitor for 8h
stay-awake 30m                 # hold inhibitor for 30 minutes
stay-awake 5400s               # hold inhibitor for 5400 seconds
stay-awake -- make train       # run the command under the inhibitor; release on exit
stay-awake --list              # show active systemd inhibitors (wraps `systemd-inhibit --list`)
stay-awake --quiet 8h          # suppress countdown and summary; still supervise
stay-awake --help
```

Duration grammar is `<N>h`, `<N>m`, or `<N>s` — one positive integer followed by one unit. No mixed units (`1h30m`), no floats. Use seconds for fine control.

## Console output

Duration mode prints to stderr (stdout stays clean for pipelines):

```
stay-awake: holding sleep inhibitor until 05:30 (8h 0m)
7h 42m remaining (until 05:30)        # live countdown, TTY only
stay-awake: released after 8h 0m (timer elapsed, target was 05:30)
```

Countdown cadence is adaptive — once per minute when >1h remaining, once per 10s between 1m–1h, once per second under 1m — so overnight runs don't spam the terminal. When stderr isn't a TTY, only the start and end lines are printed.

Command mode gets start and end lines only (no countdown — the wrapped command's output would collide with `\r` rewrites):

```
stay-awake: holding sleep inhibitor for: make train
... child stdout/stderr pass through untouched ...
stay-awake: released after 47m 12s (command exited rc=0)
```

Exit codes:

| Case                                    | Exit code         |
|-----------------------------------------|-------------------|
| Duration elapsed normally               | `0`               |
| Command mode                            | wrapped command's rc |
| `Ctrl-C` / `KeyboardInterrupt`          | `130`             |
| `systemd-inhibit` not on `PATH`         | `127`             |
| Invalid duration / unknown flag         | `2`               |
| `systemd-inhibit` itself died abnormally | its rc            |

## Examples

Hold the machine awake overnight while an analytics job runs in another terminal:

```bash
stay-awake 10h
```

Run a command under the inhibitor and let it release automatically on exit:

```bash
stay-awake -- bash -c 'make dataset && python3 train.py'
```

Check what's currently inhibiting sleep:

```bash
stay-awake --list
```

## Development

```bash
pytest tests/ -q              # all tests, quiet
pytest tests/ -v -x           # verbose, stop on first failure
```

Pure-function modules (`duration.py`, `inhibit.py`) are unit-tested directly. `cli.py` takes an `executor` callable (default `os.execvp`) so tests assert the argv that would be exec'd without actually exec'ing.

The real logind inhibitor behavior is **not** unit-tested — the Python path stops at "we'd run this argv." End-to-end coverage lives in [HOST_UAT.md](HOST_UAT.md).

See [CLAUDE.md](CLAUDE.md) for the TDD methodology and architecture notes.

## License

Licensed under Apache 2.0. See [LICENSE](LICENSE).
