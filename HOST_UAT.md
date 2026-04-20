# HOST_UAT.md

End-to-end acceptance checklist for `stay-awake` on a real host. The Python unit tests stop at "we would spawn this argv and print these lines"; everything below verifies the *actual* logind inhibitor behavior and the three-layer leak defense, which cannot be unit-tested from pytest without spawning long-running system processes or killing the test runner.

Run Phases 1–7 before publishing. Phase 8 is an overnight smoke test deferred until a real workload is available (typically the next time you need the feature for its intended purpose).

## Phase 1 — Unit tests pass

```bash
pytest tests/ -q
```

Expected: all 83 tests pass.

## Phase 2 — Inhibitor present; start line, countdown, end line

```bash
stay-awake 2m
```

Expected on stderr (TTY):
- Start line: `stay-awake: holding sleep inhibitor until HH:MM (2m 0s)`
- Live countdown that updates every 10s (under an hour), rewriting the same line via `\r`
- A visible `systemd-inhibit --list` row from another terminal: `Who=stay-awake`, `What=sleep`, `Why=stay-awake sleep inhibit for 2m (120s)`, `Mode=block`.
- End line after ~2 minutes: `stay-awake: released after 2m 0s (timer elapsed, target was HH:MM)`
- Exit code 0, inhibitor gone from `systemd-inhibit --list`.

## Phase 3 — Ctrl-C releases cleanly

Start a long inhibitor in a foreground shell and interrupt it after a few seconds:

```bash
stay-awake 1h
# ... press Ctrl-C after ~10s ...
echo "rc=$?"
systemd-inhibit --list | grep stay-awake   # should produce no output
```

Expected:
- Ctrl-C interrupts the countdown.
- End line: `stay-awake: released after 10s (interrupted, target was HH:MM)`
- `rc=130`.
- `systemd-inhibit --list` no longer shows the stay-awake inhibitor.
- No orphaned Python, `systemd-inhibit`, or `sleep` processes remain after ~2s (`pgrep -fa stay-awake`, `pgrep -fa 'systemd-inhibit.*stay-awake'`, `pgrep -fa 'sleep 3600'`).

## Phase 4 — Command mode: rc propagation, start/end lines, child output passes through

```bash
stay-awake -- bash -c 'echo start; sleep 10; echo done; exit 7'
echo "rc=$?"
```

Expected:
- Start line on stderr: `stay-awake: holding sleep inhibitor for: bash -c echo start; sleep 10; echo done; exit 7`
- Child stdout (`start`, `done`) passes through unmodified.
- End line on stderr: `stay-awake: released after 10s (command exited rc=7)`
- `rc=7` (wrapped command's exit code propagates).
- During the 10 seconds, `systemd-inhibit --list` shows `Who=stay-awake`, `Why=stay-awake running: ...`. After exit, no `stay-awake` row.
- No countdown frames (command mode).

## Phase 5 — Console output matrix

### 5a. `--quiet` suppresses all status output

```bash
stay-awake --quiet 5s 2>/tmp/sa.stderr
cat /tmp/sa.stderr   # expected: empty
```

Still supervises: during the 5 seconds, `systemd-inhibit --list` shows the inhibitor. Exit 0.

### 5b. Non-TTY stderr: only start and end lines

```bash
stay-awake 30s 2>/tmp/sa.stderr >/dev/null
cat /tmp/sa.stderr
```

Expected: two lines (start + end), no `\r` frames, no ANSI escapes. Use `od -c /tmp/sa.stderr | head` to confirm — no `\r` bytes.

### 5c. TTY countdown cadence

Watch an interactive run of `stay-awake 65s`. Expected cadence:
- First ~5s: countdown shows `65s remaining (until HH:MM)`, `55s remaining (until HH:MM)`… wait, cadence crosses the 1-minute boundary. From 65s down to 60s: 10s cadence → one frame. From 59s to 0: 1s cadence → ~60 frames.

(No need to test every cadence boundary. Just confirm the countdown updates visibly, rewrites the same line, and doesn't spew new lines.)

### 5d. Command mode with TTY: no countdown

```bash
stay-awake -- bash -c 'echo a; sleep 3; echo b'
```

Expected: no `\r` frames in stderr; start line, child output, end line only.

## Phase 6 — Failure surfaces

### 6a. Invalid duration

```bash
stay-awake bogus; echo "rc=$?"
```

Expected: `stay-awake: invalid duration: 'bogus' (expected e.g. 8h, 30m, 5400s)` to stderr, `rc=2`.

### 6b. systemd-inhibit not on PATH

```bash
env -i PATH=/tmp HOME="$HOME" /home/steve/.local/bin/stay-awake 1m; echo "rc=$?"
```

Expected: `stay-awake: systemd-inhibit not found on PATH` on stderr, `rc=127`, end line with `error: systemd-inhibit not found`.

### 6c. SIGTERM to the parent Python

```bash
stay-awake 10m &
SA_PID=$!
sleep 2
systemd-inhibit --list | grep -c '^stay-awake'   # expect 1
kill -TERM $SA_PID
wait $SA_PID; echo "rc=$?"
sleep 1
systemd-inhibit --list | grep -c '^stay-awake'   # expect 0
pgrep -fa 'systemd-inhibit.*stay-awake' || echo "(none)"
```

Expected:
- `systemd-inhibit` child receives the forwarded SIGTERM, exits with rc=143.
- Python prints `stay-awake: released after 2s (systemd-inhibit exited rc=143, target was HH:MM)`.
- rc=143 from `wait`.
- No stay-awake inhibitor left in `--list`; no orphan processes.

## Phase 7 — Leak defense (SIGKILL)

This is the critical test that verifies `PR_SET_PDEATHSIG`. With the old exec-based design, this would not have been a concern (inhibitor lifetime = Python lifetime). With the supervision design, we *must* verify the kernel-level defense works.

```bash
stay-awake 10m &
SA_PID=$!
sleep 2
# Confirm inhibitor is held
systemd-inhibit --list | grep -c '^stay-awake'   # expect 1
# Find the systemd-inhibit child PID
CHILD_PID=$(pgrep -P $SA_PID systemd-inhibit || pgrep -f 'systemd-inhibit.*stay-awake' | head -1)
echo "parent=$SA_PID child=$CHILD_PID"
# SIGKILL the Python parent — no cleanup chance at all
kill -9 $SA_PID
# Give the kernel a moment to deliver PR_SET_PDEATHSIG=SIGTERM to the child
sleep 2
# Child must be gone; inhibitor must be released
systemd-inhibit --list | grep -c '^stay-awake'   # expect 0
pgrep -fa 'systemd-inhibit.*stay-awake' || echo "(none - pdeathsig fired)"
kill -0 $CHILD_PID 2>/dev/null && echo "FAIL: child $CHILD_PID survived" || echo "OK: child gone"
```

Expected:
- Inhibitor count returns to 0 within 2 seconds of the SIGKILL.
- No `systemd-inhibit ... stay-awake` child remains.
- If the child survived, the kernel-level defense is broken — investigate `_preexec()` in `src/cli.py`.

## Phase 8 — Overnight real-workload smoke test (deferred)

This is the *actual* reason the tool exists: run it before bed with a long workload and confirm the machine is still awake in the morning AND the summary line reports a clean `timer elapsed`.

```bash
# before bed
stay-awake 10h
# ... run your overnight job in another terminal, or use stay-awake -- <cmd> ...

# in the morning
journalctl -b -g 'Reached target.*Sleep' --no-pager   # should be empty
journalctl -b -g 'systemd-logind.*suspend' --no-pager # should show no successful suspend
```

Expected:
- Machine is awake when you sit down.
- `journalctl` shows **no** completed suspend between start and now.
- stay-awake's end line reads `stay-awake: released after 10h 0m (timer elapsed, target was HH:MM)`.
- The overnight job ran to completion without being paused by suspend.

### Optional observations during Phase 8

- After ~60 minutes of idle, the screen locks and DPMS goes to standby (driven by `~/.config/systemd/user/xidlehook.service`). This is expected — stay-awake only inhibits `--what=sleep`, not `--what=idle`. Mouse wiggle wakes the display; the analytics job is untouched.
- `systemd-inhibit --list` should still show the stay-awake inhibitor through the whole run until the requested duration elapses.

## Troubleshooting

- **`stay-awake: command not found`**: Check `~/.local/bin` is on `PATH`, or run with the full path `~/.local/bin/stay-awake`.
- **`systemd-inhibit: command not found`**: You're probably not on systemd. This tool assumes logind. stay-awake surfaces this as `stay-awake: systemd-inhibit not found on PATH` with rc=127.
- **Inhibitor held but the machine suspended anyway**: Check for other suspend triggers — lid switch handling (`/etc/systemd/logind.conf`), `rtcwake`, or a timer unit. `systemd-inhibit --what=sleep` blocks `systemctl suspend` and logind-initiated suspend; it does not override a manually issued `echo mem > /sys/power/state` or ACPI-level events that bypass logind.
- **Inhibitor leaked after SIGKILL of Python**: Phase 7 should catch this. If it leaks, `_preexec()` in `src/cli.py` is not running or the `prctl` call is failing. Inspect `journalctl --user -b | grep stay-awake` and the `libc.prctl` return value. Linux kernels 3.4+ support `PR_SET_PDEATHSIG`.
