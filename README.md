# stay-awake

Tiny, tested wrapper over `systemd-inhibit` for running long jobs (overnight builds, analytics runs) without the machine suspending. Holds a `sleep` inhibitor for a duration, or runs a command under one and releases on exit.

## What it does

- Holds a logind `sleep` inhibitor (`systemd-inhibit --what=sleep`) so anything that calls `systemctl suspend` becomes a no-op while the inhibitor is held.
- Uses `os.execvp` so the Python process is replaced by `systemd-inhibit`: no orphan parent, Ctrl-C releases the inhibitor cleanly, crashes release it automatically (inhibitor lifetime = process lifetime).
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
stay-awake --help
```

Duration grammar is `<N>h`, `<N>m`, or `<N>s` — one positive integer followed by one unit. No mixed units (`1h30m`), no floats. Use seconds for fine control.

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
