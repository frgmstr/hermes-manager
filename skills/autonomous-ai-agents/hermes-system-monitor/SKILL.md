---
name: hermes-system-monitor
description: "Use when running Hermes system health checks."
version: 1.0.0
author: Hermes Agent + KB
license: MIT
platforms: [linux, macos, windows]
tags: [hermes, monitoring, diagnostics, doctor]
---

# Hermes System Monitor

## Overview

Wrapper around `hermes doctor` and runtime extensions for system health. Checks gateway status, process liveness, `state.db` / `gateway_state.json`, disk space, and verification steps from SOUL.md's Verification Discipline. Includes common remediation playbooks and a "report only vs. auto-heal" mode toggle.

## When to Use

- User asks "is Hermes healthy?" or "run hermes doctor"
- Scheduled health checks via cron on Default profile
- Before/after config/model changes — verify the system is stable
- Investigating gateway stalls, missing tools, or process crashes
- Disk space concerns (state.db grows large over time)

## What to Check

| Component | Command / Method | Failure Signal |
|---|---|---|
| **Config integrity** | `hermes doctor` | Deprecated keys, config version mismatch, .env missing |
| **Security advisories** | `hermes doctor` (security section) | Active advisories with IDs to ack |
| **Python environment** | `hermes doctor` | Missing packages, venv issues, SQLite problems |
| **API keys / auth** | `hermes status --all` | Required providers not logged in |
| **Credential liveness** | `scripts/credential_audit.py` | X API 401/403, Telegram 404 (dead bot token), LM Studio unreachable, GitHub 401 |
| **Gateway service** | `hermes gateway status` or process check | Not running, stale PID, no heartbeat |
| **Cron scheduler** | `hermes cron status` | Gateway stopped = no jobs fire |
| **state.db health** | File size + SQLite integrity | >10GB, corrupt tables, FTS5 index broken |
| **gateway_state.json** | File exists + valid JSON | Missing or malformed → gateway can't route |
| **Disk space** | `df` / filesystem check | Low disk causes state.db write failures |

## Workflow

### Phase 1: Diagnostic Sweep (Report Only Mode)

Default mode — collect all signals, report findings, do NOT change anything.

```bash
# Full diagnostic
hermes doctor

# Extended status with API keys redacted
hermes status --all

# Deep checks (slower but thorough)
hermes status --deep
```

Capture and organize output into categories: ✅ healthy / ⚠️ warning / ❌ failed.

### Phase 2: Process Liveness Check

Verify the gateway and cron scheduler are actually running:

```bash
# Gateway process check (Windows — use tasklist equivalent)
ps aux | grep -i hermes_gateway | grep -v grep

# On Windows, the gateway runs as Hermes_Gateway.cmd / pythonw
tasklist | grep -i "Hermes_Gateway"  # via git-bash ps
```

**What to look for:**
- PID matches what `hermes status` reports (e.g., PID 22700)
- Process is not a zombie/stale entry
- Gateway heartbeat in cron status is recent (< 60s old)

### Phase 3: State File Health

#### state.db (~85MB on this system — monitor growth)

```bash
# Check file size (warn if >1GB)
ls -lh ~/.hermes/state.db

# SQLite integrity check
python -c "
import sqlite3
conn = sqlite3.connect('~/.hermes/state.db')
result = conn.execute('PRAGMA integrity_check').fetchall()
print(result)
conn.close()
"

# Check FTS5 virtual table health (session search relies on it)
python -c "
import sqlite3
conn = sqlite3.connect('~/.hermes/state.db')
tables = conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()
print([t[0] for t in tables])
# Look for: sessions, messages_fts (FTS5), messages
"
```

**Warning signs:**
- `integrity_check` returns anything other than `[('ok',)]`
- FTS5 tables missing → session search broken
- File size > 1GB — prune old sessions with `hermes sessions prune`

#### gateway_state.json (~446 bytes on this system)

```bash
# Verify it's valid JSON and has expected keys
python -c "
import json
with open('~/.hermes/gateway_state.json') as f:
    state = json.load(f)
print(json.dumps(state, indent=2))
"
```

**Expected structure**: routing index, request dumps config, platform connection states. If missing or malformed → gateway can't route messages.

### Phase 4: Credential & Endpoint Liveness

The script — quick run:

```bash
python $HERMES_HOME/scripts/credential_audit.py
```

Per profile it reports each credential family's key presence and live-probes endpoints that are fully configured (X API search/recent — 1 credit, Telegram getMe, LM Studio /models, GitHub user). Report-only; values redacted. Flag any `FAIL` probe as a rotation candidate.

### Phase 5: Disk Space Check

```bash
# Check available disk space (warn if < 5GB free)
df -h ~/.hermes/  # on Linux/macOS via git-bash
dir %LOCALAPPDATA%\hermes  # $HERMES_HOME on Windows

# Or use Python for cross-platform:
python -c "
import shutil
total, used, free = shutil.disk_usage(os.environ['HERMES_HOME'])
print(f'Free: {free / (1024**3):.1f} GB of {total / (1024**3):.1f} GB total')
if free < 5 * 1024**3:
    print('⚠️ LOW DISK SPACE — state.db writes may fail')
"
```

### Phase 6: Remediation Playbooks

#### Auto-Heal Mode (OPT-IN)

Set `auto_heal=true` to allow these automatic fixes. **Default is report-only.**

| Issue | Auto-Fix | Manual Alternative |
|---|---|---|
| Gateway not running | `hermes gateway start` | Same, but user confirms first |
| Cron scheduler stopped | Restart via `hermes cron status --fix` or gateway restart | `hermes gateway restart` |
| state.db > 1GB | Prune sessions: `hermes sessions prune --older-than 30d` | Interactive prune with review |
| Deprecated config keys | `hermes doctor --fix` (auto-migrates) | Manual edit via `hermes config set` |
| Missing .env | Create stub, prompt user to fill in keys | Same — never write secrets for the user |

**Never auto-heal**: API key rotation, model changes, profile deletions, skill installations. These require explicit user confirmation.

#### Common Remediation Commands

```bash
# Fix config issues automatically (safe migrations only)
hermes doctor --fix

# Restart gateway to pick up new config / clear stale state
hermes gateway restart

# Prune old sessions to reclaim disk space
hermes sessions prune --older-than 30d

# Check and fix cron scheduler
hermes cron status  # reports, then:
hermes gateway start  # if stopped

# Reset permissions / clear stuck state
hermes security reset-permissions  # (if available in this version)
```

### Phase 7: Verification Discipline (from SOUL.md)

After any remediation, **never assume changes are live without checking**:

1. `hermes status` — confirms gateway is running with correct PID
2. `hermes cron status` — confirms scheduler heartbeat is fresh
3. For model/config changes: start a new chat and verify the active model in session info
4. Run one cron job manually to confirm it works post-remediation
5. Check that state.db writes succeed (create/search a test session)

## Self-Monitoring Cron Job (Optional)

This skill can drive itself via a lightweight daily cron on Default:

```python
# Script: ~/.hermes/scripts/hermes_health_check.py
import subprocess, shutil, json, os
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()
issues = []

# 1. Doctor check
result = subprocess.run(["hermes", "doctor"], capture_output=True, text=True)
if result.returncode != 0:
    issues.append(f"Doctor failed with exit code {result.returncode}")

# 2. Gateway process
status = subprocess.run(["hermes", "cron", "status"], capture_output=True, text=True)
if "running" not in status.stdout.lower():
    issues.append("Gateway/cron scheduler NOT running")

# 3. Disk space
total, used, free = shutil.disk_usage(str(HERMES_HOME.parent))
free_gb = free / (1024**3)
if free_gb < 5:
    issues.append(f"Low disk space: {free_gb:.1f} GB free")

# 4. state.db size
db_path = HERMES_HOME / "state.db"
if db_path.exists():
    size_mb = db_path.stat().st_size / (1024**2)
    if size_mb > 1024:  # > 1GB
        issues.append(f"state.db is {size_mb:.0f} MB — consider pruning sessions")

# Report
if issues:
    print("⚠️ HERMES HEALTH ISSUES:")
    for issue in issues:
        print(f"  - {issue}")
else:
    print(f"✅ Hermes healthy. Disk free: {free_gb:.1f} GB, state.db: {size_mb:.0f} MB")
```

Schedule it: `hermes cron create "0 9 * * *" --script hermes_health_check.py --no-agent --deliver telegram`

## Quick Command Reference

```bash
# Full diagnostics
hermes doctor                    # config, packages, security advisories
hermes status --all              # API keys (redacted), auth providers, gateway
hermes status --deep             # extended checks (slower)

# Gateway & cron liveness
hermes gateway status            # is the messaging gateway running?
hermes cron status               # scheduler alive + heartbeat age

# Process check (git-bash ps equivalent)
ps aux | grep -i "hermes" | grep -v grep

# State file health
ls -lh ~/.hermes/state.db        # monitor growth (>1GB = prune needed)
python -c "import sqlite3; print(sqlite3.connect('~/.hermes/state.db').execute('PRAGMA integrity_check').fetchall())"
python -c "import json; print(json.dumps(json.load(open('~/.hermes/gateway_state.json')), indent=2))"

# Disk space (cross-platform)
python -c "import shutil; t,u,f = shutil.disk_usage('.'); print(f'{f/1024**3:.1f} GB free')"

# Auto-fix safe issues only
hermes doctor --fix              # migrates deprecated config keys, etc.

# Remediation commands (manual confirmation required)
hermes gateway restart           # pick up new config / clear stale state
hermes sessions prune --older-than 30d  # reclaim disk space from old sessions
```

## Verification Checklist

- [ ] `hermes doctor` passes with no errors or warnings (or all acknowledged)
- [ ] No active security advisories (or they're explicitly acked via `--ack`)
- [ ] Gateway process running with matching PID (`hermes status --all`)
- [ ] Cron scheduler heartbeat is recent (< 60s, from `hermes cron status`)
- [ ] state.db integrity check returns `[('ok',)]`
- [ ] gateway_state.json exists and parses as valid JSON
- [ ] Disk space > 5GB free on HERMES_HOME's filesystem
- [ ] If auto-heal ran: re-verify all checks pass after remediation
- [ ] Restart reminder surfaced if config/gateway changes were applied