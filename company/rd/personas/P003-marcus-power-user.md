---
id: P003
name: Marcus Bell
archetype: power user / quant hobbyist (keyboard-driven)
goals:
  - Approve or reject every proposed trade himself
  - Get alert events pushed, not polled
  - Poke the APIs directly with curl before trusting the UI
risk_tolerance: high
devices:
  - Linux desktop, three monitors
  - Terminal + browser side by side
tests:
  - approvals
  - alerts
  - broker
---

# P003 — Marcus Bell (power user / quant hobbyist)

Marcus reads the API before he reads the page. He wants the approval
queue to be airtight (submit gated by the internal token, fail-closed
when unset), alert events to arrive on the bus the moment they fire,
and error payloads that tell him exactly why a request was refused —
including the broker rate limiter kicking in when he hammers
`test-connection` from a retry loop.

His journeys: approvals submit/approve/reject through the
internal-token seam (plus the deliberate no-token 401 check), the
alerts test-event round-trip, and the broker failure paths including
the 5-attempts-per-minute limiter. Vague error messages are his
intake candidates.
