#!/usr/bin/env python3
"""
Profile Gateway Watchdog — monitors + auto-heals a profile's cron ticker.

Suggested schedule: every 10 minutes via the manager profile's cron
(no_agent job — non-empty stdout is the delivered message, silent when healthy).

Checks:
  1. Is the target profile's gateway cron ticker alive (<STALL_THRESHOLD since heartbeat)?
  2. If stalled or down → restart that profile's gateway. Uses direct process
     management (taskkill/kill + gateway start) to bypass the CLI's cross-profile
     restart guard, so recovery is fully autonomous.
  3. Optional: health-check a local inference server (LM Studio) first — agent-based
     jobs need it. Auto-start is attempted only when `lms` is on PATH or LMLMS_PATH
     is set.

Configuration via environment variables (put them in the profile's .env):
  WATCHDOG_PROFILE   (required) target profile name, e.g. my-project
  STALL_THRESHOLD    heartbeat staleness (seconds) that triggers a restart (default 300)
  LMSTUDIO_URL       base URL of the local inference server (default http://127.0.0.1:1234/v1)
  LMLMS_PATH         optional absolute path to the `lms` CLI for auto-starting LM Studio
  HERMES_HOME        your Hermes home (defaults to %LOCALAPPDATA%\\hermes or ~/.hermes)
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROFILE = os.environ.get("WATCHDOG_PROFILE", "").strip()
STALL_THRESHOLD = int(os.environ.get("STALL_THRESHOLD", "300"))  # seconds
LMSTUDIO_URL = os.environ.get("LMSTUDIO_URL", "http://127.0.0.1:1234/v1").rstrip("/")
LMLMS_PATH = os.environ.get("LMLMS_PATH", "").strip()

if not PROFILE:
    sys.exit("ERROR: WATCHDOG_PROFILE env var is required (e.g. WATCHDOG_PROFILE=my-project)")


def _default_home() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "hermes"
    return Path.home() / ".hermes"


HERMES_HOME = Path(os.environ.get("HERMES_HOME") or _default_home())
LOG_PATH = HERMES_HOME / "logs" / f"{PROFILE}_watchdog.log"


def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except OSError:
        pass


def run_cmd(cmd, timeout=60):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return -1, str(e)


def find_hermes_bin() -> str:
    exe = shutil.which("hermes")
    if exe:
        return exe
    script_dir = "Scripts" if os.name == "nt" else "bin"
    name = "hermes.exe" if os.name == "nt" else "hermes"
    candidate = HERMES_HOME / "hermes-agent" / "venv" / script_dir / name
    if candidate.exists():
        return str(candidate)
    sys.exit(
        f"ERROR: could not locate the hermes binary. Add it to PATH or set HERMES_HOME "
        f"(tried: {candidate})."
    )


HERMES_BIN = find_hermes_bin()


def run_hermes(args):
    try:
        r = subprocess.run([HERMES_BIN] + args, capture_output=True, text=True, timeout=60)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return -1, str(e)


def check_lmstudio():
    """Returns (ok: bool, msg: str)."""
    rc, out = run_cmd(f'curl -s --connect-timeout 5 {LMSTUDIO_URL}/models')
    if rc != 0 or not out.strip() or "Connection refused" in out:
        return False, f"inference server unreachable on {LMSTUDIO_URL}"
    try:
        data = json.loads(out)
        models = data.get("data", [])
        if not models:
            return False, "server running but 0 models loaded"
        names = [m.get("id", "?") for m in models]
        return True, f"{len(models)} model(s): {', '.join(names)}"
    except json.JSONDecodeError:
        return False, f"non-JSON response: {out[:100]}"


def check_ticker():
    """Check the target profile's cron ticker health.
    Returns (alive: bool|None, stalled_sec: int|None)."""
    rc, out = run_hermes(["-p", PROFILE, "cron", "status"])

    if "not running" in out.lower() and "gateway process" not in out.lower():
        return False, None  # gateway down entirely

    for line in out.splitlines():
        lower = line.lower().strip()
        if "no heartbeat for" in lower or "stalled" in lower:
            m = re.search(r"for\s+(\d+)\s*s", line, re.IGNORECASE)
            stalled = int(m.group(1)) if m else None
            return False, stalled

    # Healthy ticker — e.g. "Ticker heartbeat: 45s ago" or "0s ago"
    for line in out.splitlines():
        lower = line.lower().strip()
        if "ticker heartbeat" in lower and "ago" in lower:
            m = re.search(r"heartbeat:\s*(\d+)\s*s\s+ago", line, re.IGNORECASE)
            if m:
                return True, int(m.group(1))

    log(f"WARNING: could not parse ticker status from output:\n{out[:500]}")
    return None, None


def find_gateway_pid():
    """Find the target profile's gateway PID from `cron status` output."""
    rc, out = run_hermes(["-p", PROFILE, "cron", "status"])
    m = re.search(r"PID:\s*(\d+)", out)
    if m:
        return int(m.group(1))
    return None


def kill_pid(pid):
    if os.name == "nt":
        rc, out = run_cmd(f"taskkill /PID {pid} /F 2>&1", timeout=15)
        if "ERROR" in out or "not found" in out.lower():
            return False, out[:200]
        return True, out[:200]
    rc, out = run_cmd(f"kill -9 {pid} 2>&1", timeout=15)
    if rc != 0 and "no such process" not in out.lower():
        return False, out[:200]
    return True, out[:200]


def restart_gateway():
    """Restart the target profile's gateway via direct process management."""
    pid = find_gateway_pid()

    if pid is not None:
        log(f"Killing stale {PROFILE} gateway (PID {pid})...")
        ok, out = kill_pid(pid)
        if ok:
            log(f"Killed gateway process (PID {pid}).")
        else:
            log(f"WARNING: could not kill PID {pid}: {out}")
        time.sleep(3)
    else:
        log(f"No existing {PROFILE} gateway PID found — starting fresh.")

    log(f"Starting new {PROFILE} gateway...")
    if os.name == "nt":
        rc, out = run_cmd(
            f'start "" "{HERMES_BIN}" -p {PROFILE} --accept-hooks gateway start 2>&1',
            timeout=15,
        )
    else:
        rc, out = run_cmd(
            f'nohup "{HERMES_BIN}" -p {PROFILE} --accept-hooks gateway start '
            f">/dev/null 2>&1 &",
            timeout=15,
        )

    # Wait for the ticker to come back up (up to ~30s)
    for _ in range(6):
        time.sleep(5)
        alive, _ = check_ticker()
        if alive is True:
            log("SUCCESS: gateway restarted, ticker healthy.")
            return True

    alive, stalled = check_ticker()
    if alive is True:
        log(f"SUCCESS: gateway recovered (heartbeat {stalled}s ago).")
        return True

    log(f"ERROR: after restart attempts, ticker still unhealthy. alive={alive}, stalled={stalled}")
    return False


def start_lmstudio():
    """Try to start LM Studio if it is not running and a path is known."""
    rc, out = run_cmd(f"curl -s --connect-timeout 2 {LMSTUDIO_URL}/models")
    if rc == 0 and out.strip() and "Connection refused" not in out:
        return True  # already running

    if not LMLMS_PATH:
        return False  # no auto-start path configured — report only

    log("Inference server not reachable — attempting to start via lms CLI...")
    run_cmd(f'start "" "{LMLMS_PATH}" serve 2>&1', timeout=5) if os.name == "nt" else run_cmd(
        f'nohup "{LMLMS_PATH}" serve >/dev/null 2>&1 &', timeout=5
    )
    time.sleep(8)

    rc, out = run_cmd(f"curl -s --connect-timeout 5 {LMSTUDIO_URL}/models")
    if rc == 0 and out.strip():
        try:
            data = json.loads(out)
            if data.get("data"):
                log("SUCCESS: inference server started with model(s).")
                return True
            log("WARNING: server is up but no models loaded — load one manually.")
            return False
        except json.JSONDecodeError:
            pass
    log(f"ERROR: could not start inference server. Last output: {out[:200]}")
    return False


def main():
    # 1. Optional: check the local inference server (agent-based jobs need it)
    lm_ok, lm_msg = check_lmstudio()
    if not lm_ok:
        log(f"Inference server issue: {lm_msg}")
        if not start_lmstudio():
            print(f"ALERT: inference server ({LMSTUDIO_URL}) is down and could not be auto-started. Agent-based {PROFILE} jobs will fail.")
            # Don't exit yet — the gateway may still need restarting for script-only jobs

    # 2. Check ticker health
    alive, stalled = check_ticker()

    if alive is False:
        log(f"Ticker STALLED ({stalled}s) or gateway DOWN. Restarting...")
        if not restart_gateway():
            print(f"ALERT: {PROFILE} gateway/ticker is down and could not be restarted automatically.")
            sys.exit(1)

    elif alive is True and stalled is not None and stalled > STALL_THRESHOLD:
        log(f"Ticker heartbeat stale ({stalled}s > {STALL_THRESHOLD}s). Restarting...")
        if not restart_gateway():
            print(f"ALERT: {PROFILE} cron ticker is stale and could not be restarted automatically.")
            sys.exit(1)

    else:
        # Healthy — stay silent (watchdog pattern)
        pass


if __name__ == "__main__":
    main()
