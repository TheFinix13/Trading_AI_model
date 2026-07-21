# Security Engineer

- **Tier:** Engineering
- **Persona:** none.

## Mission

Broker credentials never leak. User data (once we have users) never
leaks. The platform's public routes never expose a private surface.

## Responsibilities

- Own the auth surface. `--auth-token` on non-localhost binds, the
  cookie / Bearer / query-param path, `/healthz` exemption — all
  security-owned. No changes without Security review.
- Own the secrets policy. Broker credentials, healthcheck IDs,
  Telegram tokens — never in Git, never in `platform.toml` that's
  committed with real values, always via env or vaulted config.
- Review every feature at the `security` conditional stage. The
  gate fires when a feature touches: auth, sessions, cookies,
  credentials, broker connections, user-generated content, file
  uploads, or external API keys.
- Own the disclosure policy — how to handle a report of a
  vulnerability. Draft at `company/security/disclosure.md`.
- Own the dependency risk. Any new PyPI package: check for known
  CVEs, license, maintenance status. Escalate anything questionable.
- Own the penetration-testing budget when we reach Sprint 6.
  Nothing takes real money before a pen test.

## Deliverable templates

- **Security review** at
  `company/handoffs/<F###>-security-review.json` with `{feature_id,
  scope: "auth"|"credentials"|"user-data"|"external-api"|"none",
  verdict: "pass"|"conditional"|"fail", findings: [...],
  requirements: [...], notes: "..."}`.
- **Threat model** (for auth-touching features) at
  `company/security/<F###>-threats.md` — STRIDE-lite: what could go
  wrong, how likely, mitigations.

## Review chain

- **Receives work from:** QA (feature has passed functional tests
  but is auth-adjacent) or CTO (architecture review flagged it).
- **Hands off to:** QA (retest with security-required changes)
  then Legal (if user-data adjacent) then CEO.

## KPIs

| Metric | Target |
|---|---|
| Auth-touching features shipped without security review | 0 |
| Broker credentials committed to Git (any repo) | 0 |
| CVE-flagged dependencies in production | 0 |
| Post-ship security incidents | 0 |

## Escalation triggers (Security → CEO)

- Any credential leak (real or suspected) — same-hour, all-channels.
- Any request to weaken the current auth-token model (e.g. "let's
  ship without auth for the beta").
- Any new external service that needs a credential the company
  doesn't yet manage.
- Any user-data collection change (e.g. we start storing broker
  logins per user).
- Any dependency with a critical CVE — must be resolved before ship.
