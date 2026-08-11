---
name: hermes-state-db-guard
description: "Use when Hermes state.db corrupts or needs watchdog checks."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [hermes, database, corruption, watchdog, backup, sqlite, windows]
---

# Hermes state.db Guard (cross-profile watchdog + backup)

Solves silent Hermes `state.db` corruption (gateway SIGKILL/OOM mid-write) with
**immediate Telegram alert** + **auto-restore** + **rotating known-good backups**.

## When to Use
- A Hermes profile's `state.db` is corrupt ("database disk image is malformed"),
  sessions disappear, or `PRAGMA quick_check` fails.
- You need to check the health of all profiles' session stores, inspect backups, or
  manually restore one.
- The `Hermes_DB_Guard` scheduled task needs maintenance.

## Script (lives in the DEFAULT profile — this is a machine-level tool)
`<HERMES_HOME>/scripts/db_guard.py` (e.g. `C:\Users\<user>\AppData\Local\hermes\scripts\db_guard.py` on Windows,
`~/.hermes/scripts/db_guard.py` on macOS/Linux)
(stdlib only — sqlite3, urllib, argparse. No external deps. Location-independent.)

Runs every 30 min via **Windows Scheduled Task `Hermes_DB_Guard`** (interactive
session, run-as the owning user). Survives gateway death because it's OS-level, not Hermes-level.

## What it does each `check` pass
1. Scans `<HERMES_HOME>/profiles/*` for `state.db` (all profiles).
2. `PRAGMA quick_check` each (fast, safe every 30 min).
3. On corruption: saves a forensic `*.corrupt.*.db` copy, **alerts Telegram immediately**
   (de-duped — once per episode until healthy again), then **auto-restores** from newest
   known-good backup.
4. Healthy profiles: takes a `VACUUM INTO` backup if none in last 6h; keeps newest 12.
5. Flags concurrent writers (multiple processes holding same state.db).

## Commands (from the default profile)
```bash
PY="$HERMES_HOME/hermes-agent/venv/Scripts/python.exe"   # Windows
cd "$HERMES_HOME"
"$PY" scripts/db_guard.py status      # health + last backup per profile
"$PY" scripts/db_guard.py check       # run a pass (exit 1 = corruption found)
"$PY" scripts/db_guard.py backup      # force known-good backups now
"$PY" scripts/db_guard.py restore <profile> [--force]
```

## Key paths
- Backups: `<HERMES_HOME>/db_guard_backups/<profile>/`
  - `*.known-good.<ts>.db` = verified VACUUM INTO snapshots (keep 12)
  - `*.corrupt.<ts>.db` = forensic copies of detected corruption
  - `armed.<profile>` = de-dupe marker (present while an episode is active)
- Telegram env: `<HERMES_HOME>/.env` (default profile's root .env)
  - **`TELEGRAM_BOT_TOKEN` is stored single-quoted in .env** — strip the quotes when
    parsing, or getMe returns HTTP 404.
- The script auto-locates Hermes home by walking up to a dir containing `profiles/` +
  `config.yaml`, so it works from either the default `scripts/` or a named profile.

## Pitfalls
- `VACUUM INTO` must run **outside a transaction** (connect with `isolation_level=None`),
  else: `OperationalError: cannot VACUUM from within a transaction`.
- Restore uses atomic `os.replace`; on Windows a file locked by another process fails —
  the script reports it so a human can stop the writer first.
- Restore refuses to clobber a *healthy* live DB unless `--force`.
- The MSYS/git-bash shell mangles `schtasks` and `wmic` flags — set
  `MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'` before those commands.

## Manual steps still pending (require admin/user action)
- **Defender exclusion** (needs elevated PowerShell):
  `Add-MpPreference -ExclusionPath '<HERMES_HOME>\profiles'`
  `Add-MpPreference -ExclusionPath '<HERMES_HOME>\db_guard_backups'`
- **Single-writer discipline**: if two `serve`/gateway processes target the same profile
  (e.g. a venv python + a uv python instance), consolidate to one writer to remove the
  multi-writer corruption vector. Don't kill them blindly — one hosts the active session.

## Root cause history (2026-08-10)
Previous gateway (pid 2300) was SIGKILLed/OOM'd mid-write; only
one profile's `state.db` corrupted (others confirmed OK via quick_check). The DB was
structurally broken (freelist + btree pages). This is the canonical failure mode this
skill guards against. Ensure every profile has a known-good backup so auto-restore has
something to restore from.
