# Backlog — Sprints 1 through 6

Placeholder outlines for the six sprints after Trust Foundation. Each
one is a **placeholder** — the CPO will write the full sprint charter
in a dedicated `../sprint-N-*/README.md` at kick-off, informed by
what actually landed in the prior sprint. Nothing here is committed
until the CPO opens the sprint.

The sprint order mirrors the CEO's roadmap message: Trust → Access →
Real-Trading → Stickiness → Polish → Compliance → Sales. **Trust
before access. Access before stickiness.** Do not reorder without
CEO sign-off.

---

## Sprint 1 — Access (target: 2026-08-05 → 2026-08-25)

**Goal:** Turn viewers into users. Real accounts, per-user data,
first-time setup.

Features (indicative, refined at kickoff):

| ID | Title | Priority |
|---|---|---|
| F006 | User accounts (sign-up / login / password) | P0 |
| F007 | Per-user data isolation (own account settings & saved views) | P0 |
| F008 | Broker connection wizard (MT5 first — 80 % of retail forex) | P0 |
| F009 | First-time setup flow (broker → risk prefs → pair choice) | P0 |
| F010 | Marketing landing page at `/welcome` (separate from hub) | P1 |

Standby roles that activate this sprint: DevOps (public hosting),
Security (auth / secrets), Sales (waitlist prep).

Non-goals: multi-broker beyond MT5, native mobile app, payments.

---

## Sprint 2 — Real-Trading (target: 2026-08-26 → 2026-09-22)

**Goal:** What users actually pay for — control over trading behaviour.

| ID | Title | Priority |
|---|---|---|
| F011 | Risk management UI (max daily loss, max DD, max positions, max size) | P0 |
| F012 | Trade approval mode (every proposal → notification → user OK) | P0 |
| F013 | Alerts & notifications: push + SMS + email + Telegram | P1 |
| F014 | Full P&L reporting (D/W/M/YTD, per-strategy, per-pair, per-character) | P0 |
| F015 | Trade journal (per-trade page with reasoning + screenshots + tags) | P1 |

Sprint 2 does NOT enable real broker orders on this repo — that's
a hard non-negotiable (see `../protocols/escalation.md` §5).
"Real-trading features" means the UI + control layer; wiring to a
user's own broker is still gated by the safety hierarchy.

---

## Sprint 3 — Stickiness / Differentiation (target: 2026-09-23 → 2026-10-27)

**Goal:** Keep users past month 3. Lean fully into the Blue Lock
metaphor as a compounding IP asset.

| ID | Title | Priority |
|---|---|---|
| F016 | Strategy marketplace — surface AC pipeline arms (A1 baseline, widenings, B-experiments) as subscribable strategies | P0 |
| F017 | Character development / seasons — quarterly stats, player-of-the-season, evolution logs | P0 |
| F018 | Match highlights — auto-generated shareable graphics ("Bachira: 24 goals this month") | P1 |
| F019 | Public leaderboards (opt-in) — best-performing squads across users | P1 |
| F020 | Community forum / Discord — feature requests, strategy discussions | P1 |

Copy trading and revenue-share models are Sprint 4+.

---

## Sprint 4 — Polish (target: 2026-10-28 → 2026-11-24)

**Goal:** The details that separate $50/month from $500/month.

| ID | Title | Priority |
|---|---|---|
| F021 | Command palette (Ctrl+K) — search any trade, player, date, jump anywhere | P1 |
| F022 | Keyboard shortcuts (`?` help, `/` search, `g h` hub, `g v` v2, etc.) | P1 |
| F023 | Dark / light mode toggle | P1 |
| F024 | Accessibility pass — colour-blind palette review, ARIA labels, keyboard nav | P0 |
| F025 | Custom themes — per-user colour schemes | P2 |
| F026 | Full-text search across events, trades, thoughts, decision feeds | P1 |
| F027 | Uptime status page — `status.<domain>` | P0 |
| F028 | Robust loading / error → recovery paths ("[Retry] or [Contact support]") — extends F005 | P1 |

---

## Sprint 5 — Compliance & Security (target: 2026-11-25 → 2026-12-22)

**Goal:** Required for the "real" (paid, at-scale) version.

| ID | Title | Priority |
|---|---|---|
| F029 | 2FA (TOTP + optional WebAuthn) | P0 |
| F030 | Audit log — every user action logged, user-viewable | P0 |
| F031 | Encryption at rest — broker credentials in vault, not `platform.toml` | P0 |
| F032 | Secrets management — env / AWS Secrets / self-hosted vault | P0 |
| F033 | GDPR/CCPA — data export + account deletion flows | P0 |
| F034 | SOC 2 track kick-off — controls inventory + owner assignment | P1 |
| F035 | Penetration test (external, before Sprint 6 launches paid tiers) | P0 |

Legal + Security take the lead this sprint; Frontend / Backend do
compliance-adjacent implementation only.

---

## Sprint 6 — Sales (target: 2026-12-23 → 2027-01-31)

**Goal:** Turn a compliant, sticky product into revenue.

| ID | Title | Priority |
|---|---|---|
| F036 | Pricing tiers definition + display | P0 |
| F037 | Billing infrastructure (Stripe or equivalent) | P0 |
| F038 | Free trial + upgrade flow | P0 |
| F039 | Referral / affiliate program | P1 |
| F040 | Onboarding email sequence + in-product tour v2 | P1 |
| F041 | Enterprise / broker-integration sales collateral | P2 |

Sales role goes live full-time this sprint; Support role activates
for post-conversion onboarding.

---

## Deferred / parked (not in any planned sprint)

Ideas raised in the CEO's roadmap message that we consciously
deferred:

- **Multi-broker beyond MT5** (OANDA, MT4, IBKR) — Sprint 7+ after
  MT5-only adoption data proves demand.
- **Native mobile app** — mobile-responsive web (F004) plus PWA
  (Sprint 4 candidate) should suffice through Sprint 6.
- **Multi-asset (crypto, stocks)** — the forex-zones + squad
  ensemble is a niche we can own; do NOT spread thin. Any
  crypto / stocks discussion escalates immediately.
- **Copy trading (mirror another user's squad)** — Sprint 7+ once
  we have a user base to mirror.
- **Character AI voice generation** — was floated as a "wow" idea;
  parked as brand-risky and non-differentiating.

---

## Backlog discipline

- **The backlog is not a contract.** Any Sprint N charter can
  reorder or replace items when opened, informed by what Sprint
  N-1 revealed.
- **Ideas go in `company/backlog/ideas.md`** (created on demand),
  not into a future sprint's placeholder without CPO review.
- **The CEO can move items between sprints** at any time; the CPO
  logs the shift in `decisions_log.md`.
- **A sprint that finishes early does NOT auto-pull the next
  sprint's work.** Slack becomes tech-debt cleanup, backlog
  grooming, or bug bash — decided by CPO.
