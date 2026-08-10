---
name: cron-health-auditor
description: "Use when auditing Hermes cron health across profiles."
version: 1.0.0
author: Hermes Agent + KB
license: MIT
platforms: [linux, macos, windows]
tags: [hermes, cron, monitoring, audit]
---

# Cron Health Auditor

## Overview

On-demand or scheduled checks that cron is healthy across the relevant profiles. Inspects job configs, recent runs, model pins vs. `cron.model` vs. global default, delivery targets, skill bindings, failed/unknown executions, and runaway scheduling. Can itself be driven by a lightweight cron job on Default.

## When to Use

- User asks "is all my cron working?" or "check cron health"
- Scheduled audit via a self-cron on the Default profile
- Investigating recurring failures (model drift, LM Studio down, delivery errors)
- After changing models/config — verify no jobs broke from drift guard
- Cross-profile cron inventory (jobs running under `workdir` paths in other profiles)

## What to Audit

| Check | Command / Method | Failure Signal |
|---|---|---|
| **Scheduler alive?** | `hermes cron status` | "Gateway is not running" or no heartbeat |
| **Job config** | `hermes -p <profile> cron list` | Missing script, wrong schedule, `no_agent: false` but LLM down |
| **Recent runs** | `hermes -p <profile> cron history` (tail 30) | `failed`, `unknown` status entries |
| **Model pin vs drift** | Inspect each job's `--model`/`--provider` in list output | Unpinned agent jobs blocked by drift guard → "Skipped to prevent unintended spend" |
| **Delivery targets** | Check `Deliver:` field per job | `no delivery target resolved for deliver=telegram` errors |
| **Skill bindings** | Check `Skills:` field per job | Skill missing → import error on run |
| **Workdir cross-refs** | Jobs with `workdir: profiles/<other-profile>` | Model may not be loaded at that profile's LM Studio endpoint |
| **Runaway scheduling** | Verify schedules aren't overlapping or too frequent | Multiple jobs firing simultaneously, resource contention |

## Workflow

### Phase 1: Scheduler Health Check

```bash
hermes cron status
```

Look for:
- **"Gateway is running"** — if stopped, no jobs fire. Start with `hermes gateway start`.
- **Heartbeat age** — ticker heartbeat should be recent (seconds ago). Stale = scheduler stalled.
- **Active job count** vs expected. A sudden drop means a profile's cron dir may have been corrupted or the profile was deleted.

### Phase 2: Per-Profile Job Inventory

For each active profile, list and inspect jobs:

```bash
hermes -p <profile> cron list
```

Capture for each job:
1. **ID + Name** — identify it
2. **Schedule** — verify not too frequent (runaway check)
3. **`no_agent` mode** — script-only vs agent-based
4. **Model/provider pin** — `<model-id>` or `null` (unpinned)
5. **Deliver target** — `local`, `telegram`, etc.
6. **Script path** — does the file exist? (`~/.hermes/scripts/<name>` for default, `~/.hermes/profiles/<profile>/scripts/` for profile-specific)
7. **Skills bound** — are they installed in that profile?
8. **Workdir cross-ref** — jobs running under another profile's directory

### Phase 3: Recent Execution Audit

```bash
hermes -p <profile> cron history | tail -30
```

Look for three status types:

| Status | Meaning | Action |
|---|---|---|
| **`completed`** | Normal success | No action needed |
| **`failed`** | Job errored — inspect the error message below it | See Phase 4 troubleshooting |
| **`unknown`** | Scheduler restarted before a durable terminal state was reached; side effects may or may not have run | Investigate what happened mid-run; check output files manually |

### Phase 4: Failure Classification & Remediation

#### Model Not Loaded (`HTTP 400: No models loaded`)

**Symptom**: Agent-based jobs fail with `RuntimeError: HTTP 400: No models loaded. Please load a model in the developer page or use the 'lms load' command.`

**Root cause**: LM Studio doesn't have a model loaded at the profile's endpoint (`/p/<profile>/v1`). This is common when switching profiles or after LM Studio restarts.

**Fix**: Load the correct model in LM Studio for that profile's endpoint:
```bash
# Check what's available at each endpoint
curl -s http://127.0.0.1:1234/v1/models | python -m json.tool
curl -s http://127.0.0.1:1234/p/<profile>/v1/models | python -m json.tool

# Load in LM Studio (via its CLI or UI)
lms load <model-id> --endpoint /p/<profile-name>/v1
```

#### Drift Guard (`Skipped to prevent unintended spend`)

**Symptom**: `RuntimeError: Skipped to prevent unintended spend: global inference config drifted since this job was created (model 'X' -> 'Y'), and this job is unpinned.`

**Root cause**: The default/profile model changed after the cron job was created, and the job's `model` field is null (unpinned). Hermes blocks the call to prevent surprise charges.

**Fix**: Pin explicitly via CLI ONLY — the `cronjob(action='update')` tool silently fails:
```bash
hermes -p <profile> cron edit <job_id> --model <new-model> --provider custom
```

#### Delivery Target Unresolved (`no delivery target resolved for deliver=telegram`)

**Symptom**: Job runs but can't deliver results to the configured platform at fire time.

**Fix**: Change `deliver` to `"origin"` or `"local"` for self-delivery, or ensure the gateway home channel is configured:
```bash
hermes -p <profile> cron edit <job_id> --deliver origin
```

#### Agent Timeout (`idle for Ns (limit M)`)

**Symptom**: `TimeoutError: Cron job '<name>' idle for 603s (limit 600s) — last activity: waiting for non-streaming API response`

**Root cause**: The profile's `terminal.timeout` and `lifetime_seconds` settings cap how long a cron agent session can run. Complex jobs exceed this limit.

**Fix**: Increase both in `<profile>/config.yaml`:
```yaml
terminal:
  timeout: 1200      # was 600
  lifetime_seconds: 1200  # was 600
```
Then re-run the job to verify (never assume changes are live without verification).

#### Watchdog Self-Failure Loop

**Symptom**: A health-check script exits non-zero when it finds issues → cron marks it failed → next run reports itself as failed.

**Fix**: Scripts should `sys.exit(0)` even when reporting problems. Reporting is the job, not a failure. Only exit non-zero on *unrecoverable* errors (can't read config, can't connect to gateway at all).

### Phase 5: Runaway Scheduling Check

Verify no jobs are scheduled too aggressively or overlapping:
- Jobs with schedules like `"30m"` that do heavy work may pile up if a run takes longer than the interval.
- Multiple agent-based jobs firing simultaneously compete for LM Studio's single GPU context.
- Check `Next run` times in `cron list` — if multiple are imminent, consider staggering.

## Cross-Profile Cron Paths (Windows)

| Resource | Default Profile | Profile-Specific |
|---|---|---|
| Jobs config | `~/.hermes/cron/jobs.json` | `~/.hermes/profiles/<name>/cron/jobs.json` |
| Scripts dir | `~/.hermes/scripts/` | `~/.hermes/profiles/<name>/scripts/` |
| Execution DB | `~/.hermes/cron/executions.db` | `~/.hermes/profiles/<name>/cron/executions.db` |

**Important**: A job in the default profile's `jobs.json` can have a `workdir: profiles/<other-profile>` and run under that other profile's context. Always check both the jobs config location AND the workdir when troubleshooting — the model must be available at the workdir profile's LM Studio endpoint, not just the global one.

## Self-Auditing Cron Job (Optional)

This skill can drive itself via a lightweight cron job on Default:

```python
# Script: ~/.hermes/scripts/cron_health_check.py
import subprocess, json, sys
from datetime import datetime, timedelta

profiles = ["default", "<profile-a>"]
issues = []

for profile in profiles:
    # Check scheduler status
    result = subprocess.run(["hermes", "-p", profile, "cron", "status"], 
                          capture_output=True, text=True)
    if "running" not in result.stdout.lower():
        issues.append(f"{profile}: cron gateway NOT running")
    
    # Check recent failures (last 10 runs)
    history = subprocess.run(["hermes", "-p", profile, "cron", "history"],
                           capture_output=True, text=True)
    for line in history.stdout.split("\n"):
        if "failed" in line or "unknown" in line:
            issues.append(f"{profile}: {line.strip()}")

if issues:
    print("⚠️ CRON HEALTH ISSUES:")
    for issue in issues:
        print(f"  - {issue}")
else:
    print("✅ All cron jobs healthy across all profiles")
```

Schedule it: `hermes cron create "0 12 * * *" --script cron_health_check.py --no-agent --deliver telegram`

## Quick Command Reference

```bash
# Check scheduler health
hermes cron status

# List all jobs in a profile (shows model pins, modes, deliver targets)
hermes -p <profile> cron list

# Show recent execution history with error details
hermes -p <profile> cron history | tail -30

# Run a job on-demand to test it manually
hermes -p <profile> cron run <job_id>

# Pin an unpinned agent-based job (CLI ONLY — tool pinning silently fails)
hermes -p <profile> cron edit <job_id> --model <new-model> --provider custom

# Check what models are loaded at each LM Studio endpoint
curl -s http://127.0.0.1:1234/v1/models | python -m json.tool
curl -s http://127.0.0.1:1234/p/<profile>/v1/models | python -m json.tool

# Find stale cron job references after model changes
grep -rn '<old-model>' ~/.hermes/cron/ --include="*.json" --exclude-dir=.archive
```

## Verification Checklist

- [ ] Scheduler alive (`hermes cron status` shows "running" with recent heartbeat)
- [ ] All expected jobs present in `cron list` for each profile
- [ ] No `failed` or `unknown` statuses in recent `cron history` (last 10 runs per job)
- [ ] Agent-based jobs have model pins that match available LM Studio endpoints
- [ ] Delivery targets resolve correctly (`local`, `origin`, or configured gateway channel)
- [ ] Skill bindings exist in the target profile for each job using `--skills`
- [ ] Script files exist at the expected paths (check both default and profile-specific dirs)
- [ ] No runaway scheduling — jobs aren't overlapping or firing too frequently
- [ ] If self-audit cron is configured, it's delivering results on schedule