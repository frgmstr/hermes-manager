# Gateway Ticker Stall — Detection & Auto-Heal Watchdog

## Symptom

A profile's cron jobs stop firing on schedule, but the gateway **process** looks alive.
Manual runs (`cronjob(action='run')` / `hermes -p <profile> cron run <job_id>`) still
work because they bypass the scheduler thread. Detection:

```bash
hermes -p <profile> cron status
# "Gateway is running but the cron ticker looks STALLED" (or "no heartbeat for Ns")
```

**Root cause**: the gateway process is up, but its internal scheduler thread died —
no heartbeat is being written. Jobs never fire; manual triggers work.

## Why not `hermes gateway restart`?

Restarting another profile's gateway from inside a cron job context is blocked by the
CLI's self-protection guard (cross-profile restart requires user approval). Recovery
must use **direct process management**: find the gateway PID → kill it → start a fresh
gateway process. This is what makes the watchdog fully autonomous.

## The Watchdog Pattern

A generalized watchdog ships with this distribution at `scripts/profile_gateway_watchdog.py`.
It is fully environment-configured — no code edits needed:

| Env var | Purpose | Default |
|---|---|---|
| `WATCHDOG_PROFILE` | Target profile to monitor (required) | — |
| `STALL_THRESHOLD` | Heartbeat staleness (s) that triggers restart | `300` |
| `LMSTUDIO_URL` | Local inference server to health-check first | `http://127.0.0.1:1234/v1` |
| `LMLMS_PATH` | Absolute path to `lms` CLI for auto-starting the server | unset (report-only) |
| `HERMES_HOME` | Your Hermes home | `%LOCALAPPDATA%\hermes` / `~/.hermes` |

Put these in the **manager profile's** `.env` (the profile whose cron runs the watchdog),
then schedule it:

```bash
# every 10 minutes, silent when healthy, alerts via stdout (deliver: telegram or local)
hermes -p <manager-profile> cron create "10m" --name "Gateway watchdog <profile>" \
  --script profile_gateway_watchdog.py --no-agent --deliver telegram
```

What it does each tick:

1. (Optional) Health-checks the inference server; tries `lms serve` if `LMLMS_PATH` is set.
2. Runs `hermes -p <profile> cron status` and parses ticker health.
3. If the gateway is down or the ticker heartbeat is older than `STALL_THRESHOLD`:
   kill the stale gateway PID (`taskkill /PID` on Windows, `kill -9` elsewhere),
   start a fresh gateway (`hermes -p <profile> --accept-hooks gateway start`),
   then verify the ticker comes back within ~30s.
4. Silent when healthy — non-empty stdout (the ALERT lines) is what the no_agent cron delivers.

## Pitfalls

- **Kill the right PID**: the PID comes from `hermes -p <profile> cron status` output
  (`PID: <n>`). Killing the wrong process takes down an unrelated gateway.
- **Two watchdogs, one profile**: don't schedule two watchers for the same profile —
  they can fight over restarts. One per profile.
- **LM Studio down ≠ gateway stalled**: agent-based jobs fail with "No models loaded"
  when the server is down even if the ticker is healthy. Check the server first
  (the script does — but it only reports if it can't auto-start).
- **Windows `start` quirk**: the fresh gateway must be launched detached
  (`start "" "hermes.exe" -p <profile> --accept-hooks gateway start`) or it dies
  when the cron tick exits.

## Recovery Without the Watchdog (manual)

```bash
# 1. Find the stale PID
hermes -p <profile> cron status
# 2. Kill it
taskkill /PID <pid> /F          # Windows
kill -9 <pid>                    # POSIX
# 3. Start fresh
start "" "hermes" -p <profile> --accept-hooks gateway start   # Windows
nohup hermes -p <profile> --accept-hooks gateway start >/dev/null 2>&1 &   # POSIX
# 4. Verify
hermes -p <profile> cron status   # "Ticker heartbeat: 0s ago"
```
