---
name: model-config-propagator
description: "Use when changing models or config across profiles."
version: 1.0.0
author: Hermes Agent + KB
license: MIT
platforms: [linux, macos, windows]
tags: [hermes, configuration, models, propagation]
---

# Model & Config Propagator

## Overview

Safe procedures for changing the default model/provider and propagating (or selectively applying) to other profiles. Covers `hermes model`, per-profile config overrides via `hermes -p <name> config set`, drift-guard behavior for unpinned cron jobs, verification that changes are live, and the restart reminder for existing sessions.

## When to Use

- User asks to change the default LLM or provider
- Config needs propagation across profiles (selective or blanket)
- Cron model-drift errors appear ("Skipped to prevent unintended spend")
- Need to verify a config/model change is actually live before reporting done
- Profile-specific LM Studio endpoints differ from global default

## Key Concepts

### Drift Guard for Unpinned Cron Jobs

When the default/profile model changes after a cron job was created, Hermes blocks inference calls for **unpinned** jobs with:

```
RuntimeError: Skipped to prevent unintended spend: global inference config drifted since this job was created (model 'X' -> 'Y'), and this job is unpinned.
```

This prevents surprise charges if the default model switched to an expensive cloud option. **Fix**: pin explicitly via CLI (`cronjob` tool's `provider`/`model` fields silently fail — only the CLI works).

### Profile-Specific Endpoints

LM Studio exposes per-profile inference endpoints:

| Endpoint | Scope |
|---|---|
| `http://127.0.0.1:1234/v1` | Default profile global |
| `http://127.0.0.1:1234/p/<profile>/v1` | Profile-specific route |

Each endpoint may have different models loaded in LM Studio's UI — verify availability before relying on a model for cron jobs.

### Pinned vs Unpinned Cron Jobs

- **Pinned**: `model` field set to a specific model string → runs regardless of global config drift
- **Unpinned** (`model: null`): inherits the profile's current default → blocked if drift detected since creation

## Workflow

### Step 1: Change Default Model (Global)

```bash
# Interactive wizard
hermes setup
# or
hermes model

# Scripted change (preferred for automation)
hermes config set model.default <model-id>
```

**Note**: `config.yaml` changes to `model.default` do NOT hot-reload — a process restart is required.

### Step 2: Propagate to Other Profiles (Selective or Blanket)

#### Per-profile override (recommended for non-uniform models)

Profiles that use different models than the global default need individual updates:

```bash
hermes -p <profile-name> config set model.default <model-id>
```

**Important**: This does NOT update cron jobs' pinned `model` fields in those profiles — see Step 3.

#### Blanket sweep (find stale references)

After any model change, search all configs for the old name:

```bash
grep -rn '<old-model-name>' ~/.hermes/ --include="*.yaml" --include="*.json" --include="*.md" \
  --exclude-dir=.hub
```

The `.hub` cache is auto-generated and can be ignored. Session dumps in `sessions/` may contain stale references but are historical only.

### Step 3: Update Pinned Cron Jobs (CRITICAL)

**Each cron job has its own `model` field pinned at creation time.** config.yaml changes do NOT cascade to jobs. Use the CLI exclusively — the `cronjob(action='update')` tool's provider/model fields silently fail.

```bash
# List all jobs in a profile
hermes -p <profile-name> cron list

# Pin each agent-based job (no_agent: false) individually
hermes -p <profile-name> cron edit <job_id> --model <new-model> --provider custom
```

**Script-only jobs (`no_agent: true`)** have `model: null` and don't use inference — safe to skip those.

#### Drift-guard check for unpinned jobs

Unpinned agent-based jobs will be blocked on their next scheduled run if the model changed since creation. Pin them proactively rather than waiting for failures:

```bash
# Check recent cron runs for drift errors
hermes -p <profile-name> cron history | grep "Skipped to prevent unintended spend"
```

### Step 4: Verify Changes Are Live (Verification Discipline)

Never assume changes are live without checking. Run these verifications **after** restarting Hermes:

1. **Verify default profile model**:
   ```bash
   hermes config show | grep "Model:"
   # or check the active session info in a new chat
   ```

2. **Verify each profile's model**:
   ```bash
   hermes -p <profile-name> config show | grep "model.default"
   ```

3. **Run one cron job manually** to confirm it uses the new model without errors:
   ```bash
   hermes -p <profile-name> cron run <job_id>
   ```

4. **Check LM Studio**: Ensure the new model is actually loaded in LM Studio's developer page — crons will fail with "No models loaded" if LM Studio doesn't have a model ready at that endpoint.

5. **Restart Hermes Gateway** (if using Telegram/Discord/etc):
   ```bash
   hermes gateway restart
   ```

6. **Test via messaging platform**: Send a test message to confirm the gateway uses the new model.

### Step 5: Restart Reminder

After any config/model change, surface this reminder:

> ⚠️ Existing Hermes sessions and the Gateway are still running on old state until restarted. Start fresh chats in each affected profile and restart the Gateway (`hermes gateway restart`) to pick up new model/config changes. Cron jobs with pinned models must be updated individually via `hermes cron edit`.

## Common Pitfalls

1. **Cron job model drift**: The #1 issue — changing config.yaml doesn't update individual job pins. Always audit and pin after a model change.
2. **`cronjob` tool silently fails on pinning**: Passing `provider`/`model` to `cronjob(action='update')` returns success but the fields stay null. Only `hermes cron edit <id> --model X --provider Y` works reliably.
3. **Profile-specific LM Studio endpoints have different models loaded**: The default endpoint (`http://127.0.0.1:1234/v1`) may show a model as available, but `/p/<profile>/v1` might not have it loaded in LM Studio's UI. Verify both.
4. **`.env` is for secrets only**: Model names don't belong there — they're ignored. Config goes in `config.yaml`.
5. **Auxiliary models are separate**: Vision, web_extract, compression, approval, and title_generation each have their own model settings under `auxiliary.*`. Don't change those unless intentionally swapping the aux model too.

## Quick Command Reference

```bash
# Change global default (scripted)
hermes config set model.default <model-id>

# Interactive picker
hermes model

# Per-profile override
hermes -p <profile> config set model.default <model-id>

# List cron jobs in a profile (check which are agent-based vs script-only)
hermes -p <profile> cron list

# Pin a specific job (CLI ONLY — tool pinning silently fails)
hermes -p <profile> cron edit <job_id> --model <new-model> --provider custom

# Find stale model references across all configs
grep -rn '<old-model>' ~/.hermes/ --include="*.yaml" --include="*.json" --include="*.md" --exclude-dir=.hub

# Restart gateway after changes
hermes gateway restart
```

## Verification Checklist

- [ ] Global default model changed via `hermes config set` or `hermes setup`
- [ ] Per-profile overrides applied where profiles use different models
- [ ] All agent-based cron jobs pinned individually via `hermes -p <profile> cron edit --model X --provider Y`
- [ ] Stale references searched and cleaned (excluding `.hub` cache)
- [ ] LM Studio verified to have the new model loaded at each profile endpoint
- [ ] One cron job manually run to confirm no drift error
- [ ] Gateway restarted if messaging platforms are in use
- [ ] Restart reminder surfaced to user