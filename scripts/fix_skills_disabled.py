"""Set skills.disabled as a proper YAML list via the framework's own save path.

Usage:
    python fix_skills_disabled.py [skill-to-add ...]
    HERMES_HOME=<profile-home> python fix_skills_disabled.py qc-system node-inspect-debugger

Why this exists: `hermes config set` only writes scalars — a JSON array value
is stored as a single quoted string, which agent/skill_utils._normalize_string_set
treats as ONE giant skill name (so nothing would actually be disabled). The
sanctioned write path for this key is hermes_cli.skills_config.save_disabled_skills
(the same code `hermes skills config` uses), which persists a proper YAML list
via save_config (atomic write, defaults stripped). Idempotent: names already in
the list are no-ops.
"""
import json
import os
import sys

_default_home = (os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "hermes") if os.name == "nt" else os.path.expanduser("~/.hermes"))
HERMES_HOME = os.environ.get("HERMES_HOME") or _default_home
os.environ["HERMES_HOME"] = HERMES_HOME
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hermes_cli import skills_config  # noqa: E402
from hermes_cli.config import load_config  # noqa: E402

config = load_config()
skills_cfg = config.get("skills") or {}
raw = skills_cfg.get("disabled") or []

# Current value is either a real list (working form) or a JSON string (what a
# naive `hermes config set` writes). Normalize both to a set of names.
if isinstance(raw, str):
    try:
        raw = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        raw = [raw]
current = {str(s).strip() for s in raw if str(s).strip()}

target = current | set(sys.argv[1:])

skills_config.save_disabled_skills(config, target, platform=None)

print(f"disabled count: {len(target)}")
print(f"added: {sorted(target - current)}")
print(f"removed: {sorted(current - target)}")
