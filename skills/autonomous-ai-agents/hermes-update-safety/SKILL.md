---
name: hermes-update-safety
description: "Use when updating or upgrading Hermes safely."
version: 1.0.0
author: Hermes Agent + KB
license: MIT
platforms: [linux, macos, windows]
tags: [hermes, updates, maintenance, verification]
---

# Hermes Update Safety

## Overview

Runbook for updating the Hermes Agent installation without losing config, skills, state, or gateway availability. Updating is the highest-risk recurring operation on this fleet: history shows `config.yaml.corrupt` backups on ASM, `state.db` malformed-backup pileups, and stalled gateways after changes. Every update gets: backup first → changelog review → update → full post-verification.

## When to Use

- User says "update hermes", "upgrade", "install the new version"
- `hermes update` is about to run (or just ran) on this profile
- Before/after version bumps that touch the gateway, config schema, or toolsets

## Workflow

### Phase 1: Pre-Flight — Back Up FIRST (never skip)

```bash
# 1. Manual HermGIT backup (covers config, skills, cron, scripts, memories, SOUL)
python $HERMES_HOME/scripts/github_backup.py

# 2. Snapshot the live config + state (belt-and-suspenders for rollback)
cp $HERMES_HOME/config.yaml $HERMES_HOME/config.yaml.pre-update.bak
cp $HERMES_HOME/gateway_state.json $HERMES_HOME/gateway_state.json.pre-update.bak

# 3. Record the current version for rollback reference
hermes --version
```

Note: `updates.pre_update_backup` may be `false` in config.yaml — never rely on it. The manual backup above is the guarantee. Check for uncommitted local changes to bundled files: `hermes skills list-modified` (updates stash them via `updates.non_interactive_local_changes: stash`).

### Phase 2: Changelog Review

```bash
hermes update --check    # or: hermes changelog / release notes
```

Skim for breaking changes that touch: config schema version (`_config_version`), toolset names, provider/model config, cron or skills format. If a breaking change affects pinned cron models or custom providers, plan to re-verify them post-update.

### Phase 3: Run the Update

```bash
hermes update
```

If the update reports config migrations, do NOT hand-edit anything — the migration writes the new schema itself. Afterwards run `hermes config check` to confirm the schema is current.

### Phase 4: Post-Update Verification (MANDATORY — never assume)

| Check | Command | Pass condition |
|---|---|---|
| Config integrity | `hermes doctor` | No errors; config version matches |
| Config parse | `hermes config check` | No missing/outdated sections |
| Gateway (default) | `hermes gateway status` | Running, PID matches |
| All profiles | `hermes -p <name> gateway status` | Each profile with cron jobs has a live gateway |
| Cron scheduler | `hermes cron status` | Heartbeat fresh (<60s); no jobs stale |
| state.db | `PRAGMA integrity_check` | `[('ok',)]` |
| Skills load | `hermes skills list` | No missing/corrupt skills; pinned names intact |
| Model resolution | Start a test session or `hermes model` | Default model resolves (per your configured provider) |
| Toolchain | `hermes doctor` security section | No new npm vulnerabilities introduced |

If a profile's gateway is down after update: start it (`hermes -p <name> gateway start`) and re-run the check. The ASM watchdog (every 10m) self-heals within ~7s — but verify, don't wait for it.

## Pitfalls

1. **Hand-editing post-migration config** — migrations write `_config_version` and new sections themselves. Hand-edits after a migration can corrupt the file (this fleet has `config.yaml.corrupt` history). Use `hermes config set` for any follow-up tweaks.
2. **Skipping the pre-backup** — `updates.pre_update_backup: false` in this config means NO automatic backup. Run `github_backup.py` manually.
3. **Stale sessions after update** — existing sessions keep the old prompt/toolset until restarted (prompt-caching rule). Surface the restart reminder.
4. **Pinned cron models don't inherit config changes** — each job carries its own `model` field. If the update changes the model schema/provider, re-pin with `hermes cron edit <job_id> --model X -p <profile>`.
5. **npm/doctor advisories after update** — the toolchain audit may show new advisories; `hermes doctor --fix` deliberately does NOT touch workspace npm (arborist crash bug) — handle per the npm-vuln playbook, don't fight the tool.
6. **Gateway restart kills running agents** — `hermes gateway restart` terminates active sessions. Do it outside an active conversation, then verify per Phase 4.

## Verification Checklist

- [ ] Pre-update backup ran (github_backup.py) and git push succeeded
- [ ] config.yaml + gateway_state.json snapshots exist
- [ ] Changelog reviewed for breaking changes (config schema, toolsets, cron/skills format)
- [ ] `hermes update` completed without errors
- [ ] `hermes doctor` clean; `hermes config check` current
- [ ] All profiles' gateways running; cron heartbeats fresh
- [ ] state.db integrity ok; no new malformed-backup files
- [ ] Skills list intact; pinned skills still present
- [ ] Restart reminder surfaced for stale sessions
- [ ] Rollback path documented (pre-update backup + version recorded)
