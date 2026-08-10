#!/usr/bin/env python3
"""
Automated model-swap script for Hermes Agent.

Usage:
    python update_model.py --old-model "<old-model>" --new-model "<new-model>" [--dry-run]

Scans all config.yaml, jobs.json, and SOUL.md files under the Hermes home directory
and replaces old model references with new ones. Does NOT touch skill index cache or .env secrets.
"""

import argparse
import json
import os
import re
from pathlib import Path

_default_home = (Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "hermes") if os.name == "nt" else (Path.home() / ".hermes")
HERMES_HOME = Path(os.environ.get("HERMES_HOME") or _default_home)

# Files to scan for model references (relative to HERMES_HOME)
SCAN_PATHS = [
    # Default profile config + crons
    ("config.yaml", True),  # yaml
    ("cron/jobs.json", False),  # json
    # Any per-profile configs / crons / SOUL docs under profiles/ (globs)
    ("profiles/*/config.yaml", True),
    ("profiles/*/cron/jobs.json", False),
    ("profiles/*/SOUL.md", "md"),
]

# Files to SKIP entirely (never modify these)
SKIP_PATHS = {
    # Skill index cache - huge and auto-generated
    HERMES_HOME / "skills" / ".hub" / "index-cache",
}


def should_skip(path: Path) -> bool:
    for skip in SKIP_PATHS:
        if str(skip) in str(path):
            return True
    return False


def update_yaml_file(filepath: Path, old_model: str, new_model: str, dry_run: bool) -> list[str]:
    """Update model references in a YAML config file."""
    changes = []
    try:
        content = filepath.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [f"  ⚠️  {filepath.name}: not found"]

    # Pattern matches common yaml model fields
    patterns = [
        (rf'(\bmodel:\s*){re.escape(old_model)}', f'\\g<1>{new_model}'),
        (rf'(\bdefault_model:\s*){re.escape(old_model)}', f'\\g<1>{new_model}'),
        (rf'(\bmodels:.*\n\s*)(- {re.escape(old_model)})', f'\\g<1>- {new_model}'),  # list item under models:
    ]

    for pattern, replacement in patterns:
        matches = re.findall(pattern, content)
        if matches:
            new_content = re.sub(pattern, replacement, content)
            if dry_run:
                changes.append(f"  📄 {filepath.relative_to(HERMES_HOME)}: would replace '{old_model}' → '{new_model}' ({len(matches)} match(es))")
            else:
                filepath.write_text(new_content, encoding="utf-8")
                changes.append(f"  ✅ {filepath.relative_to(HERMES_HOME)}: replaced '{old_model}' → '{new_model}' ({len(matches)} match(es))")

    return changes


def update_json_file(filepath: Path, old_model: str, new_model: str, dry_run: bool) -> list[str]:
    """Update model references in a JSON file (cron jobs.json)."""
    changes = []
    try:
        content = filepath.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [f"  ⚠️  {filepath.name}: not found"]

    # Simple string replacement for model fields in JSON
    if old_model not in content:
        return []

    new_content = content.replace(old_model, new_model)
    count = content.count(old_model)

    if dry_run:
        changes.append(f"  📄 {filepath.relative_to(HERMES_HOME)}: would replace '{old_model}' → '{new_model}' ({count} match(es))")
    else:
        filepath.write_text(new_content, encoding="utf-8")
        changes.append(f"  ✅ {filepath.relative_to(HERMES_HOME)}: replaced '{old_model}' → '{new_model}' ({count} match(es))")

    return changes


def update_md_file(filepath: Path, old_model: str, new_model: str, dry_run: bool) -> list[str]:
    """Update model references in markdown documentation files."""
    changes = []
    try:
        content = filepath.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [f"  ⚠️  {filepath.name}: not found"]

    if old_model not in content:
        return []

    new_content = content.replace(old_model, new_model)
    count = content.count(old_model)

    if dry_run:
        changes.append(f"  📄 {filepath.relative_to(HERMES_HOME)}: would replace '{old_model}' → '{new_model}' ({count} match(es))")
    else:
        filepath.write_text(new_content, encoding="utf-8")
        changes.append(f"  ✅ {filepath.relative_to(HERMES_HOME)}: replaced '{old_model}' → '{new_model}' ({count} match(es))")

    return changes


def main():
    parser = argparse.ArgumentParser(description="Swap model references across all Hermes config files.")
    parser.add_argument("--old-model", required=True, help="Current model name to replace")
    parser.add_argument("--new-model", required=True, help="New model name to use")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without modifying files")
    args = parser.parse_args()

    print(f"{'DRY RUN: ' if args.dry_run else ''}Swapping '{args.old_model}' → '{args.new_model}' in Hermes config...")
    print(f"  Scanning under: {HERMES_HOME}\n")

    all_changes = []

    # Expand glob patterns first, then process each candidate file
    candidates = []
    for rel_path, file_type in SCAN_PATHS:
        if any(ch in rel_path for ch in "*?["):
            candidates.extend((p, file_type) for p in HERMES_HOME.glob(rel_path))
        else:
            candidates.append((HERMES_HOME / rel_path, file_type))

    for filepath, file_type in candidates:
        if should_skip(filepath):
            continue

        if not filepath.exists():
            all_changes.append(f"  ⚠️  {filepath.relative_to(HERMES_HOME)}: file not found")
            continue

        if isinstance(file_type, bool) and file_type:
            # YAML
            all_changes.extend(update_yaml_file(filepath, args.old_model, args.new_model, args.dry_run))
        elif filepath.suffix == ".json":
            all_changes.extend(update_json_file(filepath, args.old_model, args.new_model, args.dry_run))
        elif filepath.suffix == ".md":
            all_changes.extend(update_md_file(filepath, args.old_model, args.new_model, args.dry_run))

    # Also do a broad scan for any stale references we might have missed (pure Python, no grep)
    print("\n  Scanning for any remaining references...\n")

    def find_stale_references(search_root: Path, search_term: str, extensions: list[str]) -> list[Path]:
        """Find files containing the old model name using pure Python."""
        found = []
        for ext in extensions:
            for filepath in search_root.rglob(f"*{ext}"):
                if should_skip(filepath):
                    continue
                try:
                    content = filepath.read_text(encoding="utf-8", errors="ignore")
                    if search_term in content:
                        found.append(filepath)
                except (PermissionError, OSError):
                    continue
        return found

    remaining = find_stale_references(HERMES_HOME, args.old_model, [".yaml", ".json"])

    print(f"\n{'='*60}")
    if all_changes:
        print("Changes made:")
        for c in all_changes:
            print(c)
    else:
        print("No changes needed — model references already updated.")

    if remaining:
        print(f"\n⚠️  {len(remaining)} file(s) still reference '{args.old_model}':")
        for r in remaining[:10]:
            print(f"   - {r}")
        if len(remaining) > 10:
            print(f"   ... and {len(remaining)-10} more. Check these manually.")
    else:
        print("\n✅ No remaining references found in config files!")

    # Remind about skill index cache (which we skip but should be aware of) - pure Python check
    cache_dir = HERMES_HOME / "skills" / ".hub"
    if cache_dir.exists():
        cache_remaining = find_stale_references(cache_dir, args.old_model, [".json"])
        if cache_remaining:
            print(f"\nℹ️  Found references in skill index cache (auto-generated, safe to ignore): {cache_remaining[0].relative_to(HERMES_HOME)}")

    # Post-change reminder
    if not args.dry_run and all_changes:
        print("\n" + "="*60)
        print("⚠️  ACTION REQUIRED:")
        print(f"   1. Restart Hermes to pick up config changes")
        print(f"   2. Ensure '{args.new_model}' is loaded in LM Studio on all profile endpoints")
        print(f"   3. Run one cron job: hermes cron run <job_id> to verify")
        # Check if gateway service exists and remind about restart
        gateway_state = HERMES_HOME / "gateway_state.json"
        if gateway_state.exists():
            try:
                gw_data = json.loads(gateway_state.read_text(encoding="utf-8"))
                platforms = list(gw_data.get("platforms", {}).keys())
                if platforms:
                    print(f"   4. Restart Hermes Gateway (connected to {', '.join(platforms)}): hermes gateway restart")
            except (json.JSONDecodeError, OSError):
                pass


if __name__ == "__main__":
    main()
