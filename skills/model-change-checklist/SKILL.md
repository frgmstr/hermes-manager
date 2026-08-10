---
name: model-change-checklist
description: Config locations to update on every LLM swap.
version: 1.0.0
author: Hermes Agent + KB
license: MIT
platforms: [linux, macos, windows]
tags: [hermes, configuration, models, checklist]
---

# Model Change Checklist — When You Swap the Default LLM

Every time you change your primary model, update **all** of these locations. Missing even one means some chats, crons, or profiles will silently use an old/stale model — or fail entirely with errors like `HTTP 400: No models loaded` or the cron drift guard.

## Environment

- **Config home**: `$HERMES_HOME` (e.g. `~/.hermes` on macOS/Linux, `%LOCALAPPDATA%\hermes` on Windows)
- **Local inference (optional)**: an OpenAI-compatible server such as LM Studio — main endpoint `http://127.0.0.1:<port>/v1`, plus profile-specific endpoints under `/p/<profile-name>/v1` when serving multiple profiles

---

## 1. Default / Manager Profile — Main config.yaml

**File**: `$HERMES_HOME/config.yaml`

- `model.default` — the primary model
- `model.provider` / `model.base_url` / `model.key_env` — provider wiring
- `custom_providers[].model` / `.models[]` — any custom provider blocks (e.g. a local server) usually repeat the model name
- `fallback_model.model` — the fallback provider

**Auxiliary models (do NOT change unless intended)**: `auxiliary.vision.model`, `auxiliary.web_extract.model`, `auxiliary.compression.model`, `auxiliary.approval.model`, `auxiliary.title_generation.model`.

**Reasoning effort**: verify `agent.reasoning_effort` is valid (`none|minimal|low|medium|high|xhigh`). An invalid value (e.g. `max`) causes HTTP 400s on every API call.

---

## 2. .env

**File**: `$HERMES_HOME/.env` (secrets only)

- `LM_BASE_URL` / `LM_API_KEY` — keep pointing at the right inference endpoint if you use local models
- Model names do NOT belong in `.env` — they are ignored there. Model config lives in `config.yaml`.

---

## 3. Cron Jobs

**File**: `$HERMES_HOME/cron/jobs.json` (per-profile: `$HERMES_HOME/profiles/<name>/cron/jobs.json`)

Each cron job has a `model` field pinned at creation time. Update each pinned job:

```bash
hermes cron edit <job_id> --model <new-model>          # active profile
hermes -p <profile> cron edit <job_id> --model <new-model>
```

- Jobs with `"model": null` are script-only (`no_agent: true`) — no model to update.
- **Unpinned jobs** hit the drift guard: if the global config changed since creation, they refuse to run until explicitly pinned (`hermes cron edit <job_id> --model X --provider Y`). This is by design — pin deliberately.
- Jobs that reference other profiles' endpoints (via `workdir` or provider `base_url`) need the new model available at that endpoint.

---

## 4. Per-Profile Configs & SOUL.md Files

For every profile under `$HERMES_HOME/profiles/<name>/`:

- `config.yaml` — same keys as section 1 (`model.default`, `custom_providers[].model`, etc.). Profiles can intentionally use different models — only change them if you mean to.
- `SOUL.md` — update any model mentions in documentation sections.

```bash
for p in $HERMES_HOME/profiles/*/config.yaml; do echo "$p"; grep -n "model" "$p" | head; done
```

---

## 5. Skill Files (hardcoded model references)

Search all skill SKILL.md files for old model names after a change:

```bash
grep -rn '<old-model-name>' $HERMES_HOME --include="*.yaml" --include="*.json" --include="*.md"
```

---

## 6. After Updating — Verification Steps

1. **Restart Hermes** — `model.default` changes do not hot-reload.
2. **Verify the manager profile**: start a new chat, check the active model in session info.
3. **Verify each profile**: switch to each profile and start a chat — confirm the right model loads.
4. **Run one agent-based cron job manually**: `hermes cron run <job_id>` (or `hermes -p <name> cron run <job_id>`) to confirm it uses the new model without errors.
5. **Check the inference server**: ensure the new model is actually loaded (crons fail with "No models loaded" if the local server doesn't have it).
6. **Restart the gateway** (if you use Telegram/Discord/etc.): `hermes gateway restart` so messaging integrations pick up the new model.
7. **Verify via a messaging platform**: send a test message to confirm the gateway uses the new model.

---

## Quick Command Reference

```bash
# Change default model (CLI wizard)
hermes setup
# or
hermes model

# Set via config directly (preferred for scripted changes)
hermes config set model.default <new-model>

# Update a specific cron job's model
hermes cron edit <job_id> --model <new-model>

# Verify what's currently active
grep -E 'model\.default|reasoning_effort' $HERMES_HOME/config.yaml

# Find all stale references after a change (run this!)
grep -rn '<old-model-name>' $HERMES_HOME --include="*.yaml" --include="*.json" --include="*.md"
```

---

## Automation Script

A Python script is bundled with this skill to automate the search-and-replace across all config files (pure Python file I/O — no `grep` dependency; works on Windows, macOS, Linux):

```bash
# Dry run first (shows what would change without modifying anything)
python skills/model-change-checklist/scripts/update_model.py \
  --old-model "<old-model>" \
  --new-model "<new-model>" \
  --dry-run

# Actually perform the swap
python skills/model-change-checklist/scripts/update_model.py \
  --old-model "<old-model>" \
  --new-model "<new-model>"
```

The script:

- Resolves `$HERMES_HOME` from the environment (portable default: `%LOCALAPPDATA%\hermes` on Windows, `~/.hermes` elsewhere)
- Scans `config.yaml`, all per-profile configs (`profiles/*/config.yaml`), all cron `jobs.json` files, and all profile `SOUL.md` files
- Skips the skill index cache (`.hub/index-cache`) — it is auto-generated
- Reports any remaining references that need manual attention

---

## Common Pitfalls

1. **Cron jobs don't inherit profile model changes** — each job has its own `model` field pinned at creation time. Update them individually.
2. **`reasoning_effort` values must be valid** — `none`, `minimal`, `low`, `medium`, `high`, `xhigh`. Invalid values cause HTTP 400s.
3. **Profile-specific inference endpoints** (`/p/<profile>/v1`) may have different models loaded than the main endpoint — verify in the server's UI that each profile's model is available.
4. **Script-only crons (`no_agent: true`)** don't use a model at all — their `model` field can be `null`. Don't waste time updating those.
5. **`.env` files are for secrets only** — never put model names there (they're ignored).
