---
name: hermes-profile-distribution
description: "Use when packaging or publishing shareable Hermes profiles."
version: 1.0.0
author: agent
license: MIT
platforms: [linux, macos, windows]
tags: [hermes, profiles, distribution, sharing, publishing]
metadata:
  hermes:
    tags: [hermes, profiles, distribution, sharing, publishing]
    related_skills: [hermes-profile-manager, cron-troubleshooting]
---

# Hermes Profile Distributions — Package, Sanitize, Test, Publish

## When to Use
- User wants to share a Hermes profile/agent with others (friends, team, community)
- Packaging the default/meta profile or a specialized agent as an installable distribution
- Sanitizing a profile before sharing (strip secrets, personal data, machine-specific refs)
- Verifying a distribution installs correctly before sharing it
- Publishing / version-bumping a distribution repo

Native mechanism: `hermes profile install <git-url|local-dir>` — a git repo (or local dir) with `distribution.yaml` at root. Recipients run one command and get the whole agent; updates via `hermes profile update <name>` preserve their memories/sessions/.env/config.yaml. Docs: user-guide/profile-distributions.

## Distribution Layout
```
my-agent/
├── distribution.yaml    # REQUIRED manifest
├── SOUL.md              # personality / system prompt
├── config.yaml          # portable defaults (NO secrets, NO machine-specific paths)
├── skills/              # bundled skills (keep category subdirs)
├── scripts/             # only installed if declared in distribution_owned!
├── cron/                # optional — files are INERT, see pitfalls
├── mcp.json             # optional MCP server connections
├── README.md            # install + setup instructions
└── .gitignore           # create BEFORE git init (see pitfalls)
```

## Manifest (distribution.yaml)
```yaml
name: my-agent            # required; becomes the profile name on install
version: 1.0.0
description: "..."
hermes_requires: ">=0.12.0"
author: "..."
license: "MIT"
env_requires:             # drives the generated .env.EXAMPLE for installers
  - name: SOME_API_KEY
    description: "what it's for"
    required: false
distribution_owned:       # OPTIONAL but recommended — controls exactly what installs
  - SOUL.md
  - config.yaml
  - skills
  - scripts               # NOT in the installer's default owned list!
```
Default owned paths (when `distribution_owned` is omitted): SOUL.md, config.yaml, mcp.json, skills, cron, distribution.yaml. **`scripts/` is NOT included by default — declare it explicitly or your scripts silently never install.**

## Hard-Excluded (installer strips these even if an author ships them)
`auth.json`, `.env`, `memories/`, `sessions/`, `state.db*`, `logs/`, caches, `plans/`, `workspace/`, `home/`, `local/`, `hermes-agent/`, `profiles/`, `bin/`, `node_modules/`, checkpoints, sandboxes, backups. This protects INSTALLERS — authors must still use .gitignore to keep secrets out of the repo.

## Sanitization Checklist (before sharing)
1. **Secrets**: never copy `.env` or `auth.json`. `env_requires` generates `.env.EXAMPLE` on install.
2. **config.yaml**: strip `model`/`provider`/`base_url` (recipient runs `hermes setup`), `auxiliary.*` LM blocks, voice/piper paths, `custom_providers`, delivery channels, `skills.disabled`.
3. **SOUL.md**: generalize — remove fleet maps (specific profile names/purposes), business doctrine, machine paths; keep invariants, routing table, workflows generic.
4. **Skills**: grep EVERY file (not just SKILL.md) for personal terms — user-home paths, business/profile names, dated session-note files, token-audit files, custom LM Studio ports, model ids. Drop or rewrite session-note references; patch code examples to `<placeholder>` style; strip locations from frontmatter `author:` lines.
5. **Scripts**: replace hardcoded HERMES_HOME fallbacks with the portable expression:
   `(os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "hermes") if os.name == "nt" else os.path.expanduser("~/.hermes"))`
   and machine-specific ports with `os.environ.get("LMSTUDIO_URL", "http://127.0.0.1:1234/v1")`.
6. Verify with `scripts/verify_distribution.py` (below).

## Verify Before Pushing
1. Generic checks:
   `python scripts/verify_distribution.py --dist <dir> --patterns '["<personal-term>", "..."]'`
   → manifest parses, every distribution_owned path exists, no hard-excluded paths in tree, all .py compile, git hygiene.
2. **Local test install — do this ALWAYS** (docs' test recipe):
   `hermes profile install C:/path/to/dist --name <name>-test -y`
   → verify SOUL.md/config.yaml/skills/scripts landed, no `.env`/`auth.json` in the profile, `.env.EXAMPLE` generated, `hermes -p <name>-test skills list` indexes the skills, `hermes profile info <name>-test` shows the manifest.
   → `hermes profile delete <name>-test --yes`
3. Cron: distribution `cron/` files never auto-schedule (inert — see Pitfalls) — document `hermes cron create` commands in the README instead of shipping a cron/ dir.

## Publish to GitHub (no gh CLI needed — token + REST API)
See references/github-publishing.md for full commands and quirks. Summary:
1. Create repo: `curl -X POST /user/repos` (Bearer token).
2. `git remote add origin https://github.com/<user>/<repo>.git` (clean URL — never embed the token).
3. Push with Basic auth via extraheader — **Bearer does NOT work for git smart-HTTP**:
   `AUTH=$(python -c "import base64,sys; print(base64.b64encode(b'x-access-token:'+sys.argv[1].encode()).decode())" "$TOKEN")`
   `git -c http.extraheader="AUTHORIZATION: Basic $AUTH" push -u origin main --tags`
4. Verify remote: API `git/trees/<branch>?recursive=1` blob count == local `git ls-files | wc -l`; fetch raw README and grep for the URL; `git ls-remote --tags`.
5. Version bumps: edit `distribution.yaml` version → commit → tag → `push --tags`. Recipients: `hermes profile update <name>`.

## Pitfalls (all hit in production, 2026-08)
- **`scripts/` is not installed by default** — declare `distribution_owned` explicitly.
- **`cron/*.json` in a distribution is inert** — the scheduler reads only `cron/jobs.json`; files are copied but never imported. README-document cron setup.
- **`.gitignore` anchor trap**: a bare `hermes-agent/` pattern also ignores the `skills/.../hermes-agent` skill directory — anchor it: `/hermes-agent/`. (This silently dropped 22 files from the first commit.)
- **`hermes profile install /c/Users/...` fails** ("Cannot resolve distribution source") — pass Windows-style `C:/Users/...`.
- **`git archive -o <path>` mangles paths on git-for-Windows** — the zip can land INSIDE the repo (and an unanchored `*.zip` gitignore hides it from `git status`). Use shell redirection: `git archive --format=zip <tag> > /c/Users/<user>/out.zip`.
- **Cannot install as 'default'** — that's the reserved built-in root profile; recipients get a new profile (or pass `--name`).
- **Installers' config.yaml is preserved on update** unless `--force-config` — don't rely on shipped config changes reaching users who tuned theirs.
- **Distributions are unsigned** — README should state the trust model (same trust level as a browser extension).
- **Test-install env preview** marks already-set env vars "✓ set" from the shell — good UX signal that env_requires is working.

## Related
- `hermes-profile-manager` (user-owned) Phase 5b carries the complementary authoring outline — this skill is the curator-maintained operational companion. Overlap noted for the curator.
- `cron-troubleshooting` — cron diagnostics; distribution `cron/*.json` inertness is a scheduler behavior (see Pitfalls), not an installer bug.
- `scripts/verify_distribution.py` — generic pre-publish verification.
- `references/github-publishing.md` — token auth, REST repo creation, git archive quirks.
