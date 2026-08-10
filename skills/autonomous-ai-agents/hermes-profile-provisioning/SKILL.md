---
name: hermes-profile-provisioning
description: "Use when building a new Hermes profile. Verify boot."
version: 1.0.0
author: agent
license: MIT
platforms: [windows, linux, macos]
tags: [hermes, profiles, provisioning, verification, smoke-test]
---

# Hermes Profile Provisioning

Execution playbook for standing up a NEW specialized Hermes profile end-to-end: create, stock with skills, author SOUL, wire the model, and prove it boots before handoff. Complements `hermes-profile-manager` (which owns the lifecycle outline → confirm → export/import → retire flow); this skill carries the concrete build + verification commands. If the profile already exists and you're only changing its model/skills, see `model-config-propagator` instead.

## When to Use

- User asks to build a new profile ("build me a profile for X", "set up a profile for Y")
- You need to stock a fresh profile with skills and verify it runs before the user walks over to it

## Workflow

### 0. Research BEFORE executing (user expectation — KB)

The user explicitly expects the default profile to research anything it's unsure about BEFORE writing files:

- **Ground domain content in existing fleet intel**: cross-profile `session_search(profile='<source>', query=..., sort='newest')` to extract real narrative/facts for the new profile's SOUL and domain skill. Never invent product/domain specs — carry narrative claims *as claims* and keep a TBD list for the owner to fill.
- **Check fleet model wiring first**: `grep -A 6 "^model:"` on a working profile's config.yaml to see the exact provider/base_url/key_env pattern before setting anything.
- **Survey existing skills** worth bundling (skills_list + category dirs) vs. authoring new ones.

### 1. Propose outline, get confirmation

Follow hermes-profile-manager Phase 1: name, purpose (SOUL), recommended model, key skills/tools, delivery targets, pinned cron?, rationale. Present as a message; do NOT write files until confirmed. Ask whether the user wants fresh/independent vs clone — "fully new and independent" is the common answer for business domains.

### 2. Create

```bash
hermes profile create <name> --description "<purpose for kanban routing>" --no-skills
```

- `--no-skills` for lean builds (opts out of `hermes update` skill sync; delete `.no-bundled-skills` to opt back in).
- Do NOT clone unless the user wants default's config/SOUL/skills copied.

### 3. Stock skills (fresh profiles start empty)

Two mechanisms:

- **Copy existing skills** from another profile's skills dir (skills are just files; plain `cp -r` works, no CLI needed):
  ```bash
  P="$HERMES_HOME/profiles/<name>"; mkdir -p "$P/skills"
  cp -r "$HERMES_HOME/skills/software-development/plan" "$P/skills/"
  ```
- **Author a new domain skill** with write_file directly into the target profile — NOT skill_manage (skill_manage writes to the ACTIVE profile's skills dir):
  ```
  write_file(path="$HERMES_HOME/profiles/<name>/skills/<skill-name>/SKILL.md", cross_profile=true)
  ```
  Rule: the skill directory name must exactly match the SKILL.md `name:` field. Fill it with the researched facts from step 0.

### 4. Author SOUL.md

`write_file(path="$HERMES_HOME/profiles/<name>/SOUL.md", cross_profile=true)`. Include: role + owner, what the profile does/sells (know this cold), working rules (plan-first, verify-before-done, never invent specs, secrets → .env), key paths. Never put secrets in SOUL.md.

### 5. Wire the model (NEVER hand-edit config.yaml)

The fleet-standard quartet, per key:

```bash
hermes -p <name> config set model.default <model>
hermes -p <name> config set model.provider custom
hermes -p <name> config set model.base_url http://127.0.0.1:1234/v1
hermes -p <name> config set model.key_env LMSTUDIO_API_KEY
```

(Example is LM Studio wiring; adjust provider/keys per environment. A stray hand-edit indent can corrupt config.yaml and break the live gateway.)

### 6. Verify (never assume — prove it)

1. `hermes profile show <name>` — model, skills count, SOUL/.env existence
2. Skills integrity: loop `test -f "$P/skills/"*/SKILL.md`
3. Config landed: `grep -A 6 "^model:" "$P/config.yaml"`
4. **Boot smoke test** — end-to-end proof the profile boots, loads SOUL+skills, connects to its model provider, and runs inference:
   ```bash
   hermes -p <name> chat -q "Reply with exactly: PROFILE_OK" -Q --max-turns 1
   # expect: session_id: <id>  +  PROFILE_OK  +  exit 0
   ```
   If this returns garbage/errors, the profile is NOT ready — fix before handoff.

### 7. Bookkeeping + handoff

- Add the profile row to default's SOUL.md fleet map (patch the table under "## Fleet & Cron Doctrine"; read_file the SOUL first to locate the table — see pitfall on pipe escaping).
- Save a compact memory entry: purpose, model, skills, gateway policy (always-on / on-demand / watchdog), cron ownership, delivery.
- Surface the restart reminder: existing sessions for that profile may use old state until restarted (a brand-new profile boots clean on first use).
- Answer the "should I update Hermes first?" question: NO — if `profile create` / `config set` / the smoke test all work on the current build, an update is not needed to use the new profile and would only risk disrupting running gateways. Only update with a reason, via `hermes-update-safety`.

## Pitfalls

- **skill_manage writes to the active profile only** — for another profile's skills, write files directly with `cross_profile=true`.
- **`hermes config set` writes scalars** — the model quartet is all scalars so config set is correct; list keys (e.g. skills.disabled) need the framework API (see hermes-profile-manager pitfalls).
- **grep literal pipes**: searching SOUL.md for a fleet-map row like `| <profile-name> |` — `\|` escaping in ripgrep can silently fail and return a wrong match; read_file on the file is the reliable way to locate the table.
- **Keep default lean**: domain skills belong in the new profile, never default's skills dir.
- **Don't invent specs** in domain skills — mark narrative claims as claims; maintain a TBD list for the owner.


