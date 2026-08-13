# Native-Python Path + Script Bug Class (cron `no_agent` wrappers)

Real recovery session where three profile cron jobs failed for distinct root
causes. The patterns generalize to any profile whose `no_agent` jobs wrap
external scripts. All examples are sanitized — substitute your own paths/model
ids/profile names.

## 1. MSYS `/c/...` paths crash native venv Python (the big one)

The cron scheduler runs `.py` scripts under Hermes' **native venv Python**
(`sys.executable`) — NOT the terminal tool's git-bash shell. A subprocess path
written as MSYS-style `/c/Users/...` raises:

```
FileNotFoundError: [WinError 2] The system cannot find the file specified
    ... _winapi.CreateProcess(executable, args, ...)
```

**Rule**: In any `.py` cron wrapper that calls an external interpreter or opens a
path via `subprocess`, use the **drive-letter form** `C:/Users/...` (forward
slashes, drive prefix). `C:/...` works under BOTH git-bash and native Windows
Python; `/c/...` works ONLY under bash.

```python
# BAD — native venv Python cannot launch /c/...
PY314 = "/c/Users/<user>/AppData/Local/Programs/Python/Python314/python.exe"
subprocess.run([PY314, TARGET, ...])   # WinError 2

# GOOD — drive-letter form works under bash AND native Python
PY314 = "C:/Users/<user>/AppData/Local/Programs/Python/Python314/python.exe"
subprocess.run([PY314, TARGET, ...])
```

Applies to `PY314` interpreter constants, `OUTDIR` path constants, and any path
passed into `subprocess`.

**.sh wrappers** run under bash so `/c/` works there — but `C:/` works in both,
so prefer `C:/` everywhere for uniformity.

## 2. Health checker false "STALE" on weekly jobs

`cron_health_check.py`'s `parse_schedule_interval_hours()` originally defaulted
**every** cron string to 24h. A weekly job (`0 8 * * 1` = Monday) got flagged
`STALE` ~1 day after running because 25h > 24h. False alarm, not a real failure.

**Fix**: the parser now honors the cron day-of-week / day-of-month fields:
- fixed dow value (`1` = Monday) → `24 * 7 = 168h`
- contiguous dow range (`1-5` = weekdays) → `24h`
- comma dow list → `24 * 7 / len(list)`
- `*/N` in minute field → `N / 60h`
- no day constraints, fixed hour → `24h`

**Lesson**: when a health checker flags a job "stale," verify the job's REAL
schedule before trusting the alarm. A weekly job is not stale after one day.

## 3. UnboundLocalError from a var assigned inside a conditional block

A report generator had `top = scored[:top_n]` indented INSIDE the
`if not scored:` block. When `scored` was non-empty (the normal case), the block
was skipped, `top` was never bound, and `for post in enumerate(top, 1)` raised:

```
UnboundLocalError: cannot access local variable 'top' where it is not
associated with a value
```

**Fix**: hoist the assignment to function-body level, outside the conditional:

```python
if not scored:
    ... # early-return OR fall-through
top = scored[:top_n]      # must be OUTSIDE the if block
for i, post in enumerate(top, 1):
    ...
```

**Lesson**: any variable referenced later but assigned only inside a conditional
is a latent crash on the branch you don't think about. Grep for assignments
nested under `if not X:` where X is the *common* case.

## 4. Wrapper passes a flag the target script doesn't accept

A weekly cycle wrapper called `collector.py --lookback-hours 720`, but that
script defines `--force-full` / `--max-results` / `--skip-budget-check` — **no**
`--lookback-hours`. Result: step 1 failed every run with:

```
collector.py: error: unrecognized arguments: --lookback-hours 720
```

**Fix**: read the target script's `argparse` definitions (search for
`add_argument`) before invoking it, and pass flags it actually accepts. Changed
to `--force-full`.

**Lesson**: don't trust a wrapper's flag names — verify against the target
script's parser. A silently-failing step inside a multi-step wrapper can still
exit 0 if the wrapper only ORs step return codes loosely.

## 5. Model preflight in the wrapper (prevent "model not loaded" at fire time)

A script job that calls LM Studio fails with `HTTP 400: Invalid model identifier
"...". No matching loaded model found` when the drafter isn't loaded at fire
time. Add a preflight to the wrapper that loads + waits for the drafter before
handing off:

```python
def model_loaded(model_id):
    # query LM_STUDIO_MODELS_URL /v1/models, return model_id in loaded set
def ensure_model_loaded(model_id):
    if model_loaded(model_id):
        return True
    subprocess.run([LMS, "load", model_id], ...)   # LMS = lms.exe path
    for _ in range(30):                            # poll up to ~90s
        if model_loaded(model_id):
            return True
        time.sleep(3)
    return False

ensure_model_loaded("<drafter-model-id>")   # run before the target script
```

`lms load` returns before the model is serving, so **poll** `/v1/models` for it
to appear. The target script should ALSO keep its own loaded-model fallback as a
last resort (see `model-fallback-quality-gate.md`).

## 6. Verify under the EXACT cron execution path

Always re-run a fixed `.py` wrapper with the **native venv Python** that cron
uses (`python <wrapper>.py` from the profile scripts dir), not just from git-bash
where `/c/...` happens to work. The venv-python run is the one that exposes
`WinError 2` path bugs and the `UnboundLocalError`. Confirm exit code 0 and that
output files were written to `<profile>/cron/output/<job_id>/`.

## TL;DR checklist for a failing no_agent cron wrapper
1. Does it run `.py`? Then native venv Python → use `C:/...` paths.
2. Is the health check calling it "stale"? Verify the job's real schedule first.
3. Any var referenced later but assigned under `if not X:`? Hoist it.
4. Does the wrapper pass flags the target script actually defines? Check argparse.
5. Does it hit LM Studio? Add an `lms load` + poll preflight.
6. Re-run under venv Python and check exit code + output files.
