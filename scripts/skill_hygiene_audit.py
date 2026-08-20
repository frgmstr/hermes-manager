#!/usr/bin/env python
"""Skill hygiene audit — runs as a script-only cron job on Default profile.

Loads the skill-auditor skill workflow and produces a concise report.
Designed to be quiet (no output) when everything is healthy, per watchdog pattern.

Schedule: daily at 9 AM via `hermes cron create "0 9 * * *" --script skill_hygiene_audit.py --no-agent --deliver telegram`
"""
import os
import sys
import json
import yaml
import glob
import platform

_default_home = (os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "hermes") if os.name == "nt" else os.path.expanduser("~/.hermes"))
HERMES_HOME = os.environ.get("HERMES_HOME", _default_home)
SKILLS_DIR = os.path.join(HERMES_HOME, "skills")
AGENT_ROOT = os.path.join(HERMES_HOME, "hermes-agent")


def _current_platform():
    sysname = platform.system().lower()
    return {"windows": "windows", "linux": "linux", "darwin": "macos"}.get(sysname, sysname)


def _disabled_skill_names():
    """Read skills.disabled from config.yaml (empty set on any error)."""
    try:
        with open(os.path.join(HERMES_HOME, "config.yaml"), encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        raw = (cfg.get("skills") or {}).get("disabled") or []
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                raw = [raw]
        return {str(s).strip() for s in raw if str(s).strip()}
    except Exception:
        return set()


def _platform_index():
    """Map skill name -> declared platforms (first SKILL.md found wins).

    Covers user-local, bundled, and optional skill roots — usage telemetry
    tracks all of them, so the platform check must see the same scope.
    """
    index = {}
    roots = [SKILLS_DIR, os.path.join(AGENT_ROOT, "skills"), os.path.join(AGENT_ROOT, "optional-skills")]
    for root in roots:
        for path in glob.glob(os.path.join(root, "**", "SKILL.md"), recursive=True):
            if ".archive" in path or ".hub" in path:
                continue
            name = os.path.basename(os.path.dirname(path))
            if name in index:
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    content = f.read()
                if not content.startswith("---"):
                    continue
                end = content.find("\n---\n", 3)
                if end == -1:
                    continue
                fm = yaml.safe_load(content[3:end]) or {}
                plats = fm.get("platforms")
                if isinstance(plats, list) and plats:
                    index[name] = [str(p) for p in plats]
            except Exception:
                continue
    return index


def _is_excluded(name, stats, disabled, plat_index):
    """True if a never-used skill is already handled or inert on this host.

    Flags only *open* issues: skills that are enabled, curator-active, and
    usable on the current platform. A skill that is already disabled,
    already archived, or platform-incompatible (e.g. macos-only on Windows)
    is not an outstanding problem — flagging it again forever is what made
    the daily report re-raise the same 10 names for weeks.
    """
    if name in disabled:
        return True
    if stats.get("state") == "archived":
        return True
    plats = plat_index.get(name)
    if plats is not None and _current_platform() not in plats:
        return True
    return False


def check_description_lengths():
    """Check all SKILL.md files for descriptions >60 chars (breaks system prompt routing)."""
    issues = []
    pattern = os.path.join(SKILLS_DIR, "**", "SKILL.md")

    for path in glob.glob(pattern, recursive=True):
        # Skip archive and hub dirs
        if ".archive" in path or ".hub" in path:
            continue

        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()

            if not content.startswith("---"):
                issues.append(f"{os.path.relpath(path, HERMES_HOME)}: missing frontmatter delimiter")
                continue

            end = content.find("\n---\n", 3)
            if end == -1:
                issues.append(f"{os.path.relpath(path, HERMES_HOME)}: malformed frontmatter (no closing ---)")
                continue

            fm = yaml.safe_load(content[3:end])
            desc = fm.get("description", "")

            if not desc:
                issues.append(f"{os.path.relpath(path, HERMES_HOME)}: missing description field")
            elif len(desc) > 60:
                issues.append(
                    f"{os.path.relpath(path, HERMES_HOME)}: "
                    f"description is {len(desc)} chars (will be truncated to 57+\"...\" — breaks routing)"
                )

        except Exception as e:
            issues.append(f"{os.path.relpath(path, HERMES_HOME)}: error parsing frontmatter — {e}")

    return issues


def check_linked_files():
    """Check that referenced linked files (references/, templates/, scripts/) exist."""
    issues = []

    for path in glob.glob(os.path.join(SKILLS_DIR, "**", "SKILL.md"), recursive=True):
        if ".archive" in path or ".hub" in path:
            continue

        skill_dir = os.path.dirname(path)
        rel_skill = os.path.relpath(skill_dir, HERMES_HOME)

        # Check common subdirectories that SKILL.md files reference
        for subdir in ["references", "templates", "scripts"]:
            sub_path = os.path.join(skill_dir, subdir)
            if not os.path.isdir(sub_path):
                continue  # Not all skills have these — only flag if the file references them

    return issues


def check_pruned_skills():
    """Check for [SKILL_PRUNED] markers in skill content."""
    issues = []

    for path in glob.glob(os.path.join(SKILLS_DIR, "**", "SKILL.md"), recursive=True):
        if ".archive" in path or ".hub" in path:
            continue

        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()

            # Check body (after frontmatter) for actual pruned markers
            end = content.find("\n---\n", 3)
            if end != -1:
                body = content[end + 5:]
                # A real [SKILL_PRUNED] marker replaces the skill's actual content — it appears
                # as a standalone line (not inside backticks, not within sentences). We check for
                # lines that are ONLY "[SKILL_PRUNED]" with optional whitespace.
                pruned_lines = [line.strip() for line in body.split('\n') if line.strip() == '[SKILL_PRUNED]']
                if pruned_lines:
                    issues.append(
                        f"{os.path.relpath(path, HERMES_HOME)}: contains [SKILL_PRUNED] as standalone content — "
                        "content lost in compression, needs reload"
                    )
        except Exception as e:
            issues.append(f"{os.path.relpath(path, HERMES_HOME)}: error checking content — {e}")

    return issues


def check_stale_skills():
    """Check curator usage telemetry for stale/unused skills.

    Only flags *open* issues: never-used skills that are still enabled, not
    archived, and usable on the current platform. Already-handled skills
    (disabled in config, already archived, or platform-incompatible) are
    excluded so the daily report doesn't re-raise the same names forever.
    """
    issues = []
    usage_path = os.path.join(SKILLS_DIR, ".usage.json")

    try:
        with open(usage_path) as f:
            usage = json.load(f)

        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=60)

        disabled = _disabled_skill_names()
        plat_index = _platform_index()

        for skill_name, stats in usage.items():
            if not isinstance(stats, dict):
                continue

            use_count = stats.get("use_count", 0)
            state = stats.get("state", "unknown")
            last_active_str = stats.get("last_activity_at", "")

            if _is_excluded(skill_name, stats, disabled, plat_index):
                continue

            # Never used and not pinned — candidate for pruning
            if use_count == 0 and state != "pinned":
                issues.append(
                    f"Skill '{skill_name}': never used, not pinned — prune candidate"
                )
            elif last_active_str:
                try:
                    last_active = datetime.fromisoformat(last_active_str.replace("Z", "+00:00"))
                    if last_active < cutoff and state != "pinned":
                        issues.append(
                            f"Skill '{skill_name}': stale (last active {last_active.strftime('%Y-%m-%d')}, "
                            f"{use_count} uses, state={state})"
                        )
                except (ValueError, TypeError):
                    pass  # Skip if date parsing fails

    except FileNotFoundError:
        issues.append("Curator usage telemetry (.usage.json) not found — curator may be disabled")
    except Exception as e:
        issues.append(f"Error reading curator telemetry: {e}")

    return issues


def main():
    all_issues = []

    # 1. Description length violations (critical — breaks routing)
    desc_issues = check_description_lengths()
    all_issues.extend(desc_issues)

    # 2. Pruned skill content (content lost in compression)
    pruned_issues = check_pruned_skills()
    all_issues.extend(pruned_issues)

    # 3. Stale/unused skills from curator telemetry (only open, not-handled)
    stale_issues = check_stale_skills()
    all_issues.extend(stale_issues)
    if len(stale_issues) > 25:
        all_issues.append(f"… and {len(stale_issues) - 25} more stale-skill candidates (full list: hermes curator usage)")

    # Report (watchdog pattern: only output if there are issues)
    if all_issues:
        print("⚠️ SKILL HYGIENE AUDIT — ISSUES FOUND")
        for issue in all_issues:
            print(f"  • {issue}")
    else:
        # Silent when healthy (no delivery = nothing sent to user)
        pass


if __name__ == "__main__":
    main()
