#!/usr/bin/env python3
"""Verify a Hermes profile distribution before publishing.

Usage:
    python verify_distribution.py --dist <dir> [--patterns '["term1","term2"]'] [--install]

    --dist <dir>      path to the distribution directory (required)
    --patterns JSON   list of personal terms to scan for (username, business
                      names, model ids, custom ports, ...). Default: [] — pass
                      your own; the generic secret/state checks always run.
    --install         also run a local test install (hermes profile install
                      --name <name>-test), verify, and delete the profile.

Checks (exit non-zero if any fail):
  1. distribution.yaml parses; name/version present; every distribution_owned
     path exists on disk.
  2. No hard-excluded paths shipped in the tree (auth.json, .env, state.db*,
     memories/, sessions/, logs/, caches, local/, ...) — the installer strips
     these on the recipient side, but they must not be in the repo either.
  3. Personal-pattern scan across .md/.py/.yaml/.yml/.json (skips .git/).
  4. Every shipped .py compiles (pycache redirected outside the tree).
  5. Git hygiene: clean tree, tags listed (if a git repo).
  6. Optional: local test install + skill index check + cleanup.

Environment: HERMES_HOME locates the hermes CLI (portable fallback to
%LOCALAPPDATA%\\hermes or ~/.hermes). On Windows pass --dist as a Windows-style
path (C:/...) — the installer rejects MSYS /c/... paths.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Mirrors hermes_cli/profile_distribution.py USER_OWNED_EXCLUDE (installer hard-excludes)
USER_OWNED_EXCLUDE = {
    "auth.json", ".env", "state.db", "state.db-shm", "state.db-wal",
    "hermes_state.db", "response_store.db", "response_store.db-shm",
    "response_store.db-wal", "gateway.pid", "gateway_state.json", "processes.json",
    "auth.lock", "active_profile", ".update_check", "errors.log", ".hermes_history",
    "memories", "sessions", "logs", "plans", "workspace", "home", "image_cache",
    "audio_cache", "document_cache", "browser_screenshots", "checkpoints",
    "sandboxes", "backups", "cache", "hermes-agent", ".worktrees", "profiles",
    "bin", "node_modules", "local",
}
SCAN_EXTS = {".md", ".py", ".yaml", ".yml", ".json"}


def _hermes_home() -> Path:
    env = os.environ.get("HERMES_HOME")
    if env:
        return Path(env)
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "hermes"
    return Path.home() / ".hermes"


def _hermes_bin(home: Path) -> str:
    exe = shutil.which("hermes")
    if exe:
        return exe
    script_dir = "Scripts" if os.name == "nt" else "bin"
    name = "hermes.exe" if os.name == "nt" else "hermes"
    candidate = home / "hermes-agent" / "venv" / script_dir / name
    if candidate.exists():
        return str(candidate)
    return "hermes"  # let PATH resolve it; errors will surface in the install test


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dist", required=True, help="distribution directory")
    ap.add_argument("--patterns", default="[]", help='JSON list of personal terms')
    ap.add_argument("--install", action="store_true", help="run local test install")
    args = ap.parse_args()

    dist = Path(args.dist)
    if not dist.is_dir():
        print(f"FAIL  --dist is not a directory: {dist}")
        return 1
    try:
        patterns = json.loads(args.patterns)
    except json.JSONDecodeError:
        print(f"FAIL  --patterns is not valid JSON: {args.patterns}")
        return 1

    failures = 0

    def check(name, ok, detail=""):
        nonlocal failures
        if not ok:
            failures += 1
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))

    # 1. manifest
    try:
        import yaml
        manifest = yaml.safe_load((dist / "distribution.yaml").read_text(encoding="utf-8"))
        check("manifest parses", True)
        check("manifest name/version", bool(manifest.get("name")) and bool(manifest.get("version")))
        owned = manifest.get("distribution_owned") or []
        missing = [p for p in owned if not (dist / p).exists()]
        check("every distribution_owned path exists", not missing, f"missing={missing}")
    except ImportError:
        check("manifest parses", False, "pyyaml not installed")
    except Exception as e:
        check("manifest parses", False, str(e))

    # 2. no hard-excluded paths in the tree
    bad = []
    for p in dist.rglob("*"):
        if ".git" in p.parts:
            continue
        if p.name.lower() in USER_OWNED_EXCLUDE:
            bad.append(str(p.relative_to(dist)))
    check("no hard-excluded paths shipped", not bad, f"{bad[:5]}")

    # 3. personal-pattern scan
    if patterns:
        pat = re.compile("|".join(re.escape(x) for x in patterns), re.I)
        hits = []
        for p in dist.rglob("*"):
            if p.is_file() and p.suffix in SCAN_EXTS and ".git" not in p.parts:
                try:
                    txt = p.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                for ln, line in enumerate(txt.splitlines(), 1):
                    if pat.search(line):
                        hits.append(f"{p.relative_to(dist)}:{ln}")
        check(f"personal-pattern scan ({len(patterns)} terms)", not hits, f"{len(hits)} hits: {hits[:5]}")
    else:
        print("SKIP  personal-pattern scan (no --patterns given)")

    # 4. compile all python
    pycache = Path(tempfile.gettempdir()) / "hermes-verify-pyc"
    pycache.mkdir(exist_ok=True)
    env = {**os.environ, "PYTHONPYCACHEPREFIX": str(pycache)}
    compile_fail = []
    for p in [*dist.glob("scripts/*.py"), *dist.glob("skills/**/scripts/*.py"), *dist.glob("skills/**/templates/*.py")]:
        r = subprocess.run([sys.executable, "-m", "py_compile", str(p)], capture_output=True, text=True, env=env)
        if r.returncode != 0:
            compile_fail.append(f"{p.relative_to(dist)}: {r.stderr.strip()[:100]}")
    check("all shipped .py compile", not compile_fail, f"{len(compile_fail)} failed")

    # 5. git hygiene
    if (dist / ".git").is_dir():
        r = subprocess.run(["git", "-C", str(dist), "status", "--porcelain"], capture_output=True, text=True)
        check("git tree clean", r.stdout.strip() == "")
        r = subprocess.run(["git", "-C", str(dist), "tag", "-l"], capture_output=True, text=True)
        check("git tags present", bool(r.stdout.strip()), r.stdout.strip().replace("\n", ","))
    else:
        print("SKIP  git checks (not a git repo)")

    # 6. optional local test install
    if args.install:
        home = _hermes_home()
        bin_ = _hermes_bin(home)
        name = manifest.get("name") if "manifest" in dir() and manifest else "agent"
        test_name = f"{name}-test"
        r = subprocess.run([bin_, "profile", "install", str(dist), "--name", test_name, "-y"],
                           capture_output=True, text=True, timeout=300)
        ok = r.returncode == 0 and "Installed" in (r.stdout + r.stderr)
        check(f"local test install ({test_name})", ok, (r.stdout + r.stderr)[-160:])
        if ok:
            prof = home / "profiles" / test_name
            check("profile has SOUL.md", (prof / "SOUL.md").exists())
            check("profile has NO .env", not (prof / ".env").exists())
            check(".env.EXAMPLE generated", (prof / ".env.EXAMPLE").exists())
            r2 = subprocess.run([bin_, "-p", test_name, "skills", "list"], capture_output=True, text=True, timeout=180)
            check("profile skills index", r2.returncode == 0, (r2.stdout + r2.stderr)[-120:])
            subprocess.run([bin_, "profile", "delete", test_name, "--yes"], capture_output=True, text=True, timeout=120)
            check("test profile cleaned up", not prof.exists())
    else:
        print("SKIP  local test install (pass --install)")

    print(f"\n{'=' * 60}\n{'FAILURES' if failures else 'ALL CHECKS PASSED'} ({failures} failed)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
