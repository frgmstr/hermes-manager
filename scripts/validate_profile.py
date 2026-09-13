#!/usr/bin/env python3
"""Validate hermes-manager distribution profile structure."""
import yaml, sys, os

errors = []
warnings = []

# Check required files
required_files = ["SOUL.md", "config.yaml", "distribution.yaml"]
for f in required_files:
    if not os.path.exists(f):
        errors.append(f"Required file missing: {f}")
    else:
        print(f"✅ {f} present")

# Validate config.yaml
if os.path.exists("config.yaml"):
    with open("config.yaml") as f:
        cfg = yaml.safe_load(f) or {}

    # Check skills.disabled is a list (common pitfall with hermes config set)
    if "skills" in cfg and isinstance(cfg["skills"], dict):
        disabled = cfg["skills"].get("disabled", [])
        if not isinstance(disabled, list):
            errors.append(f"skills.disabled should be a list, got {type(disabled).__name__}")

    models = cfg.get("models", {})
    providers = cfg.get("providers", {})
    print(f"\nModels configured: {len(models)}")
    if isinstance(providers, dict):
        provider_types = [p.get("type", "unknown") for p in providers.values() if isinstance(p, dict)]
        print(f"Provider types: {provider_types}")

# Validate distribution.yaml
if os.path.exists("distribution.yaml"):
    with open("distribution.yaml") as f:
        dist = yaml.safe_load(f) or {}

    required_keys = ["name", "version"]
    for key in required_keys:
        if key not in dist:
            errors.append(f"distribution.yaml missing '{key}'")

    print(f"\nDistribution: {dist.get('name', '?')} v{dist.get('version', '?')}")
    owned = dist.get("distribution_owned", [])
    if owned:
        print(f"Owned paths: {owned}")
    else:
        warnings.append("No distribution_owned specified — scripts/ may not install by default")

# Check skills structure — look for directories containing SKILL.md or nested skill dirs
if os.path.isdir("skills"):
    counter = [0]  # mutable container to avoid nonlocal issues
    skipped_subdirs = {"references", "scripts", "templates", "assets"}

    def check_skill_dir(path, label):
        if not os.path.exists(os.path.join(path, "SKILL.md")):
            errors.append(f"Skill missing SKILL.md: {label}")
        else:
            counter[0] += 1

    for top in sorted(os.listdir("skills")):
        top_path = os.path.join("skills", top)
        if not os.path.isdir(top_path):
            continue
        # Check if this is a category dir (contains subdirs with SKILL.md) or a direct skill
        has_skill_md = os.path.exists(os.path.join(top_path, "SKILL.md"))
        subs = [s for s in sorted(os.listdir(top_path)) if os.path.isdir(os.path.join(top_path, s))]

        if has_skill_md:
            # Direct skill (flat structure)
            check_skill_dir(top_path, top)
        else:
            # Category dir — iterate subdirs but skip non-skill dirs like references/scripts
            for sub in subs:
                if sub.lower() in skipped_subdirs:
                    continue
                skill_path = os.path.join(top_path, sub)
                check_skill_dir(skill_path, f"{top}/{sub}")

    print(f"\n✅ Checked {counter[0]} skills — all have SKILL.md")

# Check for secrets in tracked files (basic grep-style scan)
import re
secret_pattern = re.compile(r'(api_key|secret|password|token)\s*[:=]\s*[a-zA-Z0-9]{20,}', re.IGNORECASE)
for root, dirs, files in os.walk("."):
    # Skip .git and hidden dirs
    dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
    for fname in files:
        if fname.endswith((".py", ".yaml", ".yml", ".md")):
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", errors="ignore") as f:
                    for lineno, line in enumerate(f, 1):
                        if secret_pattern.search(line):
                            # Skip .env.example which legitimately has placeholder keys
                            if ".env" not in fname and "example" not in fname.lower():
                                warnings.append(f"Possible secret at {fpath}:{lineno}")
            except Exception:
                pass

if errors:
    print("\n❌ ERRORS:")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)

if warnings:
    print("\n⚠️ WARNINGS:")
    for w in warnings:
        print(f"  - {w}")

print("\n=== Profile validation complete ===")
