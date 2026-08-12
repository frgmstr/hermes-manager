---
name: cryptography-metadata-fix
description: "Fix cryptography Version: None after a failed Hermes update."
version: 1.0.0
author: Hermes Agent + KB (Saint Jo, TX)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [hermes, update, pip, cryptography, troubleshooting]
    related_skills: [cron-troubleshooting]
---

# Fix: `cryptography` `Version: None` after a failed update

## When to Use

Trigger when, after a Hermes update/upgrade, the gateway fails to restart and the root cause smells like a broken Python package:

- `pip show cryptography` returns `Version: None` (with empty Name/Summary metadata)
- `pip list` shows `cryptography  None`
- The user or an external tool claims "cryptography is corrupted / missing RECORD file" and proposes deleting the whole package + force-reinstalling cffi/cryptography.

## Root Cause (verified 2026-08-11)

An interrupted update wrote the new dist-info but never removed the **old** one, leaving an **orphaned empty dist-info directory** (e.g. `cryptography-49.0.0.dist-info/`) sitting beside the complete new one (`cryptography-50.0.0.dist-info/`). The empty shell has **no METADATA and no RECORD**. Pip's metadata resolver trips over that empty folder and reports `Version: None` — even though the actual package code (`cryptography/`, `cffi/`, `_cffi_backend*.pyd`) is fully intact and imports fine.

**Critical insight:** The symptom is a *metadata* problem, not a *code* problem. The "delete the broken folder + force-reinstall" advice is overkill and destroys working files. The fix is surgical: remove only the orphaned empty dist-info.

## Diagnosis (run these first — do NOT delete anything yet)

```bash
site="$(python -c 'import site,sys; sys.stdout.write(site.getsitepackages()[0])')"
ls -d "$site"/cryptography*.dist-info          # expect MULTIPLE dist-infos (the smoking gun)
ls -la "$site"/cryptography-<OLD>.dist-info    # empty: NO METADATA, NO RECORD
ls -la "$site"/cryptography-<NEW>.dist-info    # complete: METADATA + RECORD + WHEEL
python -m pip show cryptography
python -c "from cryptography.hazmat.primitives import hashes; import _cffi_backend; print('IMPORT OK')"
```

**Confirm the fix target:**
1. There are ≥2 `cryptography-*.dist-info` dirs.
2. The OLDEST one is an empty husk (no METADATA, no RECORD).
3. The NEWEST one is complete.
4. `from cryptography... import` works (package code intact).

If all four hold → the surgical fix below is correct. If the package dir itself is missing/broken OR only one dist-info exists and imports fail, then a reinstall IS warranted — do not force the surgical path.

## The Fix (surgical — back up, remove ONLY the orphaned empty dist-info)

```bash
site="$(python -c 'import site,sys; sys.stdout.write(site.getsitepackages()[0])')"
bk="${HERMES_HOME:-$HOME/.hermes}/archives/crypto-distinfo-backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$bk"
cp -r "$site/cryptography-<OLD>.dist-info" "$bk/" 2>/dev/null   # backup the husk (cheap insurance)
rm -rf "$site/cryptography-<OLD>.dist-info"                       # remove ONLY the empty old one
```

Do NOT touch the `cryptography/` package dir, `cffi/`, or `_cffi_backend*.pyd`. Do NOT `pip install --force-reinstall`. Those are all fine.

## Verify (mandatory)

```bash
python -m pip show cryptography   # Version: <NEW> (e.g. 50.0.0)
python -m pip list | grep -iE 'crypto|cffi'
python -c "from cryptography.hazmat.primitives import hashes; import _cffi_backend; print('SUCCESS — everything is good')"
```

Pass = `Version: <NEW>` and `SUCCESS — everything is good`.

> **Note:** These commands assume `python` is the Hermes agent's venv interpreter. On Windows that's `$LOCALAPPDATA\hermes\hermes-agent\venv\Scripts\python.exe`; on Linux/macOS `~/.hermes/hermes-agent/venv/bin/python`. If `python` isn't on PATH, call the venv interpreter by its full path and resolve `site-packages` with `python -c "import site; print(site.getsitepackages()[0])"`.

## Restart the Gateway (the crash was downstream)

The gateway went down on the broken metadata; it won't come back until the venv is healthy.

```bash
cd "${HERMES_HOME:-$HOME/.hermes}"
hermes gateway start
sleep 6
hermes gateway status    # ✓ Gateway process running
hermes cron status       # ✓ Gateway running — ticker heartbeat fresh (<60s)
```

Verify per the update-safety runbook: default gateway up, ASM gateway up, cron heartbeats fresh.

## Pitfalls

1. **Don't trust "missing RECORD file."** In the observed case the RECORD existed (200 lines) in the NEW dist-info. The broken item was the *old* dist-info missing both METADATA and RECORD. Always run the diagnosis before acting.
2. **Don't nuke the working package.** Deleting `cryptography/` + `cffi/` + force-reinstall is unnecessary when the code imports fine — it only risks reinstall flakiness and down time.
3. **Back up before deleting**, even a trivial empty dir — cheap insurance, matches fleet discipline.
4. **Always restart + verify the gateway** after the venv fix; a healthy venv does not auto-heal a downed gateway. Cron jobs will NOT fire while it's down.
