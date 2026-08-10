---
name: skill-auditor
description: "Use when auditing Hermes skills for broken references."
version: 1.0.0
author: Hermes Agent + KB
license: MIT
platforms: [linux, macos, windows]
tags: [hermes, skills, maintenance, audit]
---

# Skill Auditor / Skill Maintenance

## Overview

Cross-profile or Default-scoped scan for broken `skill_view` references, stale content, name collisions, missing supporting files, and merge candidates. Hermes skills are procedural memory — if they're broken or duplicated, the agent's reliability degrades silently. This skill codifies a regular audit workflow to catch those issues before they cause failures.

## When to Use

- User asks "audit my skills" or "check for broken skill references"
- Before major config/model changes that might affect skill behavior
- Periodic maintenance (monthly recommended)
- Investigating why `skill_view(name)` returns `[SKILL_PRUNED]` or errors
- After installing/updating skills — verify no collisions or missing files

## What to Audit

| Check | Method | Failure Signal |
|---|---|---|
| **Broken skill_view references** | Load each skill via `skill_view`, check for pruned/missing content | `[SKILL_PRUNED]` in body, error from skill_view |
| **Stale content** | Compare modification time + usage stats vs. actual needs | Skills not used in 60+ days with no pinned status |
| **Name collisions** | Scan all `skills/` dirs for duplicate SKILL.md names | Same name in multiple categories or user-local + hub-installed |
| **Missing supporting files** | Check each skill's `linked_files` (references/, templates/, scripts/) exist on disk | File referenced in SKILL.md but missing from directory |
| **Merge candidates** | Look for overlapping scope/purpose across skills | Two skills solving the same problem — consolidate via umbrella + absorbed_into |
| **Description length violations** | Check `description` field ≤ 60 chars (system prompt budget) | Description truncated to 57+ "..." in skill index, destroying routing signal |
| **Memory hygiene** | Check `memories/MEMORY.md` + `USER.md` per profile vs char limits (see Phase 7) | Near-limit entries, duplicated/overlapping facts, stale task-progress entries |

## Workflow

### Phase 1: Inventory All Skills

```bash
# User-local skills (created by agent or installed via hub)
ls ~/.hermes/skills/

# Per-profile skills (if any profiles have their own)
ls ~/.hermes/profiles/<name>/skills/

# Hub-installed skills (from taps/catalogs)
ls ~/.hermes/skills/.hub/  # index-cache, quarantine, etc.
```

User-local skills live under `$HERMES_HOME/skills/` (e.g. `~/.hermes/skills` on macOS/Linux, `%LOCALAPPDATA%\hermes\skills` on Windows):
```
$HERMES_HOME/skills/
```

### Phase 2: Broken skill_view Reference Detection

For each installed skill, attempt to load it and check for content integrity issues:

1. **Load via `skill_view(name)`** — if the body contains `[SKILL_PRUNED]`, the content was lost in context compression (see Skill Safety Rule). Reload by calling `skill_view` again.
2. **Check linked_files** — each skill's metadata lists references/templates/scripts paths. Verify these exist on disk:

```bash
# For a given skill at ~/.hermes/skills/<category>/<name>/
ls -la ~/.hermes/skills/<category>/<name>/references/  # if listed in linked_files
ls -la ~/.hermes/skills/<category>/<name>/templates/   # if listed
ls -la ~/.hermes/skills/<category>/<name>/scripts/      # if listed
```

3. **Missing files** — a SKILL.md referencing `references/api.md` but the file doesn't exist means skill_view will fail when asked for that linked file. Flag these as broken references.

### Phase 3: Name Collision Detection

Scan all skill directories for duplicate names. Collisions happen between:
- User-local skills and hub-installed skills with the same name
- Skills in different categories (e.g., `hermes-agent` under both `autonomous-ai-agents/` and a profile's skills)
- Bundled skills vs. user-created overrides

```bash
# Find duplicate SKILL.md names across all directories
find ~/.hermes/skills/ -name "SKILL.md" -exec dirname {} \; | \
  xargs basename -a | sort | uniq -d
```

If duplicates found, the loader resolves them in a specific order (user-local > hub > bundled). Document which one wins and whether that's intentional.

### Phase 4: Staleness Assessment

Use the curator telemetry sidecar to identify stale skills:

```bash
# ~/.hermes/skills/.usage.json holds per-skill stats
python -c "
import json
with open('~/.hermes/skills/.usage.json') as f:
    usage = json.load(f)
for skill, stats in sorted(usage.items(), key=lambda x: x[1].get('last_activity_at', ''), reverse=False):
    last_active = stats.get('last_activity_at', 'never')
    state = stats.get('state', 'unknown')
    use_count = stats.get('use_count', 0)
    if use_count == 0 and state != 'pinned':
        print(f'⚠️ {skill}: never used, not pinned — candidate for pruning')
"
```

**Staleness criteria:**
- `use_count: 0` AND `state != "pinned"` → prune candidate (but confirm with user first)
- `last_activity_at > 60 days ago` AND `state == "stale"` → archive via curator
- **Never auto-prune** pinned skills — they're explicitly protected

### Phase 5: Description Length Validation

The system prompt skill index truncates descriptions to 57 chars + "...". If a description is >60 chars, the routing signal is destroyed. Check all SKILL.md files:

```bash
# Find skills with overly long descriptions (YAML frontmatter)
python -c "
import yaml, os, glob
for path in glob.glob('~/.hermes/skills/**/SKILL.md', recursive=True):
    try:
        with open(path) as f:
            content = f.read()
        if not content.startswith('---'):
            continue
        end = content.find('\n---\n', 3)
        fm = yaml.safe_load(content[3:end])
        desc = fm.get('description', '')
        if len(desc) > 60:
            print(f'⚠️ {path}: description is {len(desc)} chars — will be truncated')
    except Exception as e:
        print(f'❌ {path}: error parsing frontmatter: {e}')
"
```

### Phase 6: Merge Candidate Identification

Look for skills with overlapping scope. Two skills solving the same problem should be consolidated into an umbrella skill, with the old one marked `absorbed_into` via curator. This prevents the agent from choosing between near-identical skills randomly.

**Merge indicators:**
- Same trigger keywords in description
- Similar toolset (both do "monitoring", both do "backup")
- One is a strict subset of another's functionality

If candidates found, create an umbrella skill and use `skill_manage(action='delete', absorbed_into='<umbrella>')` on the redundant one.

### Phase 7: Memory Hygiene Check

Memory is injected into every turn — near-limit or duplicated entries cost tokens and degrade routing. Check per profile (default + `profiles/<name>/`):

```bash
# Per-profile memory files with size vs. limits (memory_char_limit=4096, user_char_limit=2048)
python -c "
import os, glob
limits = {'MEMORY.md': 4096, 'USER.md': 2048}
home = os.environ.get('HERMES_HOME', os.path.expanduser('~/.hermes'))
for base in [home] + sorted(glob.glob(os.path.join(home, 'profiles', '*'))):
    for fname, limit in limits.items():
        p = os.path.join(base, 'memories', fname)
        if os.path.isfile(p):
            size = os.path.getsize(p)
            flag = '⚠️ NEAR/FULL' if size > limit * 0.85 else 'ok'
            print(f'{flag:14s} {os.path.relpath(p, home)} {size}/{limit} chars')
"
```

**What to flag (in priority order):**
1. **Near-limit entries** (>85% of limit) — must consolidate before the next add is rejected
2. **Duplicated/overlapping facts** — same fact in multiple entries (e.g. two ASM-watchdog entries describing the same mechanism) — merge via `memory` batch ops
3. **Task-progress / completed-work entries** — belong in `session_search`, not memory (memory discipline from SOUL.md)
4. **Procedures stored as memory** — belong in a skill, not memory (imperative entries like "always do X" are re-read as directives and cause repeated work)

**Remediation:** use the `memory` tool's batch `operations` — remove stale entries and add the consolidated fact in ONE atomic call (char limit is checked on the final result, so a single batch can free room and add). Never split a consolidation across calls.

## Cross-Profile Considerations

When auditing skills across profiles:

1. **Profile-specific skills** live at `~/.hermes/profiles/<name>/skills/` — these are isolated from Default's skills
2. **Shared skills** loaded via `related_skills` in frontmatter can reference user-local skills, but they won't resolve for other users who clone the repo fresh (see hermes-agent-skill-authoring)
3. **Curator scope**: only touches skills with `created_by: "agent"` provenance — bundled + hub-installed skills are off-limits

## Remediation Actions

| Issue | Action | Tool |
|---|---|---|
| Broken linked file reference | Recreate the missing file or remove the reference from SKILL.md | `skill_manage(action='write_file')` or `patch` |
| `[SKILL_PRUNED]` content lost | Reload via `skill_view(name)` to trigger recovery | `skill_view` |
| Name collision (unintended) | Rename one skill's directory + update frontmatter name field | File rename + patch |
| Stale unused skill | Archive via curator: `hermes curator archive <name>` (never auto-delete) | CLI or `skill_manage(action='delete', absorbed_into=...)` for intentional merges |
| Description too long (>60 chars) | Shorten to ≤60 chars, move detail into body | `patch` on SKILL.md frontmatter |
| Overlapping skills (merge candidates) | Create umbrella skill, delete redundant with `absorbed_into` | `skill_manage` create + delete |
| Memory near-limit / duplicated / stale-progress | Batch-consolidate: remove stale, merge overlaps, add consolidated fact in one call | `memory` tool `operations` batch |

## Quick Command Reference

```bash
# List all user-local skills across categories
find ~/.hermes/skills/ -name "SKILL.md" -not -path "*/.archive/*" -not -path "*/.hub/*"

# Find duplicate skill names
find ~/.hermes/skills/ -name "SKILL.md" | xargs dirname | xargs basename -a | sort | uniq -d

# Check curator usage stats for staleness
python -c "import json; d=json.load(open('~/.hermes/skills/.usage.json')); [print(k, v.get('use_count',0), v.get('state','?'), v.get('last_activity_at','never')) for k,v in sorted(d.items(), key=lambda x: x[1].get('last_activity_at','') or '')]"

# Validate description lengths
python -c "import yaml,glob; [print(f'{len(yaml.safe_load(c[3:c.find(chr(10)+\"---\",3)]).get(\"description\",\"\"))} chars: {p}') for p in glob.glob('~/.hermes/skills/**/SKILL.md',recursive=True) if (c:=open(p).read()).startswith('---') and len(yaml.safe_load(c[3:c.find(chr(10)+\"---\",3)]).get(\"description\",\"\"))>60]"

# Reload a pruned skill
skill_view(name='<skill-name>')  # triggers recovery from curator backup

# Archive a stale unused skill (never auto-delete)
hermes curator archive <name>

# Check for broken linked files per skill
for d in ~/.hermes/skills/*/; do echo "=== $d ==="; ls "$d/references/" 2>/dev/null || echo "(no references dir)"; done
```

## Verification Checklist

- [ ] All installed skills load via `skill_view` without `[SKILL_PRUNED]` or errors
- [ ] No duplicate skill names across user-local, hub-installed, and profile-specific dirs
- [ ] All linked_files referenced in SKILL.md frontmatter exist on disk (references/, templates/, scripts/)
- [ ] No descriptions exceed 60 chars (would be truncated to 57+"..." in system prompt)
- [ ] Stale unused skills identified and archived via curator (never auto-deleted)
- [ ] Merge candidates documented for user review — no overlapping skills left unresolved
- [ ] Cross-profile skill references verified to resolve correctly when switching profiles
- [ ] Memory files per profile within limits; no duplicated/stale-progress entries (Phase 7)