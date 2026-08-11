# Hermes Manager — a shareable Hermes meta-agent profile

A sanitized, portable version of the author's personal "meta-agent" profile: an agent whose whole job is managing Hermes itself — profiles, skills, cron, memory, gateway health, and fleet hygiene. Install it as its **own profile**; it does not touch your default profile or any existing one.

## What you get

- **`SOUL.md`** — the manager's system prompt: hard invariants, routing table, profile-management workflow, fleet/cron doctrine, verification discipline.
- **`config.yaml`** — portable operational settings (compression, guardrails, security, terminal). **No provider/model** — you pick your own at setup.
- **Skills** — curated meta-skill kit (each loads on demand via `skill_view`):
  - `hermes-agent` — the official Hermes operating skill (routing hub + reference files)
  - `hermes-profile-manager` — profile lifecycle: create / clone / export / retire
  - `hermes-profile-provisioning` — verify a freshly built profile actually boots
  - `hermes-system-monitor` — doctor-style health checks, gateway/disk/state.db integrity
  - `cron-health-auditor` — scheduler liveness, per-profile job inventory, failure classification
  - `skill-auditor` — broken refs, stale content, name collisions, memory hygiene
  - `model-config-propagator` — change models across profiles safely (drift-guard aware)
  - `hermes-update-safety` — pre/post-update backup + verification
  - `merge-reconciler` — neutral resolution of agent-vs-agent merge conflicts
  - `cron-troubleshooting` — diagnose failing cron jobs (incl. gateway ticker stall)
  - `hermes-backup-recovery` / `hermes-backup-debug` — git-based backup + repair
  - `model-change-checklist` — every config location to touch on an LLM swap
  - `hermes-state-db-guard` — cross-profile `state.db` corruption watchdog + auto-restore
    (detect → alert → forensic copy → restore from rotating known-good backups)
  - `hermes-profile-distribution` — package, sanitize, test, and publish shareable profiles
- **Scripts** — fleet tools used by the skills and suggested cron jobs:
  - `cron_health_check.py` — daily health audit across profiles (rotates stale state.db backups)
  - `skill_hygiene_audit.py` — skill hygiene scan (broken refs, stale content, collisions)
  - `credential_audit.py` — credential presence + liveness probes (report-only, values redacted)
  - `fix_skills_disabled.py` — the safe way to set the `skills.disabled` list (config set can't)
  - `github_backup.py` — git-based backup of config / skills / scripts (HermGIT pattern)
  - `profile_gateway_watchdog.py` — auto-heal a profile's gateway when its cron ticker stalls

## Requirements

- Hermes >= 0.12.0 (`hermes version`)
- `git` on PATH (the installer clones with it; any auth your shell already handles works)

## Install

```bash
# From a git URL (recommended — enables `hermes profile update`)
hermes profile install github.com/frgmstr/hermes-manager --alias

# From a local directory (zip → unzip → point at the folder)
hermes profile install /path/to/hermes-manager-dist --alias

# Under a different profile name
hermes profile install github.com/frgmstr/hermes-manager --name my-manager --alias
```

The installer shows a manifest preview (version, author, required env vars), checks which keys you already have set, and writes `.env.EXAMPLE` into the new profile. Nothing is scheduled, nothing is overwritten elsewhere.

## Post-install setup (~5 minutes)

1. **Pick a model provider** — the profile has no model configured by design:

   ```bash
   hermes -p hermes-manager setup
   ```

   …or set one of `NOUS_API_KEY` / `OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY` (or any other provider) in the profile's `.env` and run `hermes -p hermes-manager model`.

2. **Fill in `.env`** (from the profile dir — `hermes -p hermes-manager profile show` prints the path):

   ```bash
   cd ~/.hermes/profiles/hermes-manager      # Windows: %LOCALAPPDATA%\hermes\profiles\hermes-manager
   cp .env.EXAMPLE .env
   # edit with YOUR keys — minimum: one model-provider key
   ```

   Optional but useful: `GITHUB_TOKEN` (backups), `TELEGRAM_BOT_TOKEN` + `TELEGRAM_HOME_CHANNEL` (alert delivery), `FIRECRAWL_API_KEY` (web extraction), `BROWSERBASE_API_KEY` (cloud browser), `LMSTUDIO_API_KEY` (local models).

3. **Chat** — try it:

   ```bash
   hermes -p hermes-manager chat
   ```

   > "Run a system health check" · "Audit my cron jobs" · "Set up a new profile for X" — the skills load on demand.

## Optional: fleet cron jobs (NOT auto-scheduled)

Distributions never auto-schedule cron — enable what you want. The classic fleet jobs, as `no_agent` script jobs (non-empty stdout is the message; silent when healthy; `deliver: telegram` needs the bot env vars, otherwise use `deliver: local`):

```bash
# Daily 12:00 — cron health watchdog
hermes -p hermes-manager cron create "0 12 * * *" --name "Cron health watchdog" \
  --script cron_health_check.py --no-agent --deliver telegram

# Daily 09:00 — skill hygiene audit
hermes -p hermes-manager cron create "0 9 * * *" --name "Skill hygiene audit" \
  --script skill_hygiene_audit.py --no-agent --deliver telegram

# Every 10 min — auto-heal a business profile's gateway (set WATCHDOG_PROFILE)
# e.g. WATCHDOG_PROFILE=my-project  (add to the profile .env)
hermes -p hermes-manager cron create "10m" --name "Gateway watchdog <profile>" \
  --script profile_gateway_watchdog.py --no-agent --deliver telegram
```

## Updating

```bash
hermes profile update hermes-manager                  # new SOUL/skills/scripts
hermes profile update hermes-manager --force-config   # also reset config.yaml to defaults
```

Your memories, sessions, `.env`, and any config.yaml tweaks are **never** touched. `hermes profile info hermes-manager` shows the installed version and env-var requirements.

## Security notes

- Distributions are **unsigned** — review `SOUL.md` and `skills/` before your first run. Same trust level as installing a browser extension; install from people you trust.
- `.env`, `auth.json`, `memories/`, `sessions/`, `state.db`, logs, caches are **hard-excluded** by the installer — you always bring your own credentials, and your conversation history stays local.
- Cron jobs shipped with a distribution are never auto-enabled.

## Customizing

Fork the repo → edit `SOUL.md` (personality/doctrine), `config.yaml` (defaults), add skills under `skills/`, bump `version:` in `distribution.yaml`, commit, tag a release. Installers pull the latest with `hermes profile update`. `local/` in the profile dir is your personal override namespace — updates never touch it.

---

License: MIT. Skills authored by KB + Hermes Agent. Built with Hermes Agent (Nous Research).
