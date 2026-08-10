#!/usr/bin/env python3
"""Credential & endpoint liveness audit for all Hermes profiles.

Report-only (exit 0 always). Checks each profile's .env for known credential
key families, then probes live endpoints only for families that are fully
present. Values are never printed — only presence + probe results.

Probes (each optional via flags):
  --skip-probes   skip all network probes (presence check only)
  --skip-xapi     skip the X API probe (free endpoint; 0 credits)

Usage:
  python credential_audit.py
  python credential_audit.py --skip-xapi
"""
import argparse
import json
import os
import re
import sys
import urllib.request

_default_home = (os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "hermes") if os.name == "nt" else os.path.expanduser("~/.hermes"))
HERMES_HOME = os.environ.get("HERMES_HOME", _default_home)

# (family label, [required env keys], probe_factory or None)
# Note: LM Studio family accepts EITHER LMSTUDIO_API_KEY (profile .envs) or the
# default profile's resolved custom-provider key var.
FAMILIES = {
    "X API (OAuth1+bearer)": (
        ["X_CONSUMER_KEY", "X_CONSUMER_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET", "X_BEARER_TOKEN"],
        "xapi",
    ),
    "X API (OAuth2 PKCE)": (["X_CLIENT_ID", "X_CLIENT_SECRET", "X_REFRESH_TOKEN"], "xapi"),
    "Telegram": (["TELEGRAM_BOT_TOKEN"], "telegram"),
    "LM Studio": (["LMSTUDIO_API_KEY"], "lmstudio"),
    "GitHub": (["GITHUB_TOKEN"], "github"),
    # Firecrawl is presence-only: its auth/credit endpoint moved (api.firecrawl.dev
    # returns "Cannot GET /v1/credit-usage" as of 2026-08) and it isn't in the
    # active pipeline (web.backend=ddgs). Re-verify against docs when enabled.
    "Firecrawl": (["FIRECRAWL_API_KEY"], None),
}


def load_env(path):
    out = {}
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def get_profile_dirs():
    profiles = ["default"]
    root = os.path.join(HERMES_HOME, "profiles")
    if os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            full = os.path.join(root, name)
            if os.path.isdir(full) and not name.startswith("."):
                profiles.append(name)
    return profiles


def http_get(url, headers, timeout=8):
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(5000).decode("utf-8", errors="replace")
            return resp.status, body
    except urllib.error.HTTPError as e:
        body = e.read(500).decode("utf-8", errors="replace")
        return e.code, body
    except Exception as e:
        return 0, str(e)[:120]


def probe_xapi(env):
    bearer = env.get("X_BEARER_TOKEN")
    if not bearer:
        return "SKIP", "no bearer token"
    # search/recent is app-only compatible, costs 1 credit, and exercises the
    # same paid endpoint the ASM pipeline uses — a true auth+entitlement check.
    # (users/by/username does NOT accept app-only bearer — returns empty 404.)
    status, body = http_get(
        "https://api.twitter.com/2/tweets/search/recent?query=from%3Atwitterdev&max_results=10",
        {"Authorization": f"Bearer {bearer}"},
    )
    if status == 200:
        return "OK", "X API auth + credits valid (search/recent, 1 credit)"
    if status == 401:
        return "FAIL", "bearer rejected (401) — refresh via client-credentials flow"
    if status in (402, 403):
        return "FAIL", f"{status} — check app entitlements/credits"
    if status == 429:
        return "OK", "rate-limited (429) — token alive, budget window exhausted"
    return ("FAIL" if status else "ERR"), f"HTTP {status}: {body[:80]}"


def probe_telegram(env):
    token = env.get("TELEGRAM_BOT_TOKEN")
    if not token:
        return "SKIP", "no bot token"
    status, body = http_get(f"https://api.telegram.org/bot{token}/getMe", {})
    if status == 200 and '"ok":true' in body:
        return "OK", "Telegram bot valid"
    if status == 404:
        return "FAIL", "bot token invalid (404 — unknown bot)"
    return ("FAIL" if status else "ERR"), f"HTTP {status}: {body[:80]}"


def probe_lmstudio(env):
    lmstudio_url = os.environ.get("LMSTUDIO_URL", "http://127.0.0.1:1234/v1").rstrip("/")
    status, body = http_get(f"{lmstudio_url}/models", {})
    if status == 200:
        try:
            names = [m.get("id", "?") for m in json.loads(body).get("data", [])]
            return "OK", f"LM Studio up — models: {', '.join(names)}"
        except Exception:
            return "OK", "LM Studio up (models unparseable)"
    return ("FAIL" if status else "ERR"), f"HTTP {status}: {body[:60]}"


def probe_github(env):
    token = env.get("GITHUB_TOKEN")
    if not token:
        return "SKIP", "no token"
    status, body = http_get("https://api.github.com/user", {"Authorization": f"Bearer {token}", "User-Agent": "hermes-audit"})
    if status == 200:
        return "OK", "GitHub token valid"
    return ("FAIL" if status else "ERR"), f"HTTP {status}: {body[:80]}"


PROBES = {
    "xapi": probe_xapi,
    "telegram": probe_telegram,
    "lmstudio": probe_lmstudio,
    "github": probe_github,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-probes", action="store_true")
    ap.add_argument("--skip-xapi", action="store_true")
    args = ap.parse_args()

    print(f"=== Credential & Endpoint Liveness Audit — {HERMES_HOME} ===")
    for profile in get_profile_dirs():
        prof_dir = HERMES_HOME if profile == "default" else os.path.join(HERMES_HOME, "profiles", profile)
        env = load_env(os.path.join(prof_dir, ".env"))
        print(f"\n[{profile}]  (.env keys: {len(env)})")
        for label, (keys, probe_key) in FAMILIES.items():
            present = [k for k in keys if env.get(k)]
            missing = [k for k in keys if not env.get(k)]
            status_icon = "✓" if not missing else "✗"
            print(f"  {status_icon} {label}: {len(present)}/{len(keys)} present"
                  + (f"  missing: {', '.join(missing)}" if missing else ""))
            if missing or args.skip_probes or probe_key is None or (probe_key == "xapi" and args.skip_xapi):
                continue
            probe = PROBES[probe_key]
            p_status, p_msg = probe(env)
            print(f"      ↳ probe [{probe_key}]: {p_status} — {p_msg}")
    print("\nReport-only audit: no changes made. Values redacted.")
    sys.exit(0)


if __name__ == "__main__":
    main()
