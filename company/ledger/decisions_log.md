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
