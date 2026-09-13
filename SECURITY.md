# Security Policy

## Supported Versions

The Hermes Manager distribution is versioned via Git tags. All published
releases receive security updates for the latest minor version. Older
tagged releases are **not** guaranteed to receive patches — upgrade if you're
running an old release and need a fix.

| Version | Supported          |
| ------- | ------------------ |
| main    | ✅ Yes             |
| v0.x.x  | ⚠️ Last tagged only |

## Reporting a Vulnerability

If you discover a security vulnerability in Hermes Manager, please report it
responsibly. **Do not open a public GitHub issue.**

### How to Report

Email your findings to the maintainer with:

- A clear description of the vulnerability and its impact
- Steps to reproduce (PoC if possible)
- The version/commit you tested against

### What to Expect

| Phase | Timeline |
|-------|----------|
| Initial triage | Within 48 hours |
| Confirmation / request for more info | Within 7 days |
| Fix developed & released | Varies by severity |

You will receive a response within **48 hours**. If the vulnerability is
confirmed, we'll work with you on a fix and coordinate the release. We
ask that you do not publicly disclose details until a patch is available.

### Scope

In scope: code in this repository (skills/, scripts/, config files) that could
expose user data or compromise their Hermes Agent instance.

Out of scope: issues with third-party services (model providers, API endpoints) —
report those to the respective vendors.