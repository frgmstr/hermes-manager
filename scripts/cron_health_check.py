#!/usr/bin/env python3
"""Cron health watchdog — checks ALL profiles' gateways + cron jobs and reports issues.

Runs daily via a no_agent:true cron job in the default profile. Always exits 0
(reporting issues is its job, not a failure). Per the watchdog self-referential
failure rule: never exit non-zero for "found problems" — only for unrecoverable
errors like can't read config or gateway completely unreachable at startup.

Checks performed per profile:
  - Gateway running? (each Hermes profile needs its own dedicated gateway)
  - Cron jobs active and not failed/stale/running
  - For agent-based jobs using provider=custom/lmstudio: LM Studio API reachable + model loaded
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

_default_home = (os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "hermes") if os.name == "nt" else os.path.expanduser("~/.hermes"))
HERMES_HOME = os.environ.get("HERMES_HOME", _default_home)
STALE_MULTIPLIER = 2.0   # Flag if last run > expected_interval * this factor
LMSTUDIO_URL = os.environ.get("LMSTUDIO_URL", "http://127.0.0.1:1234/v1").rstrip("/")

# Profiles to check (default + all under profiles/)
def get_profile_dirs():
    profiles = ["default"]
    prof_root = os.path.join(HERMES_HOME, "profiles")
    if os.path.isdir(prof_root):
        for name in sorted(os.listdir(prof_root)):
            full = os.path.join(prof_root, name)
            if os.path.isdir(full) and not name.startswith("."):
                profiles.append(name)
    return profiles

def run_cmd(cmd, timeout=30):
    flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW: hide console children
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout,
                            creationflags=flags)
    return result.returncode, result.stdout.strip(), result.stderr.strip()

# Full path to hermes binary (avoids PATH issues when running per-profile).
# Derived from HERMES_HOME so no machine-specific paths (e.g. C:\Users\<user>\...)
# leak into this shared public distribution.
if os.name == "nt":
    HERMES_BIN = os.path.join(HERMES_HOME, "hermes-agent", "venv", "Scripts", "hermes.exe")
else:
    HERMES_BIN = os.path.join(HERMES_HOME, ".venv", "bin", "hermes")

def check_lmstudio():
    """Check if LM Studio is running and has a model loaded."""
    rc, out, err = run_cmd(f'curl -s --connect-timeout 5 {LMSTUDIO_URL}/models')
    if rc != 0 or not out:
        return False, "LM Studio API unreachable"
    try:
        data = json.loads(out)
        models = data.get("data", [])
        if not models:
            return False, f"LM Studio running but NO MODELS LOADED (0 models in /models)"
        names = [m.get("id","?") for m in models]
        return True, f"{len(models)} model(s) loaded: {', '.join(names)}"
    except json.JSONDecodeError:
        return False, f"LM Studio API returned non-JSON (rc={rc})"

MALFORMED_KEEP = 2  # keep this many newest state.db.malformed-backup-* sets per profile

def rotate_malformed_backups(issues, info):
    """Prune stale state.db.malformed-backup-* sets across all profiles.

    A 'set' is the base file plus its optional -shm/-wal siblings sharing a
    timestamp. Keeps the MALFORMED_KEEP newest sets for forensics and removes
    older ones — these pile up when a profile's gateway repeatedly detects a
    malformed state.db (see ASM profile history: dozens of sets per day).
    """
    pattern = re.compile(r"^state\.db\.malformed-backup-(\d{8}_\d{6})(-shm|-wal)?$")
    pruned = []
    for profile in get_profile_dirs():
        prof_dir = os.path.join(HERMES_HOME, "profiles", profile) if profile != "default" else HERMES_HOME
        if not os.path.isdir(prof_dir):
            continue
        sets = {}
        try:
            names = os.listdir(prof_dir)
        except OSError as e:
            issues.append(f"⛔ {profile}: cannot list dir for backup rotation: {e}")
            continue
        for fn in names:
            m = pattern.match(fn)
            if m:
                sets.setdefault(m.group(1), []).append(fn)
        if not sets:
            continue
        timestamps = sorted(sets.keys())
        if len(timestamps) <= MALFORMED_KEEP:
            continue
        for ts in timestamps[:-MALFORMED_KEEP]:
            for fn in sets[ts]:
                try:
                    os.remove(os.path.join(prof_dir, fn))
                    pruned.append(f"{profile}/{fn}")
                except OSError as e:
                    issues.append(f"⚠ {profile}: failed to remove {fn}: {e}")
    if pruned:
        shown = ", ".join(pruned[:5])
        extra = f" (+{len(pruned)-5} more)" if len(pruned) > 5 else ""
        info.append(f"🧹 Rotated malformed state.db backups (kept newest {MALFORMED_KEEP} set(s)): {shown}{extra}")

def parse_schedule_interval_hours(schedule):
    """Extract expected interval in hours from schedule strings like 'every 360m' or '0 9 * * *'.

    Properly handles cron day-of-week / day-of-month so weekly jobs (e.g. '0 8 * * 1')
    aren't treated as daily (which would false-flag them stale ~1 day after running).
    """
    if not schedule:
        return None
    # "every Nh" / "every Nm" formats
    m = re.search(r"every\s+(\d+)\s*([hm])", schedule, re.IGNORECASE)
    if m:
        val = int(m.group(1))
        unit = m.group(2).lower()
        hours = val if unit == "h" else val / 60.0
        return max(hours, 0.05)  # avoid div-by-zero for sub-minute schedules

    # Cron-style: 5 fields "min hour dom mon dow"
    if re.match(r"^[\d*/,\-]+\s+[\d*/,\-]+\s+[\d*/,\-]+\s+[\d*/,\-]+\s+[\d*/,\-]+\s*$", schedule):
        parts = schedule.split()
        minute, hour, dom, mon, dow = parts[0], parts[1], parts[2], parts[3], parts[4]

        # */N in minute field -> every N minutes
        m = re.search(r"\*/(\d+)", minute)
        if m:
            return int(m.group(1)) / 60.0

        # Day-of-week is a specific value or single-day list/range (e.g. "1", "1-5")
        # -> job runs only on those days, so the expected gap is ~24h * days-per-cycle
        if dow.strip() != "*":
            # A fixed single dow value (e.g. "1" = Monday) -> weekly (~168h).
            if re.fullmatch(r"\d{1,7}", dow.strip()):
                return 24.0 * 7.0
            # A contiguous range (e.g. "1-5" = weekdays) -> runs daily within the week.
            if re.match(r"^\d{1,7}-\d{1,7}$", dow.strip()):
                lo, hi = (int(x) for x in dow.split("-"))
                return 24.0 if hi >= lo else 24.0 * 6.0  # wrap-around weekend -> ~daily-ish
            # A comma list of specific days -> gap is ~24h * days / len(list)
            if "," in dow:
                days = [int(x) for x in dow.split(",") if x.strip().isdigit()]
                if days:
                    return 24.0 * 7.0 / max(len(days), 1)
            return 24.0  # unknown dow pattern -> assume daily

        # Day-of-month is a specific value -> monthly-ish
        if dom.strip() != "*":
            if re.fullmatch(r"\d{1,2}", dom.strip()):
                return 24.0 * 30.0
            return 24.0

        # No day constraints and hour is a fixed value -> daily (~24h)
        return 24.0

    # ISO timestamp (one-shot): can't estimate interval
    return None

def last_scheduled_occurrence_hours(schedule):
    """Hours since the most recent scheduled occurrence of a cron dow-range
    spec (e.g. '30 20 * * 1-5'), or None for any other schedule shape.

    Weekday jobs have a natural Fri->Mon gap (~72h) that the flat 24h interval
    from parse_schedule_interval_hours can't represent, so they false-flag
    STALE every weekend. Comparing the last run against the actual most
    recent occurrence (2h tolerance for scheduler lag) keeps detection sharp:
    a genuinely missed weekday run is still flagged at the next check.
    """
    if not schedule:
        return None
    if not re.match(r"^[\d*/,\-]+\s+[\d*/,\-]+\s+[\d*/,\-]+\s+[\d*/,\-]+\s+[\d*/,\-]+\s*$", schedule):
        return None
    minute, hour, dom, mon, dow = schedule.split()
    if dom.strip() != "*" or mon.strip() != "*":
        return None
    if not (re.fullmatch(r"\d{1,2}", minute) and re.fullmatch(r"\d{1,2}", hour)):
        return None
    if not re.match(r"^\d{1,7}-\d{1,7}$", dow.strip()):
        return None
    lo, hi = (int(x) for x in dow.split("-"))
    if hi >= lo:
        allowed = set(range(lo, hi + 1))
    else:  # wrap-around range like 5-1 (Fri..Mon)
        allowed = set(range(lo, 7)) | {0} | set(range(0, hi + 1))
    allowed = {x % 7 for x in allowed}  # normalize cron dow 7 (Sun) -> 0
    now = datetime.now().astimezone()
    for days_back in range(0, 8):
        day = (now - timedelta(days=days_back)).date()
        cron_wd = (day.weekday() + 1) % 7  # python Mon=0 -> cron Sun=0
        if cron_wd in allowed:
            cand = now.replace(year=day.year, month=day.month, day=day.day,
                               hour=int(hour), minute=int(minute),
                               second=0, microsecond=0)
            if cand <= now:
                return (now - cand).total_seconds() / 3600.0
            # today's occurrence is still in the future; keep looking back
    return None

def check_profile(profile, issues, info):
    """Check gateway + cron jobs for a single profile."""
    prof_dir = os.path.join(HERMES_HOME, "profiles", profile) if profile != "default" else HERMES_HOME

    # Set up environment with correct HERMES_HOME for this profile
    env = dict(os.environ)
    env["HERMES_HOME"] = prof_dir

    def run_profile_cmd(cmd):
        """Run a command with the per-profile HERMES_HOME set."""
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=30,
            env=env,
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()

    # --- Cron job check FIRST (per-profile) — we need to know if jobs exist before flagging gateway --
    rc, out, err = run_profile_cmd(f'{HERMES_BIN} cron list 2>&1')
    has_active_jobs = False

    if rc != 0:
        issues.append(f"⛔ Profile '{profile}' — cannot list cron jobs: {err[:80]}")
        return

    # Parse the output format from `hermes cron list` (box-drawing table)
    lines = out.split("\n")
    current_job = {}
    parsed_jobs = []

    for line in lines:
        stripped = line.strip()

        if re.match(r"^[0-9a-f]{12}\s+\[", stripped):
            if current_job:
                _evaluate_job(current_job, issues, info, profile)
                # Track whether this job is active (not paused/failed)
                status_raw = current_job.get("status_raw", "")
                if "[active]" in status_raw:
                    has_active_jobs = True
            parts = stripped.split()
            current_job = {
                "id": parts[0],
                "status_raw": " ".join(parts[1:]) if len(parts) > 1 else "",
            }
        elif stripped.startswith("Name:"):
            current_job["name"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("Schedule:"):
            current_job["schedule"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("Last run:") or stripped.startswith("Last execution:"):
            val = stripped.split(":", 1)[1].strip() if ":" in stripped else ""
            current_job.setdefault("_last_run", []).append(val)
        elif "Execution:" in stripped and "Last" not in stripped:
            parts2 = stripped.split(":", 1)
            if len(parts2) > 1:
                current_job["execution"] = parts2[1].strip()

    # Flush last job
    if current_job:
        _evaluate_job(current_job, issues, info, profile)
        status_raw = current_job.get("status_raw", "")
        if "[active]" in status_raw:
            has_active_jobs = True

    parsed_jobs.append(current_job)  # keep for potential future use

    # --- Gateway check — only flag as issue if there are active jobs that need it --
    rc, out, err = run_profile_cmd(f'{HERMES_BIN} gateway status 2>&1')

    if profile == "default":
        gw_running = rc == 0 and "not running" not in (out + err).lower()
    else:
        gw_status_line = None
        for line in out.split("\n"):
            if "not running" in (out + err).lower():
                gw_running = False
                break
            if profile in line and ("✓" in line or "running" in line.lower()):
                gw_status_line = line.strip()

        if "not running" not in (out + err).lower():
            gw_running = bool(gw_status_line) and ("✓" in gw_status_line or "running" in gw_status_line.lower())

    if not gw_running:
        # Only flag as issue if there are active cron jobs that depend on this gateway.
        # Profiles with no scheduled jobs don't need a running gateway — starting one would be wasteful.
        if has_active_jobs:
            issues.append(f"⛔ PROFILE '{profile}' — gateway NOT RUNNING (cron jobs will silently skip)")
        else:
            info.append(f"ℹ Profile '{profile}' — gateway not running but no active cron jobs (ok)")
    else:
        job_count = "with active cron jobs" if has_active_jobs else "(no scheduled jobs)"
        info.append(f"✓ Profile '{profile}' gateway is running {job_count}")

def _evaluate_job(job, issues, info, profile):
    """Evaluate a single parsed cron job for problems."""
    job_id = job.get("id", "?")[:12]
    job_name = job.get("name", "unnamed")[:50]
    schedule = job.get("schedule", "")

    # Status check — look for [active], [paused], or error indicators
    status_raw = job.get("status_raw", "")
    if "[active]" not in status_raw:
        issues.append(f"⚠ Profile '{profile}' — Job {job_id} ({job_name}) is NOT ACTIVE: {status_raw}")

    # Execution status check
    execution = job.get("execution", "")
    exec_status = ""
    if execution:
        parts = execution.split()
        exec_status = parts[0].lower() if parts else ""

    if exec_status == "failed":
        issues.append(f"⛔ Profile '{profile}' — Job {job_id} ({job_name}) last execution FAILED")
    elif exec_status == "unknown":
        pass  # unknown is normal for first run or recent schedules
    elif exec_status in ("running",):
        info.append(f"ℹ Profile '{profile}' — Job {job_id} ({job_name}) currently RUNNING (ok if scheduled)")

    # Staleness check: did it actually fire when expected?
    last_runs = job.get("_last_run", [])
    for lr in last_runs:
        try:
            ts_part = lr.split()[0]  # ISO timestamp before any status suffix
            last_run = datetime.fromisoformat(ts_part)
            if last_run.tzinfo is None:
                last_run = last_run.replace(tzinfo=timezone.utc)
            now_utc = datetime.now(timezone.utc)
            hours_since = (now_utc - last_run).total_seconds() / 3600

            expected_h = parse_schedule_interval_hours(schedule)
            last_occ_h = last_scheduled_occurrence_hours(schedule)
            if last_occ_h is not None:
                # dow-range job (e.g. '30 20 * * 1-5'): multi-day natural gaps
                # (Fri->Mon) are normal. Stale only if it MISSED its most
                # recent scheduled occurrence (2h tolerance for scheduler lag).
                if hours_since > last_occ_h + 2.0:
                    issues.append(
                        f"⚠ Profile '{profile}' — Job {job_id} ({job_name}) is STALE "
                        f"(last ran {hours_since:.1f}h ago but last scheduled "
                        f"occurrence was {last_occ_h:.1f}h ago)"
                    )
                else:
                    info.append(f"✓ Profile '{profile}' — Job {job_id} ({job_name}) last ran {hours_since:.1f}h ago")
            elif expected_h and hours_since > expected_h * STALE_MULTIPLIER:
                issues.append(
                    f"⚠ Profile '{profile}' — Job {job_id} ({job_name}) is STALE "
                    f"(last ran {hours_since:.1f}h ago, expected every ~{expected_h:.1f}h)"
                )
            else:
                info.append(f"✓ Profile '{profile}' — Job {job_id} ({job_name}) last ran {hours_since:.1f}h ago")
        except (ValueError, IndexError):
            pass

def main():
    now = datetime.now(timezone.utc)
    issues = []
    info = []

    profiles = get_profile_dirs()
    for profile in profiles:
        try:
            check_profile(profile, issues, info)
        except Exception as e:
            issues.append(f"⛔ Profile '{profile}' — watchdog error checking this profile: {e}")

    # --- Housekeeping: rotate stale malformed state.db backups (all profiles) ---
    rotate_malformed_backups(issues, info)

    # --- LM Studio availability (for agent-based jobs using provider=custom/lmstudio) ---
    lm_ok, lm_msg = check_lmstudio()
    if not lm_ok:
        issues.append(f"⚠ LM Studio: {lm_msg} — agent-based cron jobs will fail at next run")
    else:
        info.append(f"✓ LM Studio: {lm_msg}")

    # --- Report ---
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"=== Cron Health Check — {timestamp} ===")
    print(f"  Profiles checked: {len(profiles)} ({', '.join(profiles)})")
    print()

    for line in info:
        print(f"  {line}")

    if issues:
        print(f"\n  ISSUES FOUND ({len(issues)}):")
        for issue in issues:
            print(f"  {issue}")
    else:
        print("\n  All clear — no issues found.")

    # Always exit 0: reporting problems is the watchdog's job, not a failure.
    sys.exit(0)

if __name__ == "__main__":
    main()
