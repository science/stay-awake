# HOST_UAT.md

End-to-end acceptance checklist for `stay-awake` on a real host. The Python unit tests stop at "we would exec this argv"; everything below verifies the *actual* logind inhibitor behavior, which cannot be unit-tested from pytest without spawning long-running system processes.

Run Phase 1–4 before publishing. Phase 5 is an overnight smoke test deferred until a real workload is available (typically the next time you need the feature for its intended purpose).

## Phase 1 — Unit tests pass

```bash
pytest tests/ -q
```

Expected: all tests pass, no errors, no warnings.

## Phase 2 — Inhibitor present while running

Hold an inhibitor for two minutes and verify it is visible to logind:

```bash
stay-awake 2m &
sleep 2
systemd-inhibit --list | grep stay-awake
```

Expected:
- A row with `Who=stay-awake`, `Why=stay-awake sleep inhibit for 2m (120s)`, `What=sleep`, `Mode=block`.
- After ~2 minutes, the inhibitor disappears automatically and the `stay-awake` process exits.

Cleanup (if needed): `kill %1`.

## Phase 3 — Ctrl-C releases cleanly

Start a long inhibitor in a foreground shell and interrupt it:

```bash
stay-awake 1h
# ... press Ctrl-C ...
systemd-inhibit --list | grep stay-awake   # should produce no output
```

Expected:
- Ctrl-C terminates the process.
- `systemd-inhibit --list` no longer shows the stay-awake inhibitor.
- No orphaned `sleep` or `systemd-inhibit` processes remain (`pgrep -fa stay-awake` / `pgrep -fa systemd-inhibit` return nothing).

## Phase 4 — Command mode runs and releases

Run a short command under the inhibitor and verify the inhibitor disappears when the command exits:

```bash
stay-awake -- bash -c 'echo start; sleep 10; echo done'
```

In another terminal during those 10 seconds:

```bash
systemd-inhibit --list | grep stay-awake
```

Expected:
- During the 10 seconds: one `stay-awake` inhibitor with `Why=stay-awake running: bash -c echo start; sleep 10; echo done` (or similar).
- After the command exits: `systemd-inhibit --list` shows no stay-awake row.
- Exit code of the `stay-awake -- ...` invocation matches the wrapped command's exit code (because we exec).

## Phase 5 — Overnight real-workload smoke test (deferred)

This is the *actual* reason the tool exists: run it before bed with a long workload and confirm the machine is still awake in the morning.

```bash
# before bed
stay-awake 10h &
# ... run your overnight job in another terminal ...

# in the morning
journalctl -b -g 'Reached target.*Sleep' --no-pager   # should be empty
journalctl -b -g 'systemd-logind.*suspend' --no-pager # should show no successful suspend
```

Expected:
- Machine is awake when you sit down.
- `journalctl` shows **no** completed suspend between when you ran `stay-awake` and now. (If xidlehook's 60-min lock fired, that is fine and expected — the screen lock and DPMS standby are separate from logind suspend.)
- The overnight job ran to completion (or whatever state it was in at wake time) without being paused by suspend.

### Optional observations during Phase 5

- After ~60 minutes of idle, the screen locks and DPMS goes to standby (driven by `~/.config/systemd/user/xidlehook.service`). This is expected — stay-awake only inhibits `--what=sleep`, not `--what=idle`. Mouse wiggle wakes the display; the analytics job is untouched.
- `journalctl --user -u xidlehook.service -b` should show the 60-min lock trigger firing around the expected time.
- `systemd-inhibit --list` should still show the stay-awake inhibitor through the whole run until the requested duration elapses.

## Troubleshooting

- **`stay-awake: command not found`**: Check `~/.local/bin` is on `PATH`, or run with the full path `~/.local/bin/stay-awake`.
- **`systemd-inhibit: command not found`**: You're probably not on systemd. This tool assumes logind.
- **Inhibitor held but the machine suspended anyway**: Check for other suspend triggers — lid switch handling (`/etc/systemd/logind.conf`), `rtcwake`, or a timer unit. `systemd-inhibit --what=sleep` blocks `systemctl suspend` and logind-initiated suspend; it does not override a manually issued `echo mem > /sys/power/state` or ACPI-level events that bypass logind.
- **Ctrl-C doesn't release**: Confirm you're running the installed symlink (not an old copy) and that the process really did exit (`pgrep -fa stay-awake`). If the process is gone but the inhibitor remains, that's a logind bug — file it upstream.
