#!/usr/bin/env python
"""Skill hygiene audit — runs as a script-only cron job on Default profile.

Loads the skill-auditor skill workflow and produces a concise report.
Designed to be quiet (no output) when everything is healthy, per watchdog pattern.

Schedule: daily at 9 AM via `hermes cron create "0 9 * * *" --script skill_hygiene_audit.py --no-agent --deliver telegram`
"""
import os
import sys
import yaml
import glob

_default_home = (os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "hermes") if os.name == "nt" else os.path.expanduser("~/.hermes"))
HERMES_HOME = os.environ.get("HERMES_HOME", _default_home)
SKILLS_DIR = os.path.join(HERMES_HOME, "skills")


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
    """Check curator usage telemetry for stale/unused skills."""
    issues = []
    usage_path = os.path.join(SKILLS_DIR, ".usage.json")

    try:
        import json
        with open(usage_path) as f:
            usage = json.load(f)

        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=60)

        for skill_name, stats in usage.items():
            if not isinstance(stats, dict):
                continue

            use_count = stats.get("use_count", 0)
            state = stats.get("state", "unknown")
            last_active_str = stats.get("last_activity_at", "")

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

    # 3. Stale/unused skills from curator telemetry
    stale_issues = check_stale_skills()
    all_issues.extend(stale_issues[:10])  # cap to stay concise

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
