# Publishing a Distribution to GitHub (PAT auth, no gh CLI)

Verified end-to-end 2026-08-10 publishing the `hermes-manager` distribution. All
commands use the GITHUB_TOKEN from the default profile `.env` — never paste the
token into a URL or persist it in `.git/config`. Replace `<owner>/<repo>` with
your own GitHub repo.

## 1. Create the repo (REST API, Bearer auth)

```bash
TOKEN=$(grep "^GITHUB_TOKEN=" "$HERMES_HOME/.env" | cut -d= -f2- | tr -d '"' | tr -d "'")
# confirm token works + see scopes (classic PAT with `repo` scope shows in X-OAuth-Scopes)
curl -sI -H "Authorization: Bearer $TOKEN" https://api.github.com/user | grep -i x-oauth-scopes

curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Accept: application/vnd.github+json" \
  https://api.github.com/user/repos \
  -d '{"name":"my-agent","description":"...","public":true,"has_issues":true,"has_wiki":false}'
```

## 2. THE gotcha: Bearer vs Basic for git push

- **REST API** (`api.github.com`): accepts `Authorization: Bearer <token>`.
- **git smart-HTTP** (the `git push` transport): does NOT accept Bearer — it wants
  HTTP Basic with the token as the password (`x-access-token` as username).
  Pushing with the Bearer extraheader fails with `remote: invalid credentials`.

Correct push — Basic auth passed as a per-command extraheader so the remote URL
stays clean and the token never lands in `.git/config`:

```bash
cd <dist-repo>
git remote add origin https://github.com/<user>/<repo>.git
AUTH=$(python -c "import base64,sys; print(base64.b64encode(b'x-access-token:'+sys.argv[1].encode()).decode())" "$TOKEN")
git -c http.extraheader="AUTHORIZATION: Basic $AUTH" push -u origin main --tags
```

`gh` CLI is not required; if it's installed, `gh repo create <repo> --public --source . --push` is the alternative.

## 3. Verify the push (don't trust the exit code alone)

```bash
# blob count on remote == local tracked file count
git ls-files | wc -l
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.github.com/repos/<user>/<repo>/git/trees/main?recursive=1" \
  | python -c "import json,sys; d=json.load(sys.stdin); print(len([x for x in d['tree'] if x['type']=='blob']), 'blobs')"

# README actually updated (no placeholder URLs left)
curl -s "https://raw.githubusercontent.com/<user>/<repo>/main/README.md" | grep -c "<you>"

# tag present
git ls-remote --tags origin
```

## 4. Windows path quirks (both hit in the same session)

- **`hermes profile install /c/Users/...`** → `Error: Cannot resolve distribution
  source` — the installer wants a native Windows path: `hermes profile install C:/Users/<user>/<dir> --name <name>-test -y`.
- **`git archive -o <path>`** mangles the output path on git-for-Windows — the zip
  can be written INSIDE the repo instead of where you asked (and an unanchored
  `*.zip` gitignore entry then hides it from `git status`). Always use shell
  redirection instead:
  ```bash
  git archive --format=zip <tag> > /c/Users/<user>/<repo>-<tag>.zip
  ```
  Verify with Python afterwards: `zipfile.ZipFile(p).testzip()`.

## 5. Version bumps (update flow for recipients)

1. Edit `distribution.yaml`: bump `version:`.
2. Commit, tag: `git tag v1.1.0`, push: `git -c http.extraheader="AUTHORIZATION: Basic $AUTH" push origin main --tags`.
3. Recipients run `hermes profile update <name>` — config.yaml preserved unless `--force-config`.
4. `hermes profile info <name>` shows installed version/source; `git ls-remote --tags <url>` shows latest.

## 6. Amending before first push

If nothing is pushed yet, `git commit --amend` + `git tag -f` is safe and keeps
the vX.Y.Z story clean (e.g. fixing the commit author to match the account:
`git -c user.name="<Name>" -c user.email="<name>@users.noreply.github.com>" commit --amend --author="<Name> <email>" --no-edit`).
