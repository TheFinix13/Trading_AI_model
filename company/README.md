# Blue Lock Trading Co. — Founding Charter

> **The first AI trading platform that trades like a football team.**
> Watch our striker squad find setups on real markets — every decision
> explained, every trade justified, every risk gated.

Founded 2026-07-21. Charter elevated 2026-07-22 per CEO directive
(real product / real users / literature-standard R&D).

---

## Mission

Turn the multi-pair AI trading prototype into a **real product that real
strangers pay real money for and give real feedback about**. Every artifact
this company ships must strengthen one of three pillars, in this order:

1. **Trust foundation** — public evidence, transparent research, human
   language. If a prospect cannot look at the platform for two minutes and
   understand what it does and why, we have shipped nothing.
2. **Access** — turn viewers into users. Sign-up, broker connection,
   per-user data, first-time setup.
3. **Stickiness** — turn users into fans. Character seasons, match
   highlights, strategy marketplace, community.

Trust before access. Access before stickiness. **Never invert the order.**

## Operating principles (2026-07-22, CEO Fiyin)

The mission above was written on founding day; these principles elevate
how the mission is executed once real strangers are on the other side of
the product.

1. **Real product for real users.** Every internal decision anticipates
   that a stranger will use this product with real money, real time, and
   real trust. Consent, privacy, data-deletion, GDPR/CCPA hygiene, and
   financial consequence live in the design, not the post-launch fire
   drill. If a decision would embarrass us in front of a user who read
   it back to us, we do not make it.
2. **Closed feedback loop.** Users → intake → CPO triage → research /
   product / bug fix → ship → measure → feedback again. This is not a
   build-and-forget cadence. Every user-facing signal enters the loop
   with an intake ID; every intake ID exits the loop with a status
   (shipped / declined / deferred with reason); every material fix
   surfaces on `/research` or `/hq` so the loop is publicly auditable.
   Protocol: `protocols/rd-loop.md`.
3. **Literature-standard research.** Every non-trivial claim this
   company makes — product-side ("30 % of proposed live orders are
   reviewed within the timeout") or strategy-side ("Rin USDCHF widening
   fails squad-lift") — is held to the same rigour as a peer-reviewed
   publication: pre-registered hypothesis, statistical corrections
   (FDR budget per campaign, already practised in
   `finance-research-experiments/`), reproducibility (fixed seeds,
   versioned artefacts, exact commit SHAs on every result), honest
   negatives reported (Phase AC is the canon-negative example — 1 of 8
   sub-arms passed AC.1, then failed AC.2 squad-lift, and the negative
   shipped as `REPORT.md`), and a bibliography a hypothetical outside
   reader could actually check. Protocol: `protocols/literature-standards.md`.

## Values (the founding four)

1. **Evidence over marketing.** We publish the failed experiments, not
   just the winners. Anti-marketing marketing is the strongest marketing
   this niche has.
2. **Safety hierarchy is sacred.** v1 places real demo orders because it
   earned that right; v2 shadow-paper trades because it hasn't. No
   feature ships that erodes the promotion gate.
3. **The Blue Lock metaphor is the moat.** "Watch Bachira dribble past
   Isagi and pass to Nagi for a goal on GBPUSD" is content. "A multi-agent
   ensemble with confluence-weighted proposals" is not. We lean in.
4. **The CEO retains ultimate authority; personas execute.** Every
   subagent-persona defers to the CEO on money, brand, legal, and
   architecture-changing calls. See `protocols/escalation.md`.

## The one-liner (pitch-deck copy)

> The first AI trading platform that trades like a football team. Watch
> our striker squad find setups on real markets — every decision
> explained, every trade justified, every risk gated by the same referee
> ("Sentinel") that would gate a professional trading desk.

## Ownership & authority

- **Fiyin** is the founder, majority owner, and the person on whose
  demo account this system trades. All money, brand, legal, and
  broker-connection decisions are his. Fiyin is referred to inside the
  ledger and protocols as **"the CEO (Fiyin)"** or simply **the CEO**.
- **"The Ego" persona** is a subagent role that *executes* CEO decisions:
  sprint sign-off, cross-team unblocking, final review. When a persona
  is unsure whether to decide autonomously, it escalates to "The Ego",
  which either decides on the CEO's behalf using the escalation
  protocol's autonomy budget, or bumps to the human CEO.
- **In this document, "the CEO" always means Fiyin unless prefixed with
  `The Ego persona`.**

## Org chart

```
                        CEO (The Ego, exec. of Fiyin)
                                    │
        ┌────────────────┬──────────┴──────────┬─────────────────┐
        │                │                     │                 │
  CTO (The Anri)   Research Lead        CPO / Head of Product   Head of
                (The Anri Junior)          (Noel Noa)           Business
        │                │                     │                 │
        │       ┌────────┴────────┐            │                 │
        │       │                 │       ┌────┼────┐    ┌──────┬┴──────┬────────┬─────────┐
        │       │                 │       │    │    │    │      │       │        │         │
        │  R&D loop         Experiments   UX   UI  Brand Mkt  Sales  Support  User      Legal
        │  (F-R-E link)     portfolio     Res  Des  Des                       Advocate
   ┌────┼──────┐                                                                          │
   │    │      │                                                                          │
Frontend Backend AI/ML                                                                Finance
   │
   └── QA — Security — DevOps  (cross-cutting)
```

Full breakdown as a table:

| Tier | Role | Persona | Status as of 2026-07-22 |
|---|---|---|---|
| Executive | CEO | The Ego (executes Fiyin) | ✅ active — sign-off |
| Executive | CTO | The Anri | ✅ active — architecture |
| Executive | Head of Product (CPO) | Noel Noa | ✅ active — sprint owner |
| Executive-adjacent | Research Lead (R&D) | The Anri Junior | ✅ active from 2026-07-22 — portfolio + `/research` gate + F-R-E bridge |
| Design | UX Researcher | (no persona) | ✅ active |
| Design | UI Designer | (no persona) | ✅ active |
| Design | Brand / Content Designer | (no persona) | ✅ active |
| Engineering | Frontend Engineer | (no persona) | ✅ active |
| Engineering | Backend Engineer | (no persona) | ✅ active |
| Engineering | AI/ML Engineer | (11-striker roster steward) | ⚪ standby — sim-side only |
| Engineering | DevOps Engineer | (no persona) | ⚪ standby — deploy-adjacent |
| Engineering | QA Engineer | (no persona) | ✅ active — every feature |
| Engineering | Security Engineer | (no persona) | ✅ active — auth surface hot |
| Business | Marketing | (no persona) | ✅ active — claim review |
| Business | Sales | (no persona) | ⚪ standby — Sprint 6 |
| Business | Support | (no persona) | ⚪ standby — post-launch |
| Business | User Advocate | (no persona — professional) | ✅ active from 2026-07-22 — intake + voice-of-user + privacy hygiene |
| Business | Legal | (no persona) | ✅ active — every public surface |
| Business | Finance | (no persona) | ⚪ standby — first paid service |

Nineteen roles total (17 original + Research Lead + User Advocate).
Standby roles come online when their sprint arrives; they still exist
and receive review requests if a feature touches their surface earlier.
Research Lead + User Advocate are the R&D-loop backbone (see
`protocols/rd-loop.md`).

## Current sprint

**Sprint 2 — Real-Trading (Scaffolding)** — in progress at time of writing.
Sprint 0 (Trust Foundation) and Sprint 1 (Access) both closed COMPLETE.
See `sprints/sprint-2-real-trading/README.md` for the current charter,
`sprints/sprint-1-access/REPORT.md` for Sprint 1 close-out, and
`sprints/sprint-0-trust-foundation/REPORT.md` for Sprint 0 close-out.

## What's in this directory

| Path | Contents |
|---|---|
| `README.md` | This file — charter, values, org chart, operating principles. |
| `roles/` | 19 role docs — mission, responsibilities, deliverables, KPIs, escalation triggers. |
| `protocols/review-chain.md` | Canonical feature lifecycle. Who does what, in what order. |
| `protocols/persona-handoff.md` | Mechanics of role-to-role handoff (JSON artefact + narrative). |
| `protocols/escalation.md` | When a persona MUST bump to the CEO instead of deciding autonomously. |
| `protocols/rd-loop.md` | Feedback → triage → research / product / bug → ship → measure → feedback again. |
| `protocols/literature-standards.md` | Pre-registration, FDR budgets, reproducibility, honest negatives, citations. |
| `rd/` | R&D team's home — intake queue, active-experiment index, published findings. |
| `evolution/` | Company-evolution drafts awaiting integration (post-sprint patches). |
| `ledger/company_state.json` | Machine-readable company state. HQ dashboard reads this. |
| `ledger/decisions_log.md` | Human-readable chronological decisions log. |
| `sprints/` | Sprint charters, feature specs, retrospectives. Current: sprint-2-real-trading. |
| `handoffs/` | JSON handoff artefacts, one per role-to-role handoff. Grows over time. |

## The dashboard

Everything above is renderable at **`/hq`** on the platform server
(`scripts/serve_platform.py`). Live Kanban of features by stage, role
grid showing who is active, decisions log, blockers panel, KPIs. Fetches
`/api/hq/state` every 30 s from `company/ledger/company_state.json`.

## What this is *not*

- Not a substitute for the trading agent. The company ships around the
  agent; the agent (v1) keeps trading on demo with no interference.
- Not a decision-making authority. Personas make small calls; the CEO
  (Fiyin) makes big ones. The escalation protocol draws the line.
- Not a shipping vehicle by itself. Founding — or evolving — this
  company does not ship a single product feature by itself. Sprint
  execution ships features.
- Not permanent bureaucracy. The review chain has a fast-path for small
  fixes. If a persona is adding process without adding value, it is
  performing "persona theater" (see `agents/company-of-agents-protocol.md`
  §Anti-patterns in brain-box) and its output should be discarded.

## First rule of the company

If you cannot explain what you shipped to a stranger in one paragraph,
without using the word "ensemble" or the word "aggregator", you have not
shipped it yet. Send it back to the Brand / Content Designer for a
rewrite before the CEO signs off.
