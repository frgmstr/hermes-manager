import os
import shutil
import subprocess
import sys
from datetime import datetime

def _default_home():
    return (os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "hermes")
            if os.name == "nt" else os.path.expanduser("~/.hermes"))


def _load_env():
    """Load GITHUB_TOKEN from environment or .env files."""
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        return token
    # Try loading from .env in script dir, local repo dir, and Hermes home
    hermes_home = os.environ.get("HERMES_HOME", _default_home())
    for env_path in [os.path.join(os.path.dirname(__file__), ".env"),
                     os.path.join(LOCAL_REPO_DIR := os.path.expanduser(
                         os.environ.get("HERMES_BACKUP_LOCAL_DIR", "~/hermes-backup-local")), ".env"),
                     os.path.join(hermes_home, ".env")]:
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("GITHUB_TOKEN=") and not line.startswith("#"):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


# Configuration — all overridable via env for portability across machines.
# HERMES_HOME / HERMES_BACKUP_REPO / HERMES_BACKUP_LOCAL_DIR / HERMES_BACKUP_SOURCE
HERMES_HOME = os.environ.get("HERMES_HOME", _default_home())
REPO_URL = os.environ.get("HERMES_BACKUP_REPO", "https://github.com/<your-github-user>/hermes-backup")
TOKEN = _load_env() or os.environ.get("GITHUB_TOKEN", "") or "«redacted:ghp_…»"
AUTH_URL = REPO_URL.replace("https://", f"https://{TOKEN}@") if TOKEN and not TOKEN.startswith("«") else REPO_URL
LOCAL_REPO_DIR = os.path.expanduser(os.environ.get("HERMES_BACKUP_LOCAL_DIR", "~/hermes-backup-local"))
SOURCE_DIR = os.path.expanduser(os.environ.get("HERMES_BACKUP_SOURCE", HERMES_HOME))

# Files and directories to backup
INCLUDE_PATTERNS = [
    "config.yaml",
    "auth.json",
    "profiles",
    "skills",
    "memories",
    "cron",
    "hooks",
    "sessions",
    "kanban",
    "SOUL.md",
    "scripts",
]

def run(cmd, cwd=None):
    """Run a shell command. Returns stdout on success; exits with error code on failure."""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
    if result.returncode != 0:
        print(f"Error running command: {cmd}")
        print(f"Stdout: {result.stdout}")
        print(f"Stderr: {result.stderr}")
        sys.exit(1)  # Abort so cron job reports failure status
    return result.stdout

def _copy_tree_safe(src, dst):
    """Recursively copy src into dst, creating dirs as needed and skipping locked/large files."""
    IGNORE = {
        '*.db-shm', '*.db-wal', '*.lock', '*.db-journal',
        '*state.db.malformed-backup*',  # Large recovery artifacts (100MB+) that exceed GitHub limits
        'state-snapshots/',              # Can be multi-GB
    }
    import fnmatch
    os.makedirs(dst, exist_ok=True)
    for entry in os.scandir(src):
        s = os.path.join(src, entry.name)
        d = os.path.join(dst, entry.name)
        # Skip ignored patterns
        if any(fnmatch.fnmatch(entry.name, pat.rstrip('/')) or fnmatch.fnmatch(entry.name + '/', pat) for pat in IGNORE):
            continue
        if entry.is_dir():
            _copy_tree_safe(s, d)
        else:
            try:
                shutil.copy2(s, d)
            except PermissionError:
                pass  # Skip files locked by other processes


def _ensure_gitignore(path, additions):
    """Append lines to .gitignore if not already present."""
    existing = set()
    if os.path.exists(path):
        with open(path, 'r') as f:
            existing = {line.strip() for line in f if line.strip()}
    new_lines = [a for a in additions if a not in existing]
    if new_lines:
        with open(path, 'a') as f:
            if os.path.getsize(path) > 0 and not open(path).read().endswith('\n'):
                f.write('\n')
            f.write('\n'.join(new_lines) + '\n')
        print(f"Updated .gitignore with {len(new_lines)} new entries")

def main():
    # 1. Clone or update local repo
    if not os.path.exists(LOCAL_REPO_DIR):
        print("Cloning repository...")
        run(f"git clone {AUTH_URL} {LOCAL_REPO_DIR}")
    else:
        print("Updating local repository...")
        # Set remote URL with token for authenticated pull/push
        run(f'git remote set-url origin "{AUTH_URL}"', cwd=LOCAL_REPO_DIR)
        run("git pull", cwd=LOCAL_REPO_DIR)

    # Ensure .gitignore has large-file exclusions (prevents GitHub push rejection)
    gitignore_path = os.path.join(LOCAL_REPO_DIR, ".gitignore")
    GI_ADDITIONS = [
        "# Malformed backup files from state.db recovery attempts",
        "*state.db.malformed-backup*",
        "state-snapshots/",
    ]
    _ensure_gitignore(gitignore_path, GI_ADDITIONS)

    # 2. Copy files from source to repo
    print("Copying backup files...")
    for pattern in INCLUDE_PATTERNS:
        src = os.path.join(SOURCE_DIR, pattern)
        dst = os.path.join(LOCAL_REPO_DIR, pattern)
        if not os.path.exists(src):
            print(f"Skipping {pattern}: source not found")
            continue

        if os.path.isdir(src):
            # Copy into existing directory, skipping files that can't be overwritten
            _copy_tree_safe(src, dst)
        else:
            shutil.copy2(src, dst)

    # 3. Git commit and push
    print("Pushing to GitHub...")
    run("git add .", cwd=LOCAL_REPO_DIR)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    commit_msg = f"Backup - {timestamp}"
    
    # Check if there are changes to commit
    status = run("git status --porcelain", cwd=LOCAL_REPO_DIR)
    if not status or status.strip() == "":
        print("No changes to backup.")
        return

    run(f'git -c user.name="Hermes Backup" -c user.email="backup@hermes" commit -m "{commit_msg}"', cwd=LOCAL_REPO_DIR)
    run("git push", cwd=LOCAL_REPO_DIR)
    print("Backup completed successfully!")

if __name__ == "__main__":
    main()
