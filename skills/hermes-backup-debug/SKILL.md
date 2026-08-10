---
name: hermes-backup-debug
description: HermGIT BU cron push failures — diagnose and repair.
---

# HermGIT Backup Debugging & Repair

## Trigger Conditions
- HermGIT BU cron job hasn't updated GitHub for 2+ days despite `last_status=ok`
- Cron runs but pushes silently fail with oversized-file errors
- Token in `.env` is stale/expired and needs rotation

## Quick Diagnosis Checklist (run in order)

1. **Check if remote repo exists**  
   ```bash
   curl -sI https://github.com/frgmstr/hermes-backup | head -1
   # 404 = repo deleted/never existed; 200 = OK
   ```

2. **Verify token validity** (mask before sharing!)  
   ```bash
   TOKEN=$(grep '^GITHUB_TOKEN=' ~/.hermes/.env | cut -d= -f2)
   curl -s -H "Authorization: token $TOKEN" https://api.github.com/user | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('login','❌ Bad credentials'))"
   ```

3. **Check for oversized files in the backup repo**  
   ```bash
   cd ~/hermes-backup-local && git status --porcelain | grep 'state.db.malformed' || echo "clean"
   find ~/AppData/Local/hermes/profiles -name '*state.db.malformed-backup*' 2>/dev/null
   ```

4. **Test the script end-to-end** (dry run first)  
   ```bash
   python ~/.hermes/scripts/github_backup.py 2>&1; echo "EXIT: $?"
   # Should print "Backup completed successfully!" and exit 0
   ```

## Repair Steps

### A. Remove oversized files from git history
```bash
cd ~/hermes-backup-local
# If filter-repo isn't installed: pip install git-filter-repo
git filter-repo --invert-paths --path-glob '*state.db.malformed-backup*' --force
git push origin main --force
```

### B. Clean up source profile directories
```bash
find ~/.hermes/profiles -name '*state.db.malformed-backup*' -delete 2>/dev/null
```

### C. Rotate token (if stale)
1. Generate new classic PAT at https://github.com/settings/tokens
2. Store via Hermes CLI: `hermes config set GITHUB_TOKEN ghp_xxx`
3. Remove any stale commented-out lines from `.env` using `sed -i '/^# GITHUB_TOKEN=ghp_xx/d' ~/.hermes/.env`

### D. Patch the script (key fixes applied)
- **`run()`**: Changed to `sys.exit(1)` on failure instead of returning `None` — ensures cron reports actual error status
- **`_copy_tree_safe`**: Added `*state.db.malformed-backup*` and `state-snapshots/` to IGNORE set
- **`_ensure_gitignore()`**: New function that auto-appends large-file exclusions each run
- **`_load_env()`**: Loads token from env var → `.env` in scripts dir → backup repo `.env` → Hermes home `.env`
- **Remote URL**: Script now sets `git remote set-url origin "https://TOKEN@github.com/..."` on each run so push works even if credentials changed

## Verification Evidence (last verified: 2026-08-04)
```bash
# End-to-end test — script exits 0 and commit appears on GitHub
python ~/.hermes/scripts/github_backup.py → "Backup completed successfully!" EXIT: 0
curl -s https://api.github.com/repos/frgmstr/hermes-backup/commits | head shows latest backup commit ✅
```

## Consolidation Note (2026-08-04)
Previously had THREE cron health jobs: two watchdogs (noon + 9am, same script) and one audit job. Consolidated to ONE — the `Cron health watchdog` running at noon via `cron_health_check.py`. Removed `Daily Cron Health Watchdog` and `Cron health audit (auto)` plus its now-unused `cron_health_audit.py` script.
- **`_load_env()` must be defined before TOKEN/AUTH_URL at module level** — the function reads from multiple `.env` files because cron jobs run as scripts without Hermes' env injection
- **Stale commented-out token lines in `.env`** cause confusion — always remove old `# GITHUB_TOKEN=...` comments after rotation
- **`git reset --hard` requires user approval** on this system (protected operation)
