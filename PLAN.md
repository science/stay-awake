# Plan: `stay-awake` — small dev project at `~/dev/stay-awake`

## Context

User needs to run a long overnight data-analytics job without the machine suspending, and wants a reusable tool rather than ad-hoc sleep-setting mutation. Scope upgraded from "shell script in yadm" to a small Python project mirroring `~/dev/brightness-ctl` layout (TDD, install.sh, HOST_UAT.md, Apache 2.0 license, GitHub repo), because the failure mode matters (silent inhibit failure = lost overnight work) and the tool will likely grow (absolute-time `--until`, optional xidlehook interaction).

### How sleep actually works on linux-bambam (confirmed during exploration)

- **`~/.config/systemd/user/xidlehook.service`** is the only sleep driver:
  - 3600s idle → `~/bin/lock-screen` (Cinnamon lock + `xset dpms force standby`)
  - 7200s idle → `systemctl suspend`
- `~/.config/yadm/dconf/cinnamon-linux-bambam.dconf` and `~/.config/yadm/hardware/disable-csd-power/` disable `csd-power` so xidlehook is the single source of truth.
- `~/dev/brightness-ctl/` is **unrelated** to sleep — it only watches the screensaver D-Bus signal to toggle DPMS.

### Why `systemd-inhibit` is compatible with this setup

xidlehook just `exec`s `systemctl suspend`; logind honors `--what=sleep` inhibitors before actually suspending, so a held inhibitor makes the 7200s timer firing a no-op. Crash-safe: inhibitor is tied to the process lifetime — no saved state to restore.

Caveat, intentionally accepted: xidlehook uses X11 idle (not logind idle), so `--what=idle` does **not** stop the 60-min lock. For overnight batch jobs the lock+DPMS standby is fine; CPU/disk work keeps running. A future `--no-lock` flag (Phase 2) can temporarily stop xidlehook for cases where the screen must stay on.

## Project layout (mirrors brightness-ctl)

```
~/dev/stay-awake/
├── LICENSE                    # Apache 2.0 (full text)
├── README.md                  # What/Requirements/Install/CLI/Configuration/Development
├── CLAUDE.md                  # TDD methodology + architecture notes (copied pattern from brightness-ctl)
├── HOST_UAT.md                # Host-level UAT checklist (inhibitor verification, real overnight run)
├── PLAN.md                    # This plan, trimmed to implementation notes
├── install.sh                 # Symlink ~/.local/bin/stay-awake → src/stay-awake
├── uninstall.sh               # Remove the symlink
├── .gitignore                 # __pycache__/, *.pyc, .pytest_cache/, .venv/
├── pytest.ini                 # [pytest] asyncio_mode = auto (kept for consistency; likely unused here)
├── src/
│   ├── stay-awake             # Python entry script (thin; dispatches to cli.main)
│   ├── cli.py                 # argparse, dispatch, subprocess exec
│   ├── duration.py            # parse "8h", "30m", "90m"; future: "06:00" absolute
│   └── inhibit.py             # build systemd-inhibit argv (pure function)
└── tests/
    ├── conftest.py            # shared fixtures
    ├── test_cli.py            # arg parsing, usage, -- delimiter, default duration
    ├── test_duration.py       # parser: "8h"→28800s, invalid→raise, edge cases
    └── test_inhibit.py        # argv builder: produces correct systemd-inhibit command line
```

**Language choice — Python (not shell):** brightness-ctl's TDD/pytest workflow ports cleanly; testing argparse + duration parsing + argv construction as pure functions is trivial in Python and painful in shell. The CLI itself stays small (~150 lines total across modules).

## CLI design

```
stay-awake <duration>           hold sleep inhibitor for <duration>
stay-awake -- <command> [args]  run <command> under inhibitor, release on exit
stay-awake                      default: 8h
stay-awake --list               show active stay-awake inhibitors (wraps `systemd-inhibit --list`)
stay-awake --help
```

Duration grammar (Phase 1): `\d+[hms]` (e.g. `8h`, `30m`, `5400s`). Phase 2 may add `--until HH:MM`.

Core path: `exec systemd-inhibit --what=sleep --who=stay-awake --why="$why" <tail>` where `<tail>` is either `sleep <dur>` or the user's command. `exec` (os.execvp) means the Python process is replaced — no orphaned parent, Ctrl-C releases the inhibitor cleanly.

## TDD methodology (copied from brightness-ctl `CLAUDE.md`)

Carry over verbatim into `~/dev/stay-awake/CLAUDE.md`:

- **RED/GREEN/REFACTOR** — write a failing test, prove it fails, write minimal code, prove it passes, refactor.
- One behavior per test; small increments.
- **Pure functions first**: `duration.parse()` and `inhibit.build_argv()` are pure → unit-tested directly.
- **Dependency injection at edges**: `cli.main()` takes an `executor` callable (default `os.execvp`) so tests can assert the argv it would exec without actually execing.
- Run with `pytest tests/ -q`; `pytest tests/ -v -x` when debugging.
- Critical gap documented explicitly: the actual logind inhibitor behavior is **not** unit-tested — covered by `HOST_UAT.md` instead.

Dev loop: edit → `pytest` → `./install.sh` → `stay-awake 2m` in one terminal, `systemd-inhibit --list | grep stay-awake` in another.

## Install pattern (simpler than brightness-ctl — no daemon)

`install.sh`:
1. Ensure `~/.local/bin/` exists.
2. Remove any stale `~/.local/bin/stay-awake` (symlink or file).
3. Symlink `~/.local/bin/stay-awake` → `$(pwd)/src/stay-awake`.
4. Verify `systemd-inhibit --version` works (sanity check, non-fatal warn if missing).
5. Print usage hint.

`uninstall.sh`: remove the symlink only; no config/state directory to preserve.

## HOST_UAT.md outline

Short (≪ brightness-ctl's 806 lines) because there's less to verify:

1. **Unit tests pass** — `pytest tests/ -q` green.
2. **Inhibitor present while running** — `stay-awake 2m &`; `systemd-inhibit --list | grep stay-awake` shows `sleep` inhibitor with `who=stay-awake`; auto-releases after 2 min.
3. **Ctrl-C releases cleanly** — start `stay-awake 1h`, Ctrl-C, confirm inhibitor gone from `systemd-inhibit --list`.
4. **Command mode** — `stay-awake -- bash -c 'sleep 10; echo done'`; inhibitor present for 10s, released after.
5. **Overnight smoke test** — `stay-awake 10h` before bed; next morning machine is awake, `journalctl -b -g suspend` shows no suspend occurred, xidlehook logs show lock at 60min (expected).
6. **Lock behavior documented** — confirm screen locked after 60min during test; DPMS standby; mouse wiggle wakes display; analytics unaffected.

## License

- `LICENSE`: full Apache License 2.0 text (standard).
- Python source files: SPDX header only — `# SPDX-License-Identifier: Apache-2.0` on line 1. No boilerplate.
- README: "Licensed under Apache 2.0. See LICENSE."

## GitHub

- Create repo via `gh repo create science/stay-awake --public --source=. --remote=origin` after first commit (matches the `science/*` org pattern used by brightness-ctl, audio-switcher, anomalous-mon).
- Single `main` branch; no CI (matches project norms).
- First push after local tests pass and HOST_UAT Phase 1–4 clear.

## Active-projects list update

Edit `/home/steve/dev/active-projects/README.md` — add an entry under the **Linux Desktop** section (alongside PAM Fingerprint Sudo, Multi-Row Panel Launchers, etc.) using the existing format:

```markdown
### [stay-awake](https://github.com/science/stay-awake)
Temporarily inhibit system suspend for long-running overnight jobs. Thin, tested wrapper over `systemd-inhibit` with duration or command-wrapping modes. Respects the machine's xidlehook-based idle/lock config.
*Python 3, systemd-inhibit, pytest.*

---
```

## Implementation order

1. Scaffold repo (directories, `.gitignore`, `LICENSE`, empty `pytest.ini`).
2. RED/GREEN: `test_duration.py` → `duration.py`.
3. RED/GREEN: `test_inhibit.py` → `inhibit.py` (pure argv builder).
4. RED/GREEN: `test_cli.py` (using injected executor) → `cli.py` and `src/stay-awake` entry.
5. Write `install.sh` / `uninstall.sh`.
6. Write `README.md`, `CLAUDE.md`, `HOST_UAT.md`.
7. `./install.sh`, run HOST_UAT Phase 1–4.
8. `git init`, first commit, `gh repo create science/stay-awake --public --source=. --remote=origin --push`.
9. Edit `~/dev/active-projects/README.md`, commit + push there.
10. Defer HOST_UAT Phase 5 (actual overnight run) until tonight's analytics job — that *is* the real UAT.

## Files touched

- **New:** everything under `~/dev/stay-awake/` (see layout above).
- **Edited:** `/home/steve/dev/active-projects/README.md` (one entry added).
- **Not touched:** `~/.config/systemd/user/xidlehook.service`, dconf, `~/dev/brightness-ctl/`, autostart overrides, PAM, `~/bin/lock-screen`. All existing sleep/lock config stays intact.
