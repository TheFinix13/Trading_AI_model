---
id: I002
source: dogfood
submitter: ceo
submitted_at: 2026-07-23T22:50:00Z
classification: FEATURE-REQUEST
priority: P1
status: routed
route: product
linked_features: []
linked_decisions:
  - D088
linked_experiments: []
contact: internal (CEO)
resolved_at: null
history:
  - stage: filed
    at: 2026-07-23T22:50:00Z
    by: user_advocate
    note: "Filed from a direct CEO dogfood observation, 2026-07-23. First intake item sourced from a real user signal (the dogfood owner) rather than a post-mortem."
  - stage: triaged
    at: 2026-07-23T22:50:00Z
    by: cpo
    note: "Triaged in the same cycle-1 drain: FEATURE-REQUEST / P1 / route product. Fix targets next-gen's /v2 page territory -- Sprint 3 / next-gen session candidate. Not implemented in this session by design."
---

# I002 — Dashboard silence is illegible

## What happened

Real user signal from the CEO (Fiyin), 2026-07-23, verbatim:

> "I've been watching the dashboard all week but haven't seen any of
> the agents make a move... I haven't seen any actions from Sae."

The user watched the `/v2` dashboard across the week of Jul 20–24 and
interpreted the absence of agent activity as the agents being broken
or idle.

Root cause context: **the silence was correct behavior.** No NFP
event occurred Jul 20–24 — NFP is first-Friday-of-month, so the next
NFP is Aug 7; the next high-impact USD window for Sae is FOMC
Jul 28–29. The zone strikers were waiting on H4 setups that did not
materialise into proposals in that window. The squad did exactly what
its doctrine says it should: nothing.

The product failure is that healthy silence and broken silence render
identically — an empty feed. The user had no way to distinguish "no
event in window, agents correctly waiting" from "agents crashed /
disconnected / misconfigured".

## Why it matters

- **Trust erosion during correct behavior is the worst kind.** The
  system loses user confidence precisely when it is being
  disciplined. A user who concludes "it doesn't do anything" churns
  before the first real event window arrives.
- **This is the dogfood owner hitting it.** If the CEO — who knows
  the doctrine — reads the silence as inactivity, an external retail
  user has no chance.
- **It compounds.** Event-driven agents like Sae are quiet by design
  most of the time; zone strikers can go days without an H4 setup.
  Illegible silence is therefore the *default* state of the product,
  not an edge case.

## Proposed resolution

Two additions to `/v2`:

1. **"Upcoming events Sae is watching" countdown panel** — driven by
   the economic calendar: next high-impact USD events (e.g. FOMC
   Jul 28–29, NFP Aug 7) with countdowns, so the user can see what
   the event-driven agent is waiting FOR.
2. **"Why quiet" status line** — e.g. "No high-impact USD events in
   window; zone strikers waiting for H4 setups — last evaluated
   N min ago". Makes the negative state an explicit, timestamped,
   self-explaining claim rather than an empty feed.

Together these make healthy silence legible: the dashboard should
always be able to answer "why is nothing happening?" without the
user asking.

## Triage decision (CPO, 2026-07-23 cycle-1 drain)

- **Classification:** `FEATURE-REQUEST`
- **Priority:** `P1` — an active user (the CEO) lost trust in the
  product during correct behavior; next-sprint candidate.
- **Route:** `product`
- **Reasoning:** Not a BUG — the product behaved as specced; the
  spec lacked a legibility requirement for the quiet state. The fix
  is a UI/data feature on `/v2`, which is `next-gen` branch page
  territory — implementing it here would cross the declared branch
  scope. Sprint 3 / next-gen session candidate.
- **Owner from here:** `cpo` (sprint backlog placement) →
  frontend engineer in the next-gen lane.
- **Linked feature spec (if any):** none yet — spec to be written at
  Sprint 3 scoping.
- **Linked experiment pre-registration (if any):** none. A follow-up
  product-side hypothesis ("why-quiet line reduces
  'is-it-broken' support pings") can be declared in the feature spec
  §Hypothesis per literature-standards.md §5 when scoped.

## Closure notes

Open. Closes when the /v2 legibility feature ships (status →
shipped, with the feature spec linked) or is consciously declined at
Sprint 3 scoping.

- **Outcome:** _pending_
- **Measurement (if applicable):** _pending — candidate: recurrence
  of "is it broken?" dogfood reports after ship_
- **User notified:** pending — submitter is the CEO (internal);
  notify at closure.
- **Related decisions:** D088.
