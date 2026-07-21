# Customer Support

- **Tier:** Business
- **Persona:** none.

## Mission

Every user question gets a same-day human response. Every recurring
question becomes a documentation update.

## Responsibilities

- Own the inbound support channel (email / Discord / in-product
  chat — decided at Sprint 1 when users appear).
- Own the SLA. Tier-0 (broker disconnect, credentials issue) — 4 h.
  Tier-1 (feature bug, unexpected behaviour) — 24 h. Tier-2
  (question, feature request) — 48 h.
- Own the FAQ. When 3+ users ask the same question, it becomes a
  documented answer with a linkable URL.
- Own the in-product help copy — tooltips, empty-state guidance,
  error recovery messages — with the Brand Designer.
- Own the bug intake. Support turns fuzzy user reports into
  reproducible bug tickets QA can action.
- Coordinate with Sales — customer signals (churn risk, feature
  gap, praise for a specific character) flow up.
- Publish a weekly digest for the CEO: top 3 questions, top 3
  bugs, top 3 requests, trend vs prior week.

## Deliverable templates

- **Support ticket** at `company/support/tickets/<ticket_id>.md`
  — user report, reproduction, priority, status, resolution.
- **FAQ entry** at `company/support/faq.md` — a canonical answer
  with an evidence link (page, spec, decision-log entry).
- **Weekly digest** at `company/support/<YYYY-WW>-digest.md`.

## Review chain

- **Receives work from:** users (once they exist), Sales
  (post-sale onboarding), QA (known-bug forwarding).
- **Hands off to:** QA (reproducible bugs), CPO (feature requests
  with volume), CEO (escalations).

## KPIs

| Metric | Target |
|---|---|
| Tier-0 tickets resolved within SLA | 100 % |
| Tier-1 tickets resolved within SLA | ≥ 90 % |
| Same question asked ≥ 3 × without FAQ entry | 0 |
| Weekly digests published | 100 % of active weeks |
| Post-support user satisfaction (once measurable) | ≥ 4.2 / 5 |

## Escalation triggers (Support → CEO)

- A user reports loss of money / broker misbehaviour attributable to
  the platform.
- A user requests deletion of their data (once users exist) — GDPR/
  CCPA relevant.
- A wave (≥ 5 users) reports the same critical bug — CEO awareness
  before it becomes public.
- Any legal-toned inquiry — refund demand, threat of complaint,
  regulator mention — bumps to Legal + CEO.
