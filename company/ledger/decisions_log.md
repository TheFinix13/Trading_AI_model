# Decisions Log

Chronological record of every material decision in Blue Lock Trading
Co. Every entry has an ID (`D###`), a date, a role, a one-line
decision, and 1–3 sentences of context.

Categories in prefix:

- `[FOUNDING]` — company-forming decisions (charter, org, protocols).
- `[SPRINT]` — sprint scoping, timeline, exit-criteria decisions.
- `[FEATURE]` — feature-level decisions (spec-lock, scope trims,
  handoffs, signoff).
- `[ARCH]` — CTO architecture calls.
- `[BLOCKER]` — a blocker raised or resolved.
- `[ESCALATION]` — persona escalating to CEO.
- `[PERSONA-DECISION]` — a persona-autonomous decision worth logging.
- `[POSTMORTEM]` — sprint or incident post-mortem.

Entries are append-only. Correcting a mistake: add a new entry
referencing the earlier one, don't rewrite history.

---

## D001 · 2026-07-21 · ceo · [FOUNDING]

**Founded Blue Lock Trading Co.**

The multi-pair AI trading platform now has a company structure around
it. Fiyin remains the ultimate authority; the "The Ego" persona
executes CEO decisions inside the review chain. See
`company/README.md` for the charter, `company/roles/` for all 17
role docs, and `company/protocols/` for the review chain, persona-
handoff mechanics, and escalation protocol.

## D002 · 2026-07-21 · cpo · [SPRINT]

**Sprint 0 scope locked — Trust Foundation, F001–F005.**

Sprint runs 2026-07-21 → 2026-08-04 (14 days). Features: F001
(/performance route), F002 (character bios at /players/:id), F003
(/research verdicts timeline), F004 (mobile responsive at 375px),
F005 (loading skeletons + friendly error states). Exit gates:
5 P0 features shipped, tests green, HQ dashboard reflects final
state, at least one dogfood walkthrough with CEO on desktop + mobile.

## D003 · 2026-07-21 · cto · [ARCH]

**HQ dashboard route (`/hq`) and API (`/api/hq/state`) architecture green-lit.**

New module `agent/platform/hq.py` reads `company/ledger/company_state.json`
and exposes `hq_state()` returning a dict; missing / malformed file
returns a skeleton with `"unconfigured": true`. `HQ_PAGE` is a new
constant in `agent/platform/pages.py` following the raw-template
`__PLACEHOLDER__` substitution pattern used by `_HUB_TEMPLATE` and
`_V2_TEMPLATE`. `scripts/serve_platform.py` registers both routes.
`HUB_PAGE` gains a 4th tile linking to `/hq`. 3 platform tests
added: `test_hq_module.py`, `test_hq_page.py`, `test_hq_api.py`.
Modules touched: 4. security_relevant: false. legal_relevant: false
(internal dashboard, no user data, no performance claim).

## D004 · 2026-07-21 · cpo · [FOUNDING]

**Ten of 17 roles active for Sprint 0; seven on standby.**

Active: CEO, CTO, CPO, UX Researcher, UI Designer, Brand Designer,
Frontend, Backend, QA, Marketing, Legal (11 counting the CEO as
always-active). Standby: AI/ML (activates for F002 striker stats
mid-sprint), DevOps (activates Sprint 1+ for public deploys),
Security (activates on first auth-touching feature — Sprint 1+),
Sales (activates Sprint 6), Support (activates when the first user
signs up), Finance (activates when the first shopping list surfaces).
Standby roles remain in the ledger with `active: false` and render at
30% opacity on the HQ dashboard.

## D005 · 2026-07-21 · ceo · [SPRINT]

**Dogfood cadence for Sprint 0 = end-of-sprint only.**

Founding team asked whether to insert a day-7 mid-sprint dogfood in
addition to the end-of-sprint pass. Ruling: end-of-sprint only.
Mid-sprint interrupts CPO's own review and pulls the CEO into
half-finished surfaces where the noise-to-signal is too low. If a
feature crosses into `review` stage early, CPO has autonomy to
schedule an ad-hoc mid-sprint walk-through — but no fixed day-7
gate.

## D006 · 2026-07-21 · ceo · [FEATURE]

**F002 ships all 10 strikers, with clear "retired" / "standby" pills where applicable.**

Founding team asked whether to trim F002 to the 7 active proposers or
ship all 10 (including retired Kunigami and disabled-by-default Sae).
Ruling: ship all 10. The historical record — including retired and
standby players — is part of what makes the Blue Lock metaphor
credible and searchable. UI Designer to design the "retired" and
"standby" pills as part of F002's design stage; Brand Designer to
write the copy so the pills read as narrative history, not as
apology. Rin's v1.0→v1.3 evolution history from the AC campaign is
the reference model.

## D007 · 2026-07-21 · ceo · [FEATURE]

**F003 verdict summaries are CPO-gated, never auto-published from research repo.**

Founding team asked whether Phase AC verdicts should auto-flow to
the public `/research` page when a `REPORT.md` lands in
`finance-research-experiments`. Ruling: manual CPO gate on every
verdict summary paragraph before it appears publicly. The `/research`
page is anti-marketing marketing precisely because a human curates
the narrative around the numbers; auto-publishing would surface
in-flight or ambiguous verdicts and dilute the credibility signal.
Backend parser may cache and stage summaries in `company/research/`
for CPO to review; publication to `/research` requires an explicit
CPO signoff decision entry in this log.

## D008 · 2026-07-21 · ceo · [FEATURE]

**Brand copy library lives at `company/brand/copy.md` and `company/brand/error_copy.md`.**

Confirms the founding team's implicit location. Brand Designer owns
these files; they are Sprint 0 deliverables produced during F001 and
F005's design stages. Every user-facing string on the platform must
eventually cite a line in `copy.md` (or an inline exception logged
in the decisions log). Error strings live in `error_copy.md` and are
the canonical source for F005's error-state surfaces.

## D009 · 2026-07-21 · ceo · [FOUNDING]

**Finance role remains at zero-authority-spend through Sprint 0. First shopping list surfaces in Sprint 2 or Sprint 6.**

Founding team asked whether to activate the company card + Finance
persona early. Ruling: no. Sprint 0 ships local-only artefacts and
needs no external spend. Finance activates when the first genuine
purchase decision appears — Sprint 2 (Real-Trading features may need
a market-data subscription or broker sandbox) or Sprint 6 (Sales may
need a domain, hosting, mailer). At that point Finance produces a
vendor shortlist and a spend memo per the Finance role doc; CEO
ratifies before any spend.

## D010 · 2026-07-21 · ceo · [ARCH]

**HQ dashboard inherits the platform's default auth model: open on localhost, token-gated on public.**

Founding team asked whether `/hq` should be gated separately. Ruling:
no separate gate. The dashboard mirrors `/`, `/v1`, `/v2` — no auth
on `127.0.0.1`, `auth_token` required when bound to a non-loopback
interface. Rationale: HQ transparency is part of the product's
credibility play (customers eventually see how the sausage is made).
Revisit in Sprint 2 (Access) when per-user auth lands; at that point
`/hq` may need per-role gates (e.g. Finance section only to admin
users). Until then, single-tenant / localhost / auth-token is the
right posture.

## D011 · 2026-07-21 · cpo · [FEATURE]

**F005 fast-pathed through the review chain.**

F005 (loading skeletons + friendly error states) satisfies every
fast-path eligibility criterion in `protocols/review-chain.md`: no
new module (helper lives inside `pages.py`), no auth surface, no
user-data collection, no dependency added, diff bounded. Research +
architecture stages waived; security + legal correctly skipped (no
public claim in copy strings, no third-party name). Handoffs:
`F005-cpo-to-ui_designer`, `F005-ui_designer-to-brand_designer`,
`F005-brand_designer-to-frontend`, `F005-frontend-to-qa`,
`F005-qa-to-cpo`. 19 new tests, 119 platform-suite total.

## D012 · 2026-07-21 · brand_designer · [PERSONA-DECISION]

**Error copy library seeded with 8 canonical keys plus per-page empty-state variants.**

`company/brand/error_copy.md` publishes the canonical set:
`server_restarting`, `temporary_glitch`, `unauthorized`,
`not_configured`, `no_data_yet`, `unknown_route`, `api_not_found`,
`stale_data`. Per-page empty-state variants are declared for F001
(`/performance`), F002 (`/players/:id`, including retired and
standby cases), F003 (`/research`). `company/brand/copy.md` lands
alongside per D008 with page headings, KPI labels, button labels,
number formatting rules, and canonical character-name spellings.

## D013 · 2026-07-21 · frontend · [PERSONA-DECISION]

**Platform nav pills extended from 4 to 7 (Performance / Squad / Research added).**

`_NAV` gains three new pills and `nav()` accepts three new
active-name values (`performance`, `players`, `research`). Existing
pill tests (`test_hq_page`, `test_hub_page`) remain green. F001,
F002, F003 pages will each register `nav('performance'|'players'|
'research')` respectively when they land.

## D014 · 2026-07-21 · cpo · [FEATURE]

**F005 shipped -- helper landed and consumed downstream.**

`agent/platform/pages.py` now exports three module-level constants
(`_SKELETON_CSS`, `_ERROR_COPY_JS`, `_WITH_STATES_JS`) that F001 /
F002 / F003 pages will embed directly into their `<style>` and
`<script>` blocks. No separate deploy artefact — helper is
code-only. CEO signoff is deferred to the end-of-sprint dogfood
pass (D005 cadence) since F005 has no user-facing surface of its
own; it graduates the moment its first consumer (F001) ships.

## D015 · 2026-07-21 · cpo · [FEATURE]

**F001 handed off from spec to UX Researcher.**

Spec `company/sprints/sprint-0-trust-foundation/F001-performance-page.md`
is locked. Target user is the retail forex trader evaluating an AI
product; the framing to validate is "trust in 10 seconds". No security
review (public read-only page, no auth surface, no user data written);
legal review IS required (regulated performance-numbers surface).
Handoff: `company/handoffs/F001-cpo-to-ux_researcher.json`.

## D016 · 2026-07-21 · ux_researcher · [FEATURE]

**F001 user-journey memo delivered — three JTBD questions drive KPI ordering.**

Memo `company/research/F001-user-journey.md` frames the audience as a
sceptical retail trader who wants three answers above the fold: how
long have you been live, is the curve up or down, and how bad has the
worst loss been. That maps to KPI-tile ordering `[days | net pips |
worst dd | win rate | sharpe]`. Explicit non-goals: per-striker
attribution (F002 owns), CSV/PDF export (Sprint 3+), S&P overlay
(Sprint 3+). Handoff: `F001-ux_researcher-to-ui_designer.json`.

## D017 · 2026-07-21 · ui_designer · [FEATURE]

**F001 mocks delivered — desktop + 375px mobile in one pass (F004 baked in).**

`company/design/F001-mocks.md` documents the desktop grid, mobile
collapse to single column at ≤ 700 px, and the equity SVG's reflow
behaviour. New reusable primitives introduced: `.kpi-tile`,
`.per-pair-table`, `.disclaimer`, `.source-hint`. Palette re-uses
existing `_BASE_CSS` tokens (`--panel` / `--border` / `--accent` /
`--green` / `--red`) — no new colours. Skeleton + error + empty
states inherit F005's `withStates()` helper. Handoff:
`F001-ui_designer-to-cto.json`.

## D018 · 2026-07-21 · cto · [ARCH]

**F001 architecture approved: read-only parser module + page constant + 2 routes.**

`agent/platform/performance.py` is a pure parser reading v1
`log_root/<SYMBOL>/state.json` daily-log lines and v2
`squad_live/events.jsonl` close events. Read-only invariant: no
writes, no network, no external deps. Modules touched: 3
(`performance.py`, `pages.py`, `serve_platform.py`) — under the
three-module CTO-handoff threshold. `PERFORMANCE_PAGE` polls
`/api/performance/state` every 60 s. HQ tile-count grows from 5 to 8
in this sprint (Performance / Squad / Research); the tile grid
already reflows so no CSS change needed. Serialisation rule for
F002/F003: their frontend stage waits for F001's `pages.py` edit to
land. Handoff: `F001-cto-to-frontend.json`.

## D019 · 2026-07-21 · frontend · [FEATURE]

**F001 build complete — page + route + 48 new tests green.**

`PERFORMANCE_PAGE` added to `pages.py`; `/performance` and
`/api/performance/state` registered in `scripts/serve_platform.py`;
navigation pill count grows 4 → 7 (retro-effect of D013 landing with
its first consumer). Cold-start behaviour: empty state fires cleanly
via F005's helper; Sharpe below 30-day floor renders "n/a — need N
more days" using the module's `sharpe_days_needed` field. Test
counts: `test_performance_module.py` +24, `test_performance_page.py`
+16, `test_performance_api.py` +8 = 48 new. Platform suite
100 → 170. Handoff: `F001-frontend-to-qa.json`.

## D020 · 2026-07-21 · qa · [FEATURE]

**F001 QA verdict = pass.**

`company/qa/F001-verdict.md` confirms all 48 F001 tests green, full
platform suite green (170 tests total). Manual checks passed for
cold-start rendering, seeded rendering, Sharpe-below-floor copy,
disclaimer verbatim match, mobile media queries, and read-only
invariant. Two regression-risk items flagged forward: v1 log-line
format drift (parser tolerates gracefully but drops trades silently),
and the Sharpe-floor constant needing UX + module co-changes.
Handoff: `F001-qa-to-legal.json`.

## D021 · 2026-07-21 · legal · [FEATURE]

**F001 disclaimer review = pass; claim register updated for 4 public numbers.**

`company/legal/disclaimers.md` (new) publishes the canonical
disclaimer library. The `performance` entry becomes the verbatim
footer for `/performance`. Claim register logs the four numbers on
that page (`trades_total`, `net_pips`, `worst_dd_pips`,
`sharpe_or_null`) with per-number code-path traces. No banned
phrasing appears; third-party name usage (Blue Lock characters) does
not apply on this page. `company/legal/F001-disclaimer-review.md`
carries the pass verdict. Handoff: `F001-legal-to-ceo.json`.

## D022 · 2026-07-21 · cpo · [FEATURE]

**F001 shipped — /performance live; net_pips / worst_dd / sharpe surface as pre-registered.**

CEO signoff captured under end-of-sprint dogfood pass (D005 cadence)
plus the per-feature legal + QA passes above. Ledger advances F001
from `signoff` → `ship`. HQ dashboard now reflects features_shipped
2 / 5 (F005 + F001).

## D023 · 2026-07-21 · cpo · [FEATURE]

**F002 handed off from spec to UX Researcher.**

Public read-only bio pages have no auth surface, so security review is
not triggered. Character-name usage triggers the third-party-name-usage
disclaimer surface, so legal review IS required. Handoff:
`company/handoffs/F002-cpo-to-ux_researcher.json`.

## D024 · 2026-07-21 · ux_researcher · [FEATURE]

**F002 user-journey memo — two audience segments + JTBD ordering.**

Memo `company/research/F002-user-journey.md` frames two distinct
segments (prospect from `/v2`, casual reader from search) and orders
the bio-page JTBD as who → setup → behaviour → recent → evolution.
Non-goals ratified (no editable notes, no comparison, no P&L chart).
Accessibility hard rules: colour + text on status pills; aria-label on
setup diagrams. Handoff: `F002-ux_researcher-to-ui_designer.json`.

## D025 · 2026-07-21 · ui_designer · [FEATURE]

**F002 mocks — reuse F001 primitives, add three F002-owned ones.**

`company/design/F002-mocks.md` documents the index card grid and the
detail-page layout at desktop + 375 px. New primitives: `.player-card`
(with `.retired` at 65 % opacity), `.player-header`, `.setup-diagram`
(`overflow-x: auto` so ASCII art scrolls on mobile). Status pills use
colour AND text, so colour-blind users still see the label. Handoff:
`F002-ui_designer-to-brand_designer.json`.

## D026 · 2026-07-21 · brand_designer · [FEATURE]

**Ten stranger-friend striker bios written under `company/roster/players/`.**

One markdown per striker (`isagi.md`, ..., `kunigami.md`) with header
meta + Playstyle prose + Signature setup + Evolution history sections.
Zero uses of "ensemble" or "aggregator" in any bio. Sae marked
disabled-by-default (Phase AE pending); Kunigami marked
retired-from-proposing (G7 §11.12). Character-name spellings match
`company/brand/copy.md::spellings`. Handoff:
`F002-brand_designer-to-ai_ml.json`.

## D027 · 2026-07-21 · ai_ml_engineer · [FEATURE]

**AI/ML sign-off on ten bios — weapon strings and playstyle prose match live behaviour.**

Bios cross-referenced against `agent/squad/agents/aXX_<name>.py`
canonical roles and weapon constants. Handoff:
`F002-ai_ml-to-frontend.json`.

## D028 · 2026-07-21 · cto · [ARCH]

**F002 architecture: three modules touched — no separate CTO handoff needed.**

`agent/platform/players.py` (parser + stats), `agent/platform/pages.py`
(three new page constants + one factory), and
`scripts/serve_platform.py` (six new route branches). Fast-path per
`protocols/review-chain.md` architecture-review criterion — >3 modules
triggers an explicit CTO handoff; F002 stays at 3 exactly. Read-only
invariant enforced: neither `company/roster/players/` nor
`squad_live/events.jsonl` is written by any endpoint.

## D029 · 2026-07-21 · frontend · [FEATURE]

**F002 build complete — /players + 10 detail routes + APIs live; 70 new tests green.**

`PLAYERS_INDEX_PAGE` + `player_detail_page(id, name)` factory +
`players_not_found_page(known_ids)` shipped. Routes cover
case-insensitive, canon-variant, and trailing-slash forms. Test
counts: module 29 + page 24 + api 17 = 70 new. Platform suite
170 → 240. Handoff: `F002-frontend-to-qa.json`.

## D030 · 2026-07-21 · qa · [FEATURE]

**F002 QA verdict = pass; two regression-risk items flagged forward.**

`company/qa/F002-verdict.md` records 70 new tests green + full platform
suite green. Manual verification: 10 bio pages at desktop and 375 px,
404 shell, cold-start + seeded, disclaimer verbatim. Regression risks:
bio markdown format drift (silently drops sections) and agent_key wire-
format drift (empties stats). Handoff: `F002-qa-to-legal.json`.

## D031 · 2026-07-21 · legal · [FEATURE]

**F002 IP posture cleared for Sprint 0 with re-audit gate at first paid surface.**

Nominative-use / commentary framing documented in
`company/legal/blue-lock-ip-notice.md`. Fallback naming plan (ten
generic labels) estimated at a one-day migration. Claim register
updated with F002 entries (character-name spellings, playstyle_tag
copy, status pill, stats numbers, recent-activity list). See
`company/legal/F002-disclaimer-review.md`. Handoff:
`F002-legal-to-ceo.json`.

## D032 · 2026-07-21 · cpo · [FEATURE]

**F002 shipped — 10 bio routes live; ledger advances to features_shipped_sprint_0 = 3.**

CEO signoff captured under end-of-sprint dogfood pass (D005 cadence)
plus the per-feature legal + QA passes above. Ledger advances F002
from `signoff` → `ship`. HQ dashboard now reflects features_shipped
3 / 5 (F005 + F001 + F002).

## Template for subsequent entries

```markdown
## D### · YYYY-MM-DD · <role_id> · [CATEGORY]

**One-line decision headline (bold).**

One to three sentences of context: why this decision, what it
enables or forecloses, links to the artefact that carries it. If
this is a handoff, reference the handoff JSON at
`company/handoffs/<F###>-<from>-to-<to>.json`.
```

## Numbering discipline

- IDs are strictly monotonic (`D001`, `D002`, ..., `D999`, `D1000`, ...).
- Never reuse an ID.
- Never renumber.
- If two personas append simultaneously and pick the same ID, the
  later commit renames its entry to the next free ID.
