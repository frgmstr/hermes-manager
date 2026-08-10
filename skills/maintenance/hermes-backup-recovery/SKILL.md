---
name: hermes-backup-recovery
description: Back up Hermes config, skills, and state to Git.
---

# Hermes Backup & Recovery

This skill covers the process of implementing and maintaining automated remote backups of the Hermes Agent's internal state to ensure persistence across machine migrations or system failures.

## Trigger Conditions
- User asks to "backup hermes", "sync config to github", or reports that a backup cron is no longer running.
- Need to migrate Hermes profiles/skills/memories to a new installation.

## Workflow

### 1. Identify Critical State
The following paths in `AppData/Local/hermes` (Windows) are essential for a full recovery:
- `config.yaml`: Global settings and provider configs.
- `profiles/`: User profiles, including custom skills and memories.
- `skills/`: All installed and agent-created skills.
- `memories/`: Persistent memory stores.
- `cron/`: Scheduled task definitions.
- `SOUL.md`: Core agent identity/instructions if present.

### 2. Implementation Strategy (Git-based)
The most reliable method is a dedicated Python script run via `cronjob`:
1. **Authentication**: Use a Personal Access Token (PAT) embedded in the Git URL (`https://<token>@github.com/...`) for seamless non-interactive authentication.
2. **Local Staging**: Clone the remote repo to a temporary local directory.
3. **Sync**: Overwrite files in the staging directory with current state from `AppData/Local/hermes`.
4. **Commit & Push**: Perform a git add, commit (with timestamp), and push.

### 3. Automation
Schedule the script using the `cronjob` tool (e.g., `every 24h`) to ensure backups remain current without manual intervention.

## Pitfalls & Troubleshooting

### Git Author Identity
**Problem**: The backup script fails during `git commit` with "Author identity unknown".
**Fix**: Ensure global git config is set for the environment:
```bash
git config --global user.email "user@example.com"
git config --global user.name "Username"
```

### Private Repo Access
**Problem**: `web_extract` or standard `curl` calls return 404 for private repos.
**Fix**: Use the GitHub API with an Authorization header (`-H "Authorization: token <token>"`) to verify repo existence and status.

### File Locking
**Problem**: Some files (like `.db` files) may be locked by the running Hermes process.
**Fix**: Prefer backing up configuration files, scripts, and markdown over active SQLite databases if locking occurs; alternatively, use a tool that can handle shadow copies or read-only streams.

### Silent Push Failures Despite `last_status=ok`
**Problem**: The cron job reports success (`last_status: ok`) even though pushes to GitHub have been failing for days. Root cause: the script's error handler prints errors but returns `None` instead of aborting — so the process exits 0 and cron records a false "ok".
**Fix**: Change `run()` to call `sys.exit(1)` on command failure instead of returning `None`. This ensures failed pushes propagate as actual error status in the cron job's execution log.

### Oversized Files Exceeding GitHub's 100 MB Limit
**Problem**: Push fails with pre-receive hook rejection because files like `*state.db.malformed-backup-*` (~137 MB each) or `state-snapshots/` directories are copied into the backup repo, exceeding GitHub's size limit.
**Fix**: Add an IGNORE set to your file copy logic and a `.gitignore` entry for these patterns:
```python
IGNORE = {
    '*.db-shm', '*.db-wal', '*.lock', '*.db-journal',
    '*state.db.malformed-backup*',  # Large recovery artifacts (100MB+) that exceed GitHub limits
    'state-snapshots/',              # Can be multi-GB
}
```

### Token Not Available in Cron-Run Scripts
**Problem**: When a cron job runs as `no_agent=true` with `--script`, the Hermes runtime doesn't inject environment variables from `.env`. The script can't find `GITHUB_TOKEN` and fails silently.
**Fix**: Add a `_load_env()` helper that checks multiple sources in order: env var → `.env` in scripts dir → backup repo's `.env` → Hermes home `.env`:
```python
def _load_env():
    token = os.environ.get("GITHUB_TOKEN", "")
    if token: return token
    for env_path in [os.path.join(os.path.dirname(__file__), ".env"),
                     os.path.expanduser("~/hermes-backup-local/.env"),
                     os.path.expanduser("~/.hermes/.env")]:
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("GITHUB_TOKEN=") and not line.startswith("#"):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""
```

### Stale Commented-Out Token Lines
**Problem**: After rotating a token, the old `# GITHUB_TOKEN=ghp_xx...` comment remains in `.env`, causing confusion and potential accidental use of stale values.
**Fix**: Remove old commented lines: `sed -i '/^# GITHUB_TOKEN=/d' ~/.hermes/.env`

### Git Remote URL Not Updated After Token Rotation
**Problem**: Even after updating the token, pushes fail because the local repo's remote URL still contains the old (now-revoked) token.
**Fix**: Have the script set the remote URL with fresh credentials on each run: `git remote set-url origin "https://<TOKEN>@github.com/..."`.

## Verification
- Manually execute the backup script once to ensure the "Push" completes.
- Check the remote repository (via API or Web) for the latest commit timestamp.
- Verify the `cronjob` is listed and active using `cronjob(action='list')`.

## Templates & Scripts
- See `templates/github_backup_script.py` for a reference implementation of the sync logic.
