# Escalation Protocol

When a persona (a subagent) MUST escalate to the CEO (Fiyin) rather
than deciding on its own.

## The autonomy default

**A persona decides autonomously unless the decision matches one of
the mandatory-escalation categories below.** Autonomy is the default
because the review chain already forces cross-persona review; adding
a CEO check to every decision would collapse the whole company back
into "user in the loop for everything".

When a persona decides autonomously, it:

1. Makes the decision.
2. Logs it in `company/ledger/decisions_log.md` (one bullet, prefix
   `[persona-decision]`).
3. Continues.

## Mandatory escalation (never decide autonomously)

The six non-negotiables. Any decision matching any of these MUST
escalate — the persona **halts**, writes a blocker with
`awaiting_ceo: true`, and waits.

### 1. Money

Any decision that would cause real money to leave any account.

Includes:
- Subscriptions (SaaS tools, hosting, monitoring, analytics, email,
  DNS, TLS certs beyond free tier, CI minutes beyond free tier).
- API credits (OpenAI, Anthropic, Twilio, SendGrid, market-data
  feeds, news APIs beyond free tier).
- Domain purchases / renewals.
- One-time tool purchases.
- Contractor / freelancer engagements.
- Advertising spend.

The Finance role produces a shopping list (2–3 vendors, prices,
recommendation) and hands to the CEO. The CEO authorises. Nobody
else spends money.

### 2. Brand-defining decisions

Any decision that changes how the company presents itself publicly.

Includes:
- Product name changes.
- Tagline / one-liner changes.
- Pricing tier definitions.
- Colour palette / typography / logo changes.
- Domain name choice.
- Public positioning statements ("we are the … in the space").
- Public claim on the /performance page beyond what the raw numbers
  render.

Marketing + Brand Designer + Legal draft; CEO decides.

### 3. Legal risk

Any decision that changes the company's legal posture.

Includes:
- Disclaimer text (any change or new disclaimer).
- Terms of Service clauses.
- Privacy Policy clauses.
- Third-party IP usage (Blue Lock character names, broker names).
- Any public performance claim.
- Response to a regulator inquiry.
- Response to a user's legal-toned complaint.
- Refund / compensation offers.
- Data-deletion / data-export requests (GDPR/CCPA).

Legal drafts; CEO signs off before it goes public or to the person
who asked.

### 4. Architectural changes affecting > 3 modules

Any code change whose blast radius crosses 3+ modules.

Includes:
- New cross-cutting abstraction (a new base class every module
  imports).
- Refactor renaming a public API function used in 3+ places.
- Any change touching `agent/live/`, `agent/squad/engine.py`,
  `agent/squad/sentinel.py`, `agent/squad/aggregator.py`,
  `agent/risk/`, or the paper broker.
- Any schema change to `state.json`, `events.jsonl`, or
  `workspace_snapshot.json`.
- Introduction of a new PyPI dependency.
- Change to `platform.toml` schema.

CTO reviews first; if CTO wants to green-light, they must still
escalate to CEO for module-count ≥ 3.

### 5. Real-broker connections

Any decision that would let code send an order to a broker where the
account holds real (non-demo) money.

**This one is a hard NO on this repo.** No persona is authorised to
enable a real-broker connection under any circumstances. If a
prospect / user / persona asks for it, the request is logged and
escalated — the CEO's answer will always be "not on this repo".

### 6. Suppression of a research negative

Any decision that would result in a completed research study NOT
being published — because the answer was unwelcome — is a hard
escalation. Research Lead surfaces the finding; CEO decides the
publication path (immediate, delayed with reason, or archived with
reason). "Never published" is not an option per
`literature-standards.md` §9 non-negotiable #5.

## Discretionary escalation (persona should escalate if uncertain)

Beyond the five non-negotiables, personas SHOULD escalate when:

- The decision would set a precedent that changes how future
  features are built.
- Two personas disagree at a handoff and the disagreement is not
  purely engineering (CTO's tie-break) or purely product (CPO's
  tie-break).
- The decision reveals a strategic gap that isn't in any planned
  sprint.
- The decision would consume > 1 day of a persona's work not
  currently on the sprint plan.
- The persona feels the CEO would be angry to discover it later.
  ("Angry" is a signal; act on it.)

Discretionary escalation is not free — it costs the CEO's attention.
Persona should:

1. State the decision needed in one sentence.
2. State the 2–3 options considered.
3. State the persona's own recommendation and why.
4. Ask.

## Escalation mechanics

Persona escalating:

1. Adds a blocker to the feature row in `company_state.json`:
   ```json
   "blockers": [{
     "raised_by": "ui_designer",
     "raised_at": "2026-07-22T09:00:00Z",
     "summary": "Colour-blind palette conflict — equity curve",
     "options": ["Use blue/orange instead of green/red",
                 "Keep green/red but add pattern overlays",
                 "Keep green/red and label with pattern in accessibility mode"],
     "recommendation": "Blue/orange — simplest, matches accent tokens",
     "awaiting_ceo": true
   }],
   "awaiting_ceo": true,
   ```
2. Adds a decisions-log bullet marked `[ESCALATION]`.
3. **Halts on this feature.** Moves to other work. Does not proceed
   on a "best guess" — the whole point of escalation is that the
   guess is unsafe.

The HQ dashboard's Blockers panel surfaces every feature with
`awaiting_ceo: true`. The CEO clears the blocker with a decision:

1. Updates `blockers[]` — either removes the entry (decision made)
   or annotates it with `resolved_by: "ceo"`, `resolved_at: "..."`,
   `decision: "..."`.
2. Sets `awaiting_ceo: false`.
3. Adds a decisions-log bullet with the reasoning.
4. Notifies the escalating persona to resume.

## Autonomy budgets by role

Each role has a soft budget for autonomous decisions per sprint. If
a role would exceed its budget on a single feature, it escalates.

| Role | Autonomy budget per sprint | Typical spend |
|---|---|---|
| CPO | 15 decisions | Feature scope trims, priority calls, handoff routing |
| CTO | 20 decisions | Module structure, test choices, small refactors |
| UX Researcher | 10 decisions | Segment selection, journey step framing |
| UI Designer | 15 decisions | Component patterns, colour tokens (within palette) |
| Brand Designer | 20 decisions | Copy phrasing (within tone guide) |
| Frontend | 25 decisions | Implementation choices, CSS classes, test structure |
| Backend | 20 decisions | Module split, cache pattern, endpoint shape |
| AI/ML Engineer | 5 decisions | Everything else escalates given roster sensitivity |
| DevOps | 5 decisions | Anything money-adjacent escalates |
| QA | 15 decisions | Test scope, bug prioritisation |
| Security | 5 decisions | Anything auth-changing escalates |
| Marketing | 5 decisions | Anything public-facing escalates |
| Sales | 5 decisions | Anything customer-facing escalates |
| Support | 15 decisions | FAQ answers, SLA calls (within policy) |
| Legal | 3 decisions | Almost everything escalates |
| Finance | 0 decisions | **Every spend escalates by construction** |
| Research Lead | 10 decisions | Campaign scoping, PROTOCOL revisions pre-compute, finding-promotion gates, negative-publication timing |
| User Advocate | 15 decisions | Intake classification suggestions (CPO retains final), notify-message tone, retention-window calls within Legal policy |

Budgets are soft — a persona over budget is a signal, not a
violation. Systematic over-budget is a sign the role's autonomy
should be widened (or the CEO is over-involved).

## What escalation is not

- **Not a way to duck responsibility.** A persona can't escalate a
  decision that is squarely within its remit ("what CSS class name
  should I use?") to save the effort of deciding.
- **Not a way to punt on hard calls.** If the persona has the
  information to decide and the decision is in-remit, deciding is
  the job.
- **Not a status update.** Blockers with `awaiting_ceo: true` are
  requests for a decision. Progress reports go in the ledger and
  the HQ dashboard, not as blockers.
- **Not immediate.** The CEO answers escalations in the CEO's own
  cadence. Persona waits or pivots to other work — never guesses.
