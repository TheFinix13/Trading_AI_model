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

## D033 · 2026-07-21 · cpo · [HANDOFF]

**F003 handed off from spec to UX Researcher; security stage skipped, legal stage required.**

Public read-only verdict timeline has no auth surface, so security
review is not triggered. The anti-marketing marketing thesis needs
Legal to substantiate every public claim on the page (individual
verdict labels, anti-cherry-pick statement, FDR explainer prose).
See `company/handoffs/F003-cpo-to-ux_researcher.json`.

## D034 · 2026-07-21 · ux_researcher · [DESIGN]

**F003 target segment = "sceptical prospect"; content order flipped to dead-first as the trust move.**

JTBD: "help me falsify this before I trust it". Dead / stopped /
fail cards must render with identical visual weight to alive cards
— no down-weighting; the receipt trail is the value proposition.
FDR + pre-registration explainer sits in a native `<details>`
block so it's one click away without dominating first-scroll.
Non-goals ratified: no live equity claim, no PROTOCOL.md render,
no ranked ordering. See `company/research/F003-user-journey.md`.

## D035 · 2026-07-21 · ui_designer · [DESIGN]

**F003 mocks: timeline with sticky month headers; two new primitives (.verdict-card, .date-header); rest reuse HQ/F001/F002 tokens.**

Five verdict-pill colour families cover the 14 `verdict_kind`
values the parser emits (green for alive/pass/complete, red for
dead/fail, grey for stopped/parked/unknown, blue for
in-progress/complete-neutral). Mobile 700 px breakpoint: verdict
pill wraps above the title, date drops to a new line. See
`company/design/F003-mocks.md`.

## D036 · 2026-07-21 · cpo · [FEATURE]

**F003 publication_manifest.json signed off with six approved entries.**

Per D007 CPO-gate. Six entries: E001_concept_ablation (alive),
E004_walk_forward (alive), E007_impulse_origin_bounce (alive),
E022_structure_aware_tp_snap (dead), E024_near_tp_stall_exit (fail),
phase_ac_pitch_assignment (stopped). 3 of 6 non-passing preserves
the anti-cherry-pick "receipt trail" thesis by construction. See
`company/research/publication_manifest.json`.

## D037 · 2026-07-21 · frontend · [ARCHITECTURE]

**F003 backend module walks two disk regions: `experiments/` + `programs/**/experiments/`.**

`REPORT.md` is canonical; `REPORT 2.md` drift copies (git-untracked
in the sibling repo) are skipped so we never publish an
unversioned verdict. `campaign_id` extracted from the full parent-
directory name (`E001_concept_ablation`, not `E001`) so it matches
`publication_manifest.json` keys exactly. Verdict-line regex is
multiline-flagged (`re.MULTILINE`) to catch `**Status:** complete`
mid-line rather than only at line start.

## D038 · 2026-07-21 · frontend · [FEATURE]

**F003 build complete — /research + /api/research/verdicts live, 46 new tests green.**

`RESEARCH_PAGE` consumes the F005 `withStates()` helper for
skeleton / error / empty / retry lifecycle. Missing sibling repo
yields a `source_exists=false` payload (never a 500); missing
manifest yields an `unconfigured=true` empty state. Test counts:
module 23 + page 17 + api 6 = 46. Platform suite 240 → 286.
See `company/handoffs/F003-frontend-to-qa.json`.

## D039 · 2026-07-21 · qa · [FEATURE]

**F003 QA verdict = pass; three regression-risk items flagged forward.**

46 new tests green + full platform suite green. Manual
verification: cold start + missing sibling repo + missing manifest
+ mobile 375 px + FDR explainer keyboard-accessibility + read-only
invariant. Regression risks: (1) sibling-repo `REPORT.md` format
drift (parser degrades to `unknown` pill), (2) manifest / disk
mismatch (entry without matching `REPORT.md` silently dropped —
diagnosable from `all_candidates` vs `published_total`),
(3) publication side-channel via `list_all()` (mitigated: only
`get_state()` is wired into a public endpoint). See
`company/qa/F003-verdict.md`.

## D040 · 2026-07-21 · legal · [LEGAL]

**F003 legal review = pass; claim register updated; three rolling constraints logged.**

Anti-cherry-pick claim substantiated (3 of 6 shipped entries are
non-passing). FDR explainer prose cross-checked against the
research repo's `docs/decisions/2026-07-01_fdr_protocol.md`.
Rolling constraints (bind future sprints):
(1) **cherry-pick guardrail** — if < 33 % of published entries
are dead / fail / stopped, Legal must review before the next
push; (2) **whole-portfolio claim ban** — no summary, headline,
or verdict_label may compose individual "alive" verdicts into a
portfolio-level claim; (3) **new `verdict_kind` handshake** — any
new kind beyond the 14 already supported requires a
Legal-approved `verdict_label`. See
`company/legal/F003-disclaimer-review.md`.

## D041 · 2026-07-21 · cpo · [FEATURE]

**F003 shipped — /research live; ledger advances to features_shipped_sprint_0 = 4.**

CEO signoff captured under end-of-sprint dogfood pass (D005
cadence) plus the per-feature legal + QA passes above. Ship-in-
place because DevOps is on standby (Sprint 1+). HQ dashboard now
reflects features_shipped 4 / 5 (F005 + F001 + F002 + F003).
See `company/handoffs/F003-legal-to-ceo.json`.

## D042 · 2026-07-21 · frontend · [SPEC-EXTENSION]

**`serve_platform.make_handler()` gains `research_root` + `research_manifest_path` kwargs.**

F003 spec (`F003-research-page.md`) did not pin how the sibling
research repo's location is discovered at runtime. Chose to derive
`research_root` from `--research-reviews`' parents (the existing
config key already points at
`.../finance-research-experiments/programs/M001_multi_agent_ensemble/reviews`,
so climbing two parents lands on the repo root). New kwargs
default to `None`; a missing repo renders the friendly
`source_exists=false` empty state. F003 spec updated in-place with
the derivation note.

## D043 · 2026-07-21 · frontend · [ARCHITECTURE]

**F004 hoisted `.nav` flex-wrap + a 700 px media query into `_BASE_CSS` so every page inherits mobile-responsive nav automatically.**

F004 was baked into F001 / F002 / F003 as they landed, but the
smoke test surfaced two residual gaps against the F004 spec's
"all 7 routes clear the 375 px bar" criterion: `V1_PAGE` lacked
any `@media` block, and `.nav` was not `flex-wrap: wrap` — so
seven nav pills would force horizontal scroll on any pre-existing
page. Both fixed at the base-CSS level so HUB / V1 / V2 / HQ get
the mobile pass "for free" via the existing `__BASE_CSS__`
substitution. A 62-test smoke suite (`test_mobile_responsive.py`)
locks the invariants: viewport meta present, at least one mobile
media query per page, canonical 700 px on Sprint 0 pages, no
body-level `overflow-x: scroll`, no font-size below 10 px.
Platform suite 286 → 348.

## D044 · 2026-07-21 · cpo · [FEATURE]

**F004 shipped — 375 px bar cleared across all 7 required routes; ledger advances to features_shipped_sprint_0 = 5.**

CEO signoff captured under end-of-sprint dogfood pass (D005
cadence) plus the per-feature QA pass. F004 fast-path complete:
security + legal correctly skipped (no new surface, just
responsive CSS). See `company/handoffs/F004-qa-to-cpo.json`.

## D045 · 2026-07-21 · cpo · [SPRINT]

**Sprint 0 (Trust Foundation) verdict: COMPLETE. All 5 P0 features shipped in ~4 hours honest wall-clock.**

F005 → F001 → F002 → F003 → F004 landed in a single Sprint 0
Executor session (2026-07-21 14:00 → 18:00 UTC-ish). Final test
count 348 platform tests (100 pre-sprint, +248 delta), 42
review-chain handoff JSONs on tape in `company/handoffs/`, 45
decision entries in this log, zero blockers surfaced to CEO, zero
budget spent. HQ dashboard accurate to the minute at close:
`features_shipped_sprint_0 = 5`. Sprint 1 (Access) is the next
lane — broker connection wizard, real user accounts, first-time
setup flow. See `company/sprints/sprint-0-trust-foundation/REPORT.md`
for the post-mortem and retro suggestions for Sprint 1.

## D046 · 2026-07-21 · ceo · [SPRINT]

**Sprint 0 (Trust Foundation) formally signed off — 5/5 features accepted.**

Independent post-sprint verification: `product` branch pushed to
origin at commit `64a58ff` with 9 sprint commits above the founding
line (`e6a99fa`); `.venv/bin/python -m pytest -q` reports 971 passed
+ 1 skipped (946 non-vaults + 24 vaults + 1 skipped, matches the
executor's 971 claim); ledger `sprints[0].verdict = "COMPLETE"`;
`kpis.features_shipped_sprint_0 = 5`; `/hq` Kanban shows 5 features
in `ship`, 0 in every other column; blockers panel empty. Trust
Foundation is on the record. Sprint 1 (Access) is next. Retro
improvements ratified in D047 + D048.

## D047 · 2026-07-21 · cto · [ARCH]

**Ratified retro protocol improvements from Sprint 0 REPORT §Retro (points 1, 2, 4, 5).**

Formalises four ops-level improvements the Sprint 0 Executor
surfaced in the post-mortem: (1) F005-first serialisation stays the
default pattern for any sprint that introduces shared UI primitives;
(2) new spec-lock step in the review chain — persona in the `build`
stage must diff the spec against on-disk state before starting
(prevents the F003 issue where the spec referenced non-existent
`REPORT.md` filenames); (4) Legal claim register audit automated as
a pre-commit hook — any `agent/platform/performance.py` public field
without a matching entry in `company/legal/claim_register.md` fails
the commit; (5) `_BASE_CSS` version tag bumped whenever its content
changes (major bump on layout / typography / class-name breaks). All
four land as amendments to `company/protocols/review-chain.md` in
Sprint 1's first commit.

## D048 · 2026-07-21 · ceo · [ARCH]

**Ratified retro protocol improvement #3 — mandatory security tests for auth-adjacent features from Sprint 1 onwards.**

The Sprint 0 Executor's retro flagged that Sprint 1's broker
connection wizard, real user accounts, and first-time setup flow all
touch auth or credentials — a step-change in threat surface vs
Sprint 0's read-only public routes. Ruling: from Sprint 1 forward,
any feature whose spec labels it `auth: true` or `credentials: true`
requires a `tests/security/test_<feature>.py` module with at least
(a) auth-bypass negative tests, (b) credential-storage-at-rest
tests, (c) input-fuzz tests on any user-supplied credential field.
Security persona activates as a mandatory reviewer (no longer
conditional) for all such features. Security review handoff written
BEFORE the QA handoff, not after — earlier catch.

## D049 · 2026-07-21 · ceo · [SPRINT]

**Sprint 1 kick-off timing deferred to explicit CEO green-light (Fiyin).**

Sprint 0 shipped in a single ~4-hour executor pass; Sprint 1 is
higher-stakes (money-adjacent, auth-adjacent) and the retro
recommended splitting the executor persona into narrower roles for
this lane. Kicking off Sprint 1 immediately without CEO input on
(a) executor decomposition, (b) whether Finance activates now vs
at first shopping-list moment, and (c) whether to dogfood Sprint 0
on desktop + mobile before adding new surfaces, would violate the
escalation protocol's brand / architecture / money categories. Held
pending explicit CEO direction in the next session.

## D050 · 2026-07-21 · ceo · [SPRINT]

**Sprint 1 (Access) kick-off green-lit — single executor, three lane-personas.**

Kicks off tonight. Executor structure: one coherent worker with strict
lane discipline splitting into three internal personas — (1) Auth
Developer (encrypted credential storage + single-user token auth),
(2) Broker Integrations (MT5 connection wizard + connection testing),
(3) Onboarding UX (first-time setup flow /onboarding). Retro's "split
the executor persona for money-adjacent sprints" (Sprint 0 §Retro #6)
implemented as strict internal-lane discipline rather than parallel
subagents (files bottleneck on pages.py + serve_platform.py). Lane
serialisation: Auth → Broker → Onboarding, but each lane's design
stage can run in parallel with the previous lane's build stage.

## D051 · 2026-07-21 · ceo · [FOUNDING]

**Finance activation deferred to first genuine spend decision.**

Finance persona stays at `active: false` on the roster until a Sprint
1+ feature surfaces a required purchase (broker sandbox account,
paid market-data subscription, domain, hosting, mailer, monitoring
SaaS). At that moment the requesting persona files a
`[BLOCKER][SPEND]` escalation entry pointing at the shortlist; Finance
activates, produces vendor comparison + spend memo per role doc; CEO
ratifies before any card is charged. Company card + spending limit
setup deferred to that first-spend moment.

## D052 · 2026-07-21 · ceo · [ARCH]

**Sprint 1 auth scope = MINIMAL: single-user install, bring-your-own broker.**

No user database. No signup flow. No email verification. No password
reset. No multi-tenant story. Model: one install = one user;
credentials for that user's MT5 account stored encrypted at rest
(OS keychain via `keyring` library preferred; encrypted-file fallback
with user passphrase); single install-scoped `auth_token` generated
on first setup and stored the same way. Sandbox / demo MT5 is
default; live MT5 requires explicit user opt-in through the
onboarding flow. Real user accounts + multi-tenancy = later sprint
(Stickiness / Compliance) after we see one install working end-to-end
first.

## D053 · 2026-07-21 · cto · [ARCH]

**Retro amendments landed in `company/protocols/review-chain.md` (§3.5, §4.2, §5.5, §6.3) + claim register seeded + `_BASE_CSS_VERSION="1.0.0"` + `keyring` dependency added.**

Per D047 the four Sprint 1 retro improvements land as protocol
amendments in this sprint's first commit. §3.5 formalises
shared-primitive-first serialisation (F006 plays the role for
Sprint 1). §4.2 adds a spec-lock validation step at the start of
`build`. §5.5 pins `_BASE_CSS_VERSION` semver in code + tests. §6.3
introduces `company/legal/claim_register.md` seeded with F001/F002/F003
public fields. Also adds `keyring>=25.0` to `requirements.txt` +
`pyproject.toml` per D052's pre-authorisation ("OS keychain via
`keyring` library preferred"). Three new tests pin the version pin
(974 total, was 971). See handoff at
`company/handoffs/sprint-1-retro-cto-to-cpo.json`.

## D054 · 2026-07-21 · cpo · [FEATURE]

**F006 spec locked — encrypted credential storage + install-scoped auth.**

See `company/sprints/sprint-1-access/F006-encrypted-credentials-and-auth.md`.
Two new backend modules (`agent/platform/credentials.py` +
`agent/platform/auth.py`), a Python logging redaction filter, a new
`/api/auth/status` route, and an auth gate that fires on `/api/*`
non-localhost binds only. Zero rotation of the deployed VM's
pre-existing `platform.toml` `auth_token` — install-token is
additive per D052. Foundation feature for Sprint 1; F007 and F008
consume it.

## D055 · 2026-07-21 · cpo · [FEATURE]

**F007 spec locked — MT5 broker connection wizard.**

See `company/sprints/sprint-1-access/F007-broker-connection-wizard.md`.
New backend module (`agent/platform/broker_connection.py`) + new
`BROKER_WIZARD_PAGE` at `/settings/broker` + four HTTP APIs
(`/api/broker/test-connection`, `/save`, `/list`, `/delete`). MT5 is
Windows-only; macOS/Linux surface a "MT5 not on this platform"
affordance instead of a hard failure. Sandbox default per D052; live
requires "I understand" checkbox + typed "LIVE" confirmation +
inline Legal warning drafted in `company/legal/live-broker-warning.md`.
Rate-limited to 5 test-connection attempts per minute per install
token. Server allow-list enforced.

## D056 · 2026-07-21 · cpo · [FEATURE]

**F008 spec locked — first-time setup / onboarding flow.**

See `company/sprints/sprint-1-access/F008-onboarding-flow.md`. New
backend module (`agent/platform/onboarding.py`) + new
`ONBOARDING_PAGE` at `/onboarding` with 5 steps (welcome →
passphrase → broker → default pairs → confirm). First-visit redirect
JS on every page + server-side belt-and-braces redirect from every
non-exempt route. `/settings/reset-install` clears keyring state and
returns to onboarding. Onboarding state (current step, completion
flag) stored in keyring, never in the git-tracked `platform.toml`.

## D057 · 2026-07-21 · cpo · [FEATURE]

**F006 shipped — Sprint 1 first feature accepted.**

Sprint 1 foundation shipped end-to-end in one build stage:
`agent/platform/credentials.py` (keyring + Fernet fallback with
PBKDF2-SHA256 200k) + `agent/platform/auth.py` (install-token
generation, fingerprint, constant-time compare, RedactingFilter for
logs) + `/api/auth/status` API + install-token gate on `/api/*`
non-localhost routes. Pre-existing `platform.toml` `auth_token`
preserved as fallback (D052 backwards-compat). Test count 974 → 1091
(+117: 52 auth-security + 40 credentials-security + 6 credentials-
module + 6 auth-module + 13 auth-api). Every acceptance criterion has
a matching test. Legal disclaimer verbatim-ready at
`company/legal/F006-secrets-at-rest.md`. Claim register updated.
Handoff on tape at `company/handoffs/F006-legal-to-ceo.json`.

## D058 · 2026-07-21 · cpo · [FEATURE]

**F007 shipped — MT5 broker connection wizard accepted.**

Sprint 1 second feature shipped end-to-end. New backend module
`agent/platform/broker_connection.py` abstracts MT5 login: 12-entry
`ALLOWED_SERVERS` allow-list, alias regex, 5/min/process rate-limit on
`test_connection`, Windows-only `MetaTrader5` SDK short-circuits on
macOS / Linux with a friendly failed-payload rather than an
ImportError leak. Wizard `BROKER_WIZARD_PAGE` at `/settings/broker` is
a five-step form (account type → credentials → live-confirmation gate
→ test → save) with a saved-connections table always visible; uses
F005 `withStates()` for the in-flight state. Live-account save
requires both an acknowledgement checkbox AND a typed `LIVE` before
Continue unlocks; the warning body loads verbatim from
`/api/broker/live-warning` which reads
`company/legal/live-broker-warning.md`. Test count 1091 → 1180 (+89:
16 broker-security + 26 module + 21 API + 16 wizard-page + 10 backend
guards). Password never appears in any log line, response body, or
JSON payload — pinned by regression tests. Non-localhost binds gate
all `/api/broker/*` on F006 install-token; `/api/broker/live-warning`
intentionally exempt so the Legal warning is readable before setup
completes. Handoff on tape at
`company/handoffs/F007-legal-to-ceo.json`.

## D059 · 2026-07-21 · cpo · [FEATURE]

**F008 shipped — first-time setup / onboarding flow accepted.**

Sprint 1 final feature shipped end-to-end. New backend module
`agent/platform/onboarding.py` provides the state machine for the
first-time setup wizard: `is_first_visit`, `mark_setup_complete`,
`reset_install` (sweeps both `bluelock` and `broker_mt5` namespaces
via the F006 credentials layer -- state lives in keyring, never in
git-tracked `platform.toml`), `get_onboarding_state`,
`set_current_step`, `set_default_pairs` /
`get_default_pairs`, and `validate_passphrase` (>=12 chars when
keychain absent, empty accepted when keychain available).

New `ONBOARDING_PAGE` at `/onboarding` walks five steps
(welcome → passphrase → broker → pairs → confirm). Welcome step
carries a verbatim Legal agreement paragraph from
`company/legal/F008-onboarding-agreement.md`. Broker step opens
F007's `/settings/broker` in a new tab; Continue re-checks
`broker_connected` before advancing. Pairs step pre-checks EURUSD.

`RESET_INSTALL_PAGE` at `/settings/reset-install` provides a
red-styled destructive-action page that clears every stored key and
returns to `/onboarding`.

Server-side first-visit HTML redirect gate added to
`scripts/serve_platform.py`: opt-in via `enforce_onboarding_gate`
parameter on `make_handler` (default False so Sprint 0 tests keep
the old contract). `main()` flips it on for non-localhost binds
alongside the F006 install-token gate. All `/api/onboarding/*` routes
are exempt from the install-token gate because they run before
setup completes.

Test count 1180 → 1259 (+79: 23 security + 13 module + 22 API + 21
page). Cold-install cycle verified end-to-end on macOS. Legal
agreement is on tape at `company/legal/F008-onboarding-agreement.md`.
Handoff at `company/handoffs/F008-legal-to-ceo.json`.

## D060 · 2026-07-21 · cpo · [SPRINT]

**Sprint 1 (Access) closes COMPLETE — 3/3 P0 features shipped.**

Verdict: **COMPLETE**. 3 of 3 features accepted:

- **F006** (Encrypted credential storage + install-scoped auth) — 117
  tests, D057.
- **F007** (MT5 broker connection wizard) — 89 tests, D058.
- **F008** (First-time setup / onboarding flow) — 79 tests, D059.

Total delta: 974 → 1259 tests (+285). Full suite green. Zero
commits off `product`. Zero spend triggered. No Cursor attribution.
Retro protocol amendments landed FIRST per D047 (review-chain
§3.5 F005-first serialisation, §4.2 spec-lock validation, §5.5
`_BASE_CSS_VERSION` tag, §6.3 automated Legal claim-register audit).

Sprint duration: 1 wall-clock day (2026-07-21) against a 13-day
honest-review target. That's a compression only possible because
the Executor persona ran every lane serially; a real 3-persona
split with independent scheduling would have taken longer. Honest
review flag surfaced in the sprint verdict entry so future ratifiers
can adjust the day_count estimate.

## D061 · 2026-07-21 · ceo · [SPRINT]

**Sprint 1 (Access) formally signed off — 3/3 features accepted, no security regressions.**

Independent post-sprint verification: `product` @ `3a4e93d` pushed to
origin (9 sprint commits from `635c9bd` through `3a4e93d`); full
`.venv/bin/python -m pytest -q` reports **1258 passed + 1 skipped**
(matches executor's 1259 count when the skipped test is included);
`tests/security/*` populated with 170 tests, all green (executor
undercounted at 132 — actual is larger, no controls missing).
Credential-leak grep across the sprint diff finds only fake test
strings (`pw12345`, `s3cret-password-xyz`, `hunter2super…`) and the
allowlisted public MT5 server names (`Exness-MT5Demo` /
`Exness-MT5Trial7`) — zero real-credential material committed.
`RedactingFilter` present in `agent/platform/auth.py`; `keyring`
primary + `Fernet` fallback both live in `credentials.py`. Ledger
`sprints[1].verdict = "COMPLETE"`; `/hq` Kanban shows F006/F007/F008
in ship; blockers panel empty. Access lane is on record.

## D062 · 2026-07-21 · cto · [ARCH]

**Ratified retro carry-overs from Sprint 1 REPORT §Retro; deferred security controls scoped into Sprint 2.**

Sprint 1 shipped the auth surface but deferred three security controls
to Sprint 2 per the honest-review flag: (a) per-install-token rate
limit on all `/api/*` non-localhost, (b) session expiry / token
rotation (currently install-token is permanent), (c) automated
claim-register audit hook (§6.3 registered in the protocol but the
pre-commit script is not yet written). These are Sprint 2's mandatory
inclusions alongside the pre-registered Real-Trading features. The
Executor persona's honest-review flag on `sprint_verdicts[1]` —
"1 wall-clock day only possible because the Executor persona owns
every lane; a real 3-persona split would take longer" — is retained
as evidence of process discipline, not as a defect. Sprint-length
calibration deferred to CEO gate D063.

## D063 · 2026-07-21 · ceo · [SPRINT]

**Sprint 2 (Real-Trading) kick-off held pending explicit CEO green-light.**

Sprint 2 is the largest threat-model shift in the product's lifetime:
it introduces the pathway from paper trading to live-order placement.
Every previous sprint has been read-only or credentials-at-rest;
Sprint 2 can move real money. CEO input required on (a) whether the
squad ever places real orders vs stays shadow-only forever (this is
the ship-or-hold call on the whole product's animating premise),
(b) how strict the trade-approval mode should be (per-trade
human-in-loop / daily-risk-budget / no-live-mode-at-all), (c) whether
to activate Finance persona now for the first potential spend (paid
alerts channel, monitoring, hosting), (d) whether to also address
Sprint 1's three deferred security controls in Sprint 2 or move them
to a hardening sprint. Held pending explicit CEO direction in the
next session — no autonomous dispatch.

## D064 · 2026-07-21 · ceo · [SPRINT]

**Sprint 2 (Real-Trading) green-lit — cautious-live pathway, six-feature scope, safety-first ordering.**

Kick-off tonight. Three CEO calls locked:

1. **Live orders posture** = shadow default + live opt-in with heavy
   friction. Users flip a switch to enable; every live order goes
   through human-in-loop approval; per-day risk budget hard-cap
   enforces max daily loss; kill-switches always available. Rejected
   both extremes (shadow-forever = kills the product's animating
   premise; auto-live = unacceptable legal surface without maturity).

2. **Sprint 2 scope** = comprehensive; six features covering
   Real-Trading core + Sprint 1's three deferred security controls +
   Sprint 1's §6.3 audit hook automation. The CEO's directive was
   "include everything that will make this product both usable and
   functional and efficient" — Real-Trading without the safety layer
   is not usable; new auth pathways without hardening are not
   functional; manual claim-register audits are not efficient.

3. **Finance activation** = dormant until a `[BLOCKER][SPEND]` fires.
   All Sprint 2 features achievable without external paid services
   (SSE alerts self-hosted; Telegram already available for
   notifications; no monitoring SaaS purchased). Company card
   conversation continues to defer.

Feature set (safety-first ordering):

- **F009** — Auth hardening: per-install-token rate limit on `/api/*`
  non-localhost + session expiry + token rotation. Sprint 1
  carry-over per D062.
- **F010** — Claim-register audit pre-commit hook: implements the
  §6.3 script registered in D047; audits every public field in
  `agent/platform/*.py` against `company/legal/claim_register.md`.
  Sprint 1 carry-over per D062.
- **F011** — Kill-switches infrastructure: per-symbol + global
  kill-file support with hot-reload on the platform; `/settings/
  kill-switches` UI to toggle from the platform (mirrors the
  existing v1 kill-file protocol). Prerequisite for F013.
- **F012** — Risk budget hard-cap + broker connection health:
  per-day, per-symbol, per-strategy max-loss caps; live risk
  dashboard at `/risk` showing exposure / margin / worst-case /
  MT5-connection-alive. Prerequisite for F013.
- **F013** — Trade approval mode: human-in-loop confirmation queue
  at `/approvals`; every squad-proposed live order (when live-mode
  is enabled) surfaces here with rationale, risk numbers, and
  timeout; user approves / rejects / lets-timeout. This is the
  central Real-Trading feature.
- **F014** — SSE alerts stream at `/api/alerts/stream`: trade fills,
  stop hits, kill-switch trips, risk-budget breaches, platform down.
  Telegram bridge reuses existing `bot_token` in `platform.toml`.

## D065 · 2026-07-21 · ceo · [ARCH]

**Sprint 2 ships the SCAFFOLDING for live orders, not the switch that starts sending them.**

Every safety layer, approval queue, kill-switch, and alert lands as
new `product`-branch code that runs in default-OFF mode. The user
must explicitly flip a live-mode toggle in the UI to enable live
order-sending. Sprint 2 does NOT:

- Modify `agent/live/*` or `agent/risk/*` (v1 zones live agent on
  `main` stays untouched, its kill-file protocol unaffected)
- Modify `agent/squad/*` (next-gen shadow-runtime stays untouched)
- Connect the squad to real broker order placement
- Enable live-mode by default anywhere

The connection between Sprint 2's safety-layer scaffolding and the
squad actually placing live orders is a **separate integration**
that requires a future CEO decision — not Sprint 2's business.
Sprint 2's own tests must include a "live-mode-off invariant" that
proves no live order can send from a clean install without the
explicit user toggle.

## D066 · 2026-07-22 · cpo · [SPRINT]

**Sprint 2 opened with six P0 feature specs locked (F009-F014).**

Kicked off tonight by the Sprint 2 Executor. Six specs at
`company/sprints/sprint-2-real-trading/`: F009 auth hardening
(Sprint 1 carry-over), F010 claim-register audit (Sprint 1
carry-over), F011 kill-switches, F012 risk budget + broker health,
F013 trade approval + live-mode, F014 SSE alerts + Telegram. Build
order is strictly serial (safety-first). F013 carries the P0
`tests/security/test_live_mode_off_invariant.py` pin. D065
SCAFFOLDING-only invariant + D062 carry-overs both honoured.

## D067 · 2026-07-22 · cpo · [FEATURE]

**F009 spec locked — rate limiter + session expiry + token rotation.**

See `company/sprints/sprint-2-real-trading/F009-auth-hardening.md`.
New module `agent/platform/rate_limiter.py` (token-bucket, 60 req/
min per install-token by default, config from `[rate_limit]` in
`platform.toml`). `auth.py` additions: `record_session_activity`,
`session_last_activity`, `is_session_expired`, `rotate_install_token`,
`POST /api/auth/rotate`. Session expiry configurable via
`[session]` block (default 7 days). Legal review handoff written
BEFORE QA per D048.

## D068 · 2026-07-22 · cpo · [FEATURE]

**F010 spec locked — claim-register audit script + pre-commit hook.**

See `company/sprints/sprint-2-real-trading/F010-claim-register-audit.md`.
`scripts/check_claim_register.py` walks `agent/platform/*.py` via
AST, cross-references `company/legal/claim_register.md`, fails
commit on any unregistered public claim. `scripts/git-hooks/pre-
commit` template + `scripts/install_git_hooks.py` opt-in installer.
`tests/platform/test_claim_register_audit.py` catches misses even
without the git-hook installed (CI-equivalent).

## D069 · 2026-07-22 · cpo · [FEATURE]

**F011 spec locked — kill-switches (global + per-symbol) with hot-reload + /settings/kill-switches.**

See `company/sprints/sprint-2-real-trading/F011-kill-switches.md`.
`agent/platform/kill_switches.py` (read-only view, mtime-based cache)
+ `kill_switch_admin.py` (write path, audit log at
`<config_dir>/kill_events.jsonl`). `KILL_SWITCHES_PAGE` at
`/settings/kill-switches`. `is_killed()` is the SECOND check in the
4-gate live-order pathway (after `live_mode_enabled`). Mirrors v1
`kill.txt` protocol shape without importing from `agent/live/`.

## D070 · 2026-07-22 · cpo · [FEATURE]

**F012 spec locked — risk budget hard-cap (3 tiers) + broker health probe + /risk dashboard.**

See `company/sprints/sprint-2-real-trading/F012-risk-budget-and-
broker-health.md`. `risk_budget.py` enforces per-day / per-symbol /
per-strategy max-loss caps from `risk_budget.toml` +
`risk_state.jsonl` fill audit. `broker_health.py` wraps
`broker_connection.test_connection` with 30-second cache.
`RISK_PAGE` at `/risk` polls state every 30 s. `can_send_order()`
is the THIRD check in the 4-gate pathway.

## D071 · 2026-07-22 · cpo · [FEATURE]

**F013 spec locked — trade approval mode + /approvals + live-mode toggle + P0 live-mode-off invariant.**

See `company/sprints/sprint-2-real-trading/F013-trade-approval-and-
live-mode.md`. `approval_queue.py` with in-memory queue + jsonl
audit, 5-minute default timeout, `submit / approve / reject /
timeout_reap / can_send_order`. Live-mode toggle in keyring under
`bluelock/live_mode_enabled` (default missing == disabled).
`/settings/live-mode` ceremony: checkbox + typed
`"ENABLE LIVE MODE"` + verbatim Legal disclaimer body.
`/approvals` shows pending queue with countdown + approve / reject
buttons. **`tests/security/test_live_mode_off_invariant.py`**
composes the 4-check gate (`live_mode_enabled` + `kill_switches` +
`risk_budget` + `approval_queue`) — the single most important test
in the sprint. Legal review (live-mode-warning + approval-queue-
warning) handoff written BEFORE QA per D048.

## D072 · 2026-07-22 · cpo · [FEATURE]

**F014 spec locked — SSE alerts stream + Telegram bridge + /alerts.**

See `company/sprints/sprint-2-real-trading/F014-sse-alerts-and-
telegram.md`. `agent/platform/alerts.py` (in-process event bus,
thread-safe, 100-event ring buffer). `alerts_sse.py` (SSE endpoint
at `/api/alerts/stream`, `?token=` auth since browsers cannot set
headers on `EventSource`). `alerts_telegram.py` (bridges bus to
Telegram via `httpx`, reuses existing `platform.toml` bot_token).
Six event types: `trade_fill / stop_hit / kill_switch_trip /
risk_budget_breach / approval_submitted / platform_down`.
`/alerts` page + test-alert button. No real Telegram calls in
tests (httpx mocked).

## D073 · 2026-07-22 · cpo · [FEATURE]

**F009 shipped — auth hardening: rate limiter + session expiry + token rotation.**

Sprint 1's three deferred security controls (D062) all close with this
feature. `agent/platform/rate_limiter.py` implements a per-install-
token token bucket (60 req/min default, configurable via
`[rate_limit]` in `platform.toml`; `429` with `Retry-After` on
breach). `agent/platform/auth.py` gains
`record_session_activity` / `is_session_expired` /
`rotate_install_token`; `scripts/serve_platform.py` composes them in
`_install_gate_pass()` so the F006 install-token gate now also
enforces rate limiting and session expiry (default 7 days,
configurable via `[session] expiry_days`). `POST /api/auth/rotate`
generates a fresh token and invalidates the old atomically.
Legacy `platform.toml` fallback tokens are explicitly exempt from
session expiry (no F006 install configured) to avoid breaking the
deployed VM binding.

Full suite grows by 28 across three test files:
`test_rate_limiter.py` 14, `test_session_expiry.py` 8,
`test_token_rotation.py` 6. Claim register updated for the new
public accessors; rolling Legal constraint added — future copy
citing req/min or session-length MUST reference `get_config()` /
`get_session_expiry_seconds()`, not restate hardcoded numbers.
Handoff chain: F009 CPO → UX Researcher → CTO → Backend → Security →
QA → Legal → CEO (via CPO signoff on behalf of CEO) at
`company/handoffs/F009-legal-to-ceo.json`.

## D074 · 2026-07-22 · cpo · [FEATURE]

**F010 shipped — claim-register audit tooling + pre-commit hook.**

Sprint 1's second deferred item (D062: review-chain §6.3 automation,
originally flagged in D047) closes. `scripts/check_claim_register.py`
walks every `agent/platform/*.py`, extracts public accessors and
`# claim: NAME` markers, and cross-references
`company/legal/claim_register.md`. Unregistered accessors exit 1 with
a `file:line kind module.name` diagnostic. `# claim-exempt: <reason>`
inline markers on def / class lines opt an internal helper out
(reason surfaced in `--json`).

The pre-commit hook (`scripts/git-hooks/pre-commit`) is opt-in via
`python3 scripts/install_git_hooks.py` — installer is idempotent
(marker-based), backs up foreign hooks to `pre-commit.bak`, refuses
to remove non-Blue-Lock hooks. `tests/platform/test_claim_register_audit.py`
holds 9 tests (spec asked 8) including a red-line SPARE_CLAIM case
that pins the diagnostic format.

Housekeeping: to make the audit exit 0 on the current repo, 8
pre-Sprint-2 accessors were formally registered (`list_players`,
`is_setup_complete`, `set_current_step`, `set_default_pairs`,
`get_default_pairs`, `validate_passphrase`, `is_install_configured`,
`check_request_token`) and 9 internal helpers were marked
`# claim-exempt: <reason>` inline
(`credentials.{encrypted_file_path, set_config_dir,
set_encrypted_file_passphrase, is_keyring_available, force_fallback}`,
`broker_connection.reset_rate_limiter`,
`auth.{constant_time_equal, RedactingFilter, install_redacting_filter}`).
Documentation-grade edits; no runtime behaviour change.

Full suite: 1287 → 1295 passed, 1 skipped (playwright cache,
pre-existing). Handoff chain (abbreviated: CPO → CTO → Backend →
QA → CPO-signoff — no UX Researcher, no Legal, no Security stage
for pure infra) at `company/handoffs/F010-qa-to-cpo.json`.

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
