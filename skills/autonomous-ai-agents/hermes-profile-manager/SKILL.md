---
name: hermes-profile-manager
description: "Use when managing Hermes profile lifecycle."
version: 1.0.0
author: Hermes Agent + KB
license: MIT
platforms: [linux, macos, windows]
tags: [hermes, profiles, configuration, lifecycle]
---

# Hermes Profile Manager

## Overview

Codifies the profile lifecycle workflow for the Default meta-agent. Every step enforces the hard invariants from SOUL.md: resolve paths from `$HERMES_HOME`, never hand-edit `config.yaml` (use `hermes config set`), never store secrets in SOUL.md, and always remind about session restarts after editing another profile's files.

## When to Use

- User asks to create a new specialized profile
- Profile needs cloning (`--clone`, `--clone-all`, `--clone-from`)
- Editing an existing profile's SOUL/config safely
- Export/import of profiles for backup or migration
- Any profile lifecycle operation that touches another profile's config/skills/memory/cron

## Workflow

### Phase 1: Propose Outline (WAIT for confirmation)

Before writing any files, propose this outline and **wait for the user to confirm**:

```
Profile Name: <suggested-name>
Purpose (SOUL): One sentence describing what this profile is good at.
Recommended Model: e.g., <model-id> @ <provider> (local LM Studio or cloud)
Key Skills/Tools: List of skills this profile should load on demand
Delivery Targets: Telegram? Discord? Local only?
Pinned Cron?: Yes/No — does it run scheduled jobs that need model pinning?

Rationale: Why a new profile vs. doing the work in Default or an existing one?
```

**Do NOT create files until confirmed.** The proposal lives as a message, not on disk.

### Phase 2: Create / Clone

#### Fresh Profile (no skills)

```bash
hermes profile create <name> --description "<purpose>" --no-skills
```

#### From Current Default (`--clone`)

Copies `config.yaml`, `.env`, `SOUL.md`, and bundled skills from the active profile:

```bash
hermes profile create <name> --clone --description "<purpose>"
```

#### Full Copy Including State (`--clone-all`)

Same as `--clone` but also copies per-profile state (cron, scripts, memories). Excludes session history. Use when you want an exact replica that can run immediately:

```bash
hermes profile create <name> --clone-all --description "<purpose>"
```

#### From a Different Source Profile (`--clone-from`)

Clone from any existing profile, not just the active one:

```bash
# Implies --clone unless --clone-all is also set
hermes profile create <name> --clone-from <source-profile> --description "<purpose>"
```

**Flags:**
- `--no-alias` — skip wrapper script creation (advanced users)
- `--no-skills` — empty profile with no bundled skills (opts out of `hermes update` skill sync)
- `--description DESC` — one or two sentence role description (used by kanban decomposer for routing)

### Phase 3: Edit SOUL / Config Safely

#### SOUL.md

Write directly to the profile's `SOUL.md`. **Never** put API keys, tokens, or secrets here — those go in `<profile>/.env`:

```
<HERMES_HOME>/profiles/<name>/SOUL.md
```

#### config.yaml

**NEVER hand-edit.** Always use:

```bash
hermes -p <name> config set model.default <model-id>
hermes -p <name> config set terminal.timeout 1200
```

A stray indent in `config.yaml` can corrupt the file and break the live gateway. The CLI handles YAML safety for you.

**Profile-safe path resolution:** Always resolve from `$HERMES_HOME`, never hardcode `~/.hermes`. On this system:

```
HERMES_HOME = <your hermes home>  # e.g. ~/.hermes or %LOCALAPPDATA%\hermes
Profiles live at  $HERMES_HOME/profiles/<name>/
```

### Phase 4: Restart Reminder (CRITICAL)

After editing another profile's files, **always surface**:

> ⚠️ Existing sessions for `<profile-name>` may still be using old state until a new session is started. Start a fresh chat in that profile to pick up the changes.

For model/config changes specifically, also note:
- Cron jobs with pinned models do NOT inherit config.yaml model changes — each job has its own `model` field. Update via `hermes cron edit <job_id> --model X -p <profile>`.
- The Hermes Gateway (if running for that profile) must be restarted to pick up new config: `hermes gateway restart`.

### Phase 5: Export / Import

#### Export (backup or share)

```bash
hermes profile export <name>   # writes to a .tar.gz archive
```

#### Import (restore from archive)

```bash
hermes profile import <archive-file>
```

### Phase 6: Retire / Archive a Profile

Full retirement when a profile's purpose is finished (never delete blindly — the fleet has archive precedent at `<HERMES_HOME>/archives/`):

```bash
# 1. Inventory what the profile owns
hermes -p <name> cron list          # all scheduled jobs
hermes -p <name> gateway status     # is a gateway running?

# 2. Pause/remove all cron jobs (per job id from step 1)
hermes -p <name> cron pause <job_id>   # or: cron remove <job_id>

# 3. Stop the gateway (frees the LM Studio slot + resources)
hermes -p <name> gateway stop

# 4. Snapshot for rollback (config, SOUL, skills, memories, cron, scripts)
hermes profile export <name>        # writes <name>.tar.gz

# 5. Archive the archive-file + move the profile dir out of active use
#    (move to <HERMES_HOME>/archives/<name>-retired-<date>/ — see abvx-mine, outreach-mine precedent)
```

Then update fleet records:
- **SOUL.md fleet map** (default profile) — remove the row, or mark it "retired <date>"
- **Memory** — note the retirement so future sessions don't route work there
- **Any cron in other profiles referencing this profile** (workdir, delivery, context_from) — repoint or remove

**Warnings:**
- Existing sessions keep running on old state until restarted — surface the restart reminder.
- Export BEFORE stopping anything you can't recreate; `.tar.gz` is the rollback unit.
- Don't delete the profile dir until the export + archive is verified readable (`tar tzf`).
- Check for leftover watchdogs/health checks that monitor this profile (e.g. default's `cron_health_check.py` flags profiles automatically — a retired profile with no cron jobs is informational only, no action needed).

## Hard Invariants (never violate)

| Rule | Detail |
|---|---|
| **Profile-safe paths** | Resolve real home from `$HERMES_HOME`. Never hardcode `~/.hermes` in scripts or skills. |
| **Never hand-edit config.yaml** | Use `hermes config set KEY VAL`. A stray indent can corrupt the file and break the live gateway. |
| **Secrets → .env only** | API keys, tokens, credentials go in `<profile>/.env`, never SOUL.md or config.yaml. |
| **Restart reminder** | After editing another profile's files, always tell the user existing sessions may be stale until restarted. |

## Common Pitfalls

1. **`--clone` vs `--clone-all`**: `--clone` copies only config/SOUL/skills. If a profile has cron jobs or scripts that depend on state, use `--clone-all`.
2. **Forgetting `--description`**: Without it, the kanban decomposer can't route tasks by role description — always set one for profiles meant to be task targets.
3. **Editing config.yaml directly**: Even with good intentions (e.g., "I'll just change this one line"), use `hermes config set`. YAML indentation errors are silent and catastrophic.
4. **Not restarting after edits**: The most common mistake — changes appear saved but old sessions keep running on stale state until a fresh session starts.
5. **`hermes config set` writes scalars only — list keys need the framework API**: `hermes config set skills.disabled '["a","b"]'` stores a JSON *string*, which `agent/skill_utils._normalize_string_set` treats as ONE giant skill name — so **nothing gets disabled**. The working form is a real YAML list; the sanctioned writer is `hermes_cli.skills_config.save_disabled_skills` (same code path as `hermes skills config`). Reusable helper: `scripts/fix_skills_disabled.py` (idempotent; pass skill names as args; set `HERMES_HOME` to target another profile). Contrast: `custom_providers` IS expected as a JSON string, so `hermes config set custom_providers '[...]'` is correct there.

## Quick Command Reference

```bash
# List all profiles with their models
hermes profile list

# Create from scratch (lean, no skills)
hermes profile create <name> --description "<purpose>" --no-skills

# Clone current default's config + SOUL + skills
hermes profile create <name> --clone --description "<purpose>"

# Full clone including cron/scripts/memories
hermes profile create <name> --clone-all --description "<purpose>"

# Clone from a specific source profile
hermes profile create <name> --clone-from <source> --description "<purpose>"

# Set active default profile (sticky)
hermes profile use <name>

# Show details (model, gateway, skills, .env, SOUL.md status)
hermes profile show <name>

# Export / Import
hermes profile export <name>
hermes profile import <archive-file>

# Safe config edits per-profile
hermes -p <name> config set model.default <model-id>
```

## Verification Checklist

- [ ] Profile outline proposed and confirmed by user before any file writes
- [ ] `HERMES_HOME` resolved correctly (not hardcoded `~/.hermes`)
- [ ] No secrets written to SOUL.md or config.yaml — only `.env`
- [ ] All config edits done via `hermes -p <name> config set`, never direct YAML editing
- [ ] Restart reminder surfaced after editing another profile's files
- [ ] Cron model pins updated separately if the profile runs agent-based cron jobs