# Checking Distribution Versions

## Verify Your Installation is Current

### Check Profile Version
```bash
hermes profile info hermes-manager
# Shows: version, source (local/git), env requirements
```

### Check Upstream Tags (works for any distribution, pinned refs not supported yet)
Installed distributions track the source repo's default branch on `hermes profile update` — there is no ref pinning yet. Compare what you have against what upstream published:

```bash
# Version you installed + recorded source URL
hermes profile info <name> | grep -E "Version|Source"

# Latest tags upstream (no clone needed)
git ls-remote --tags "$(hermes profile info <name> | awk '/^Source:/{print $2}')" | tail -5

# GitHub API alternative
curl -s https://api.github.com/repos/<owner>/<repo>/git/refs/tags | jq -r '.[].ref' | tail -5
```

If the newest upstream tag is ahead of your Version, run `hermes profile update <name>` to pull it. Hold off until you're ready — updates always move to latest, so check first and update deliberately.

## Update a Git-Based Distribution

```bash
# Get updates from remote
hermes profile update hermes-manager

# Force config reset to the distribution's defaults (config.yaml is otherwise preserved)
hermes profile update hermes-manager --force-config
```

Flags are `--force-config` and `-y/--yes` only — there is no `--dry-run` (a dry-run flag was considered upstream but hasn't shipped; compare versions manually with `profile info` + `git ls-remote`).

**Update notes:**
- `.env`, memories, sessions, logs, caches, `local/` are **never touched**; cron jobs already scheduled under your profile keep running — the update replaces distribution-owned files (`SOUL.md`, `config.yaml` unless preserved, `skills/`, `cron/`, `mcp.json`; also `scripts/` if it's declared in `distribution_owned`)
- After a major version update, run `hermes doctor` to verify everything works

## Profile vs Hermes Core Updates

- **Profile updates**: `hermes profile update <name>` — updates the profile's skills/config
- **Hermes core updates**: `hermes update` — updates the Hermes Agent itself

Both should be checked if things seem "stale".