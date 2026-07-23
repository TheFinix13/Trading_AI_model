---
id: P001
name: Fiyin
archetype: CEO / dogfood owner
goals:
  - Watch the squad work without babysitting a terminal
  - Know at a glance whether silence is healthy or broken (I002)
  - Verify every public claim before it ships
risk_tolerance: medium
devices:
  - macOS desktop (primary)
  - iPhone (checks /v2 + /hq on the go)
tests:
  - onboarding
  - broker
  - kill_switch
  - approvals
  - alerts
  - research
  - hq_org
  - pages
---

# P001 — Fiyin (CEO, dogfood owner)

The real user. Runs the platform daily on the demo account, watches
`/v2` and `/hq`, and files intake items when the product confuses him
(I002 "Dashboard silence is illegible" came from exactly this seat).
As dogfood owner he exercises every surface, so his journey in the
script is the union of all the others — if a flow breaks for anyone,
it should break for P001 first.

What he cares about: honest state (no fake green), legible silence,
the kill switch always one tap away, and `/research` never claiming
more than the artifacts support.
