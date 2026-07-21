# Blue Lock Trading Co. — Founding Charter

> **The first AI trading platform that trades like a football team.**
> Watch our striker squad find setups on real markets — every decision
> explained, every trade justified, every risk gated.

Founded 2026-07-21. Sprint 0 in flight (target: 2026-08-04).

---

## Mission

Turn the multi-pair AI trading prototype into a **product a stranger can
trust**. Every artifact this company ships must strengthen one of three
pillars, in this order:

1. **Trust foundation** — public evidence, transparent research, human
   language. If a prospect cannot look at the platform for two minutes and
   understand what it does and why, we have shipped nothing.
2. **Access** — turn viewers into users. Sign-up, broker connection,
   per-user data, first-time setup.
3. **Stickiness** — turn users into fans. Character seasons, match
   highlights, strategy marketplace, community.

Trust before access. Access before stickiness. **Never invert the order.**

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
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
        CTO (The Anri)       CPO / Head of Product   Head of Business
                                (Noel Noa)          (rotates: Sales/Mkt)
              │                     │                     │
   ┌──────────┼──────────┐    ┌─────┼─────┐   ┌──────┬───┴───┬─────────┐
   │          │          │    │     │     │   │      │       │         │
Frontend  Backend    AI/ML   UX    UI  Brand Mkt   Sales  Support   Legal
 (Isagi   (Reo    (Isagi'70 Res.  Des.  Des.
  finish) build)  striker
                  ops)
   │                                                                  │
   └── QA — Security — DevOps  (cross-cutting)                    Finance
```

Full breakdown as a table:

| Tier | Role | Persona | Sprint-0 active? |
|---|---|---|---|
| Executive | CEO | The Ego (executes Fiyin) | ✅ yes — sign-off |
| Executive | CTO | The Anri | ✅ yes — architecture |
| Executive | Head of Product (CPO) | Noel Noa | ✅ yes — sprint owner |
| Design | UX Researcher | (no persona) | ✅ yes — F001/F002/F003 |
| Design | UI Designer | (no persona) | ✅ yes — F001/F002/F003/F004 |
| Design | Brand / Content Designer | (no persona) | ✅ yes — copy on F001–F005 |
| Engineering | Frontend Engineer | (no persona) | ✅ yes — F001/F002/F003/F004/F005 |
| Engineering | Backend Engineer | (no persona) | ✅ yes — F001 data plumb, F003 |
| Engineering | AI/ML Engineer | (11-striker roster steward) | ⚪ standby — F002 stats source only |
| Engineering | DevOps Engineer | (no persona) | ⚪ standby — Sprint 1+ |
| Engineering | QA Engineer | (no persona) | ✅ yes — every feature |
| Engineering | Security Engineer | (no persona) | ⚪ standby — auth-touching only |
| Business | Marketing | (no persona) | ✅ yes — F003 copy review |
| Business | Sales | (no persona) | ⚪ standby — Sprint 6 |
| Business | Support | (no persona) | ⚪ standby — post-launch |
| Business | Legal | (no persona) | ✅ yes — F001 disclaimers |
| Business | Finance | (no persona) | ⚪ standby — first paid service |

Ten roles active in Sprint 0, seven on standby. Standby roles come online
when their sprint arrives; they still exist and receive review requests
if a feature touches their surface earlier.

## Current sprint

**Sprint 0 — Trust Foundation** (2026-07-21 → 2026-08-04)

Ship the five features that turn the prototype into something showable
to prospects:

| ID | Title | Priority |
|---|---|---|
| F001 | Public `/performance` route (equity curve, drawdown, Sharpe, win rate) | P0 |
| F002 | `/players/:id` character bio + career stats | P0 |
| F003 | `/research` timeline (Phase AC verdicts, anti-marketing marketing) | P0 |
| F004 | Mobile-responsive pass on hub + /v1 + /v2 + /hq at 375px | P0 |
| F005 | Loading skeletons + friendly error-state recovery | P0 |

See `sprints/sprint-0-trust-foundation/README.md` for the full charter.

## What's in this directory

| Path | Contents |
|---|---|
| `README.md` | This file — charter, values, org chart, current sprint. |
| `roles/` | 17 role docs — mission, responsibilities, deliverables, KPIs, escalation triggers. |
| `protocols/review-chain.md` | Canonical feature lifecycle. Who does what, in what order. |
| `protocols/persona-handoff.md` | Mechanics of role-to-role handoff (JSON artefact + narrative). |
| `protocols/escalation.md` | When a persona MUST bump to the CEO instead of deciding autonomously. |
| `ledger/company_state.json` | Machine-readable company state. HQ dashboard reads this. |
| `ledger/decisions_log.md` | Human-readable chronological decisions log. |
| `sprints/sprint-0-trust-foundation/` | Current sprint charter, 5 feature specs, backlog for sprints 1–6. |
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
- Not a shipping vehicle by itself. Founding this company does not ship
  a single product feature. Sprint 0 execution ships features.
- Not permanent bureaucracy. The review chain has a fast-path for small
  fixes. If a persona is adding process without adding value, it is
  performing "persona theater" (see `agents/company-of-agents-protocol.md`
  §Anti-patterns in brain-box) and its output should be discarded.

## First rule of the company

If you cannot explain what you shipped to a stranger in one paragraph,
without using the word "ensemble" or the word "aggregator", you have not
shipped it yet. Send it back to the Brand / Content Designer for a
rewrite before the CEO signs off.
