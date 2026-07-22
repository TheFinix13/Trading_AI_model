# R&D Loop — feedback → triage → ship → measure → feedback

Canonical protocol for the closed feedback loop that runs alongside the
review chain. The review chain (`review-chain.md`) tells us how a feature
moves from spec to ship; **this protocol tells us where features come from
in the first place, and how we know they actually helped once shipped.**

Written 2026-07-22 as the operating consequence of the CEO's
"real-product / real-users / literature-standard" directive. Adopted by
CPO decision; CEO signs off. See `company/evolution/drafts/decisions_log_addendum.md`.

## The loop

```
   ┌─── Sprint retro ── Post-mortem ── Dogfood ────┐
   │                                                │
   ▼                                                │
Intake ──► CPO triage ──► classification ──► routed to:
   │                                                │
   ▲                                          ┌─────┴─────────────────┐
   │                                          │           │             │
   │                                          ▼           ▼             ▼
   │                                        Bug        Feature       Research
   │                                       (fast-      (sprint       (finance-
   │                                       path)       backlog)      research-
   │                                                                 experiments)
   │                                          │           │             │
   │                                          └────┬──────┴──────┬──────┘
   │                                               ▼             ▼
   │                                             Ship         Publish
   │                                               │             │
   │                                               └──────┬──────┘
   │                                                      ▼
   └── Feedback: measurement + user notify ── /research or /hq surface
```

The loop is closed when every intake item has a status (shipped /
declined / deferred with reason), a measurement (did the ship actually
help?), and — if the user gave contact info — a notify.

## §1 Intake channels

Five sources of intake feed the queue. Each source has a canonical
capture mechanism.

| Channel | Capture | Volume expectation (Sprint 2 / 4 / post-launch) |
|---|---|---|
| **Bug reports** | F013's approval-queue rejections + F014 alert stream + (Sprint 4+) `/feedback` route + `support@` inbox | low / medium / high |
| **User surveys** | Sprint 4+ in-product prompts + retro emails | 0 / medium / medium |
| **Dogfood observations** | Self-observation by CEO or any persona while using the platform | high / high / medium |
| **Agent-emitted anomalies** | Sentinel warnings, unusual rejection patterns, `agent/live/` daily rejection-review digest, squad Kanban misses | medium / medium / medium |
| **Squad post-mortems** | Sprint retros, feature failure post-mortems, finance-research-experiments STOP_NOTICE files | 1–2 per sprint |

All five funnel into `company/rd/intake/` as one file per item.

## §2 The intake item — data shape

Every intake item lands as a Markdown file at
`company/rd/intake/I<###>-<slug>.md`. The `I###` prefix — chosen to avoid
collision with feature `F###` and decision `D###` counters — is monotonic
starting at `I001`.

Required front matter (YAML):

```yaml
---
id: I001
source: bug | feature-request | dogfood | agent-anomaly | post-mortem | survey
submitter: <user_id | persona_id | "self-observation">
submitted_at: 2026-07-22T14:00:00Z
classification: null   # filled at triage
priority: null          # filled at triage
status: new             # new | triaged | routed | in_progress | shipped | declined | deferred
route: null             # bug | feature | research | performance | polish | out-of-scope
linked_features: []     # F### references once routed to a feature
linked_decisions: []    # D### references
linked_experiments: []  # finance-research-experiments E### / M### references
contact: null           # user contact only if they consented; else null
resolved_at: null
---
```

Body: 3–8 paragraphs. Sections:

1. **What happened** (what the user / persona observed).
2. **Why it matters** (impact on user or on the product's credibility).
3. **Proposed resolution** (only if the submitter has one — often blank).

The template is at `company/rd/intake/TEMPLATE.md`. Copy → edit → land.

## §3 Triage cadence

**CPO (Noel Noa) drains the intake queue weekly** on Monday morning at
the start of the working day. If the queue holds ≥ 10 items, or if any
single item is priority P0 (a user is actively harmed), CPO drains
immediately.

Triage output for each item:

1. **Classification** — one of:
   - `[BUG]` — the product does not behave as its own spec claims.
   - `[FEATURE-REQUEST]` — a plausible new capability.
   - `[RESEARCH-QUESTION]` — a claim about market, strategy, or model
     behaviour that needs pre-registered testing.
   - `[PERFORMANCE]` — the product works but slower / less reliably
     than a user should tolerate.
   - `[POLISH]` — copy, spacing, empty-state, minor UX friction.
   - `[OUT-OF-SCOPE]` — legitimate observation but not something this
     company is or should be shipping.
2. **Priority** — P0 (user actively harmed / actively losing trust)
   / P1 (next-sprint candidate) / P2 (documented, deferred).
3. **Routing** — see §4.

Every triage decision lands as a `history[]` entry in the intake file
front matter (`triaged_at`, `triaged_by: cpo`, `verdict: ...`) and — if
the item is P0/P1 — as a bullet in `company/ledger/decisions_log.md`.

## §4 Routing rules

| Classification | Route | Owner | Turn-around |
|---|---|---|---|
| `[BUG]` P0 | Hotfix — fast-path review chain, ship within 24 h | CTO + on-call engineer | 24 h |
| `[BUG]` P1/P2 | Sprint backlog (`sprints/<next>/BUGS.md`) | CPO | next-sprint |
| `[FEATURE-REQUEST]` | Sprint backlog (`sprints/backlog.md`) | CPO | next-sprint candidate |
| `[RESEARCH-QUESTION]` | Formalised as a `finance-research-experiments` experiment with pre-registration | Research Lead | ≤ 2 weeks to pre-registration |
| `[PERFORMANCE]` | Before / after measurement required; results reported on `/hq` KPI strip | CTO | current sprint if measurable in day, else next sprint |
| `[POLISH]` | Accumulates in the ongoing polish sprint (`sprints/polish/`) | CPO / Frontend | rolling |
| `[OUT-OF-SCOPE]` | Declined with reason logged; user notified if they left contact | CPO | 1 week |

Fast-path eligibility for `[BUG]` and `[POLISH]` items follows the
existing review-chain fast-path rules (`review-chain.md` §Fast path).

## §5 The finance-research-experiments bridge

`[RESEARCH-QUESTION]` items are the loop's cross-repo bridge. When an
item routes to research:

1. Research Lead files a `PROTOCOL.md` under
   `finance-research-experiments/programs/<Program>/experiments/<slug>/`
   OR `finance-research-experiments/experiments/E<###>_<slug>/`
   following the pre-registration rules in
   `literature-standards.md` §1.
2. The pre-registration lists this intake `I###` in its "motivation"
   section so the lineage is on-record.
3. When the experiment closes, its `REPORT.md` verdict flows back —
   Research Lead condenses it to `company/rd/findings/<slug>.md`
   (public-facing), and the intake `I###` moves to
   `status: shipped` with `linked_experiments: [E###]`.

**Product observations → research questions** flow the same direction:
if a dogfood observation suggests "does trade-approval-mode timeout
correlate with user attention?" then CPO tags it
`[RESEARCH-QUESTION]`, Research Lead pre-registers, and the loop
closes when the experiment reports.

## §6 Loop closure

An intake item is **closed** when *all* of the following hold:

1. Its `status` is one of `shipped | declined | deferred`.
2. If it changed the product, a measurement is on file — either
   inline in the intake body (small change) or as a linked
   experiment `REPORT.md` (large change).
3. If the submitter provided contact info, they have been notified of
   the outcome (Support owns the notify handshake).
4. If the fix was `[BUG]` P0/P1 or `[FEATURE-REQUEST]` shipped, the
   `/hq` decisions log carries a bullet.

Weekly, the Research Lead publishes a rollup at
`company/rd/intake/<YYYY-WW>-rollup.md`:

- Items opened this week (count + IDs + one-line).
- Items closed this week (count + IDs + outcome).
- Open queue depth (count) — surfaced on `/hq` KPI strip.
- Any item aged > 30 days without closure — flagged red.

## §7 Ledger link

Every intake item that reaches `[BUG]` P0/P1 or
`[FEATURE-REQUEST]` shipped, or `[RESEARCH-QUESTION]` promoted, gets
a `D###` entry in `company/ledger/decisions_log.md` describing the
routing decision. Convention:

```markdown
### D### · 2026-07-22 · cpo · [INTAKE]

Routed I014 ("`/performance` page loads slowly on mobile") as
`[PERFORMANCE]` P1. Before / after measurement to be reported by CTO
on `/hq` KPI strip within Sprint 3. User notified by Support.
```

The `company_state.json` ledger gains a top-level `intake` array
mirroring the intake file front matter (see
`company/evolution/drafts/company_state_addendum.json` for the schema).

## §8 What the R&D loop is NOT

- **Not a bug tracker.** GitHub Issues, Linear, and the like duplicate
  what our intake queue does; we do not use them until we have >100
  open items or a user population that needs a public tracker. Until
  then, the on-disk queue is authoritative and the `/hq` dashboard
  renders it.
- **Not a way to bypass the review chain.** Every routed item that
  becomes a feature still enters at `spec` and goes through the
  standard stages. The intake ID becomes a citation in the feature
  spec; it does not replace the spec.
- **Not a promise to ship every idea.** `[OUT-OF-SCOPE]` and P2
  `[FEATURE-REQUEST]` are legitimate closures. The evidence-over-
  marketing value means we tell submitters the truth about their
  request, not that we ship everything.
- **Not a substitute for pre-registration.** A `[RESEARCH-QUESTION]`
  item is a *trigger* for pre-registration, not pre-registration
  itself. See `literature-standards.md`.

## §9 First-week operating calendar (2026-07-22 →)

Concrete cadence to demonstrate the loop is live, not aspirational:

| Day | Action | Owner |
|---|---|---|
| Mon | Drain intake queue; classify; route | CPO |
| Tue | File `[RESEARCH-QUESTION]` pre-registrations in F-R-E | Research Lead |
| Wed | Publish first condensed finding at `company/rd/findings/` (candidate: Phase AC negative) | Research Lead |
| Thu | Ship measurements for previous week's shipped items (KPI strip update) | CTO |
| Fri | Weekly rollup published at `company/rd/intake/<YYYY-WW>-rollup.md` | Research Lead |

## §10 Related protocols

- `review-chain.md` — how a routed feature moves from spec to ship.
- `literature-standards.md` — how a `[RESEARCH-QUESTION]` is turned
  into a pre-registered, statistically-honest experiment.
- `escalation.md` — when a triage decision escalates to CEO (e.g. an
  intake item alleges data loss, or names a real user's account).
- `persona-handoff.md` — the intake-to-owner handoff still uses the
  standard JSON + narrative handoff artefact.
