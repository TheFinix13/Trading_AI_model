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
  - stage: amended
    at: 2026-07-23T23:20:00Z
    by: user_advocate
    note: "Root cause REVISED after read-only next-gen investigation (D096). The silence was NOT merely correct quiet-market behavior: two coded-in defects also guaranteed it (200-live-bar warm-up gate silencing strikers ~33 days; Sae hard-disabled and unhydrated on the live path). Fix session in flight on next-gen 2026-07-24 -- this item's /v2 legibility feature is being implemented there, ahead of Sprint 3."
---

# I002 — Dashboard silence is illegible

## What happened

Real user signal from the CEO (Fiyin), 2026-07-23, verbatim:

> "I've been watching the dashboard all week but haven't seen any of
> the agents make a move... I haven't seen any actions from Sae."

The user watched the `/v2` dashboard across the week of Jul 20–24 and
interpreted the absence of agent activity as the agents being broken
or idle.

Root cause context (as filed): **the silence was correct behavior.**
No NFP event occurred Jul 20–24 — NFP is first-Friday-of-month, so
the next NFP is Aug 7; the next high-impact USD window for Sae is
FOMC Jul 28–29. The zone strikers were waiting on H4 setups that did
not materialise into proposals in that window.

The product failure is that healthy silence and broken silence render
identically — an empty feed. The user had no way to distinguish "no
event in window, agents correctly waiting" from "agents crashed /
disconnected / misconfigured".

## Root-cause amendment (2026-07-23, post-investigation — D096)

A read-only investigation of the `next-gen` runtime code revised the
root cause. The silence was **over-determined**: even in a week with
qualifying events and valid H4 setups, the squad could not have acted.

1. **Warm-up gate bug (P1).** `agent/squad/engine.py` withholds all
   proposals until `bars_seen[symbol] > WARMUP_BARS (=200)`, and the
   counter only counts bars arriving after process start — the ~2,500
   historical bars that already hydrate zones/swings/ATR at boot do
   not count. A runtime started 2026-07-20 cannot propose until
   ~late August. Sim-era gate semantics ("bars of context") silently
   became live semantics ("days of uptime").
2. **Sae structurally inert.** `run_squad_live.py` builds the roster
   without a `SaeConfig` (default `sae_enabled=False`, so Sae never
   joins `proposers`); nothing on the live path loads his calendar or
   sets his bars provider; and the H4 evaluation cadence can only
   catch events landing 15–60 min before an H4 bar-open — NFP
   (12:30 UTC) and FOMC (18:00 UTC) never do. Three independent
   blockers.
3. **Failure invisibility (the original framing).** Calendar-fetch
   failures are console-only; Sae/Karasu have no pitch presence; no
   warm-up/burn-in/status surface exists. This item's legibility
   thesis stands — strengthened: the "correct behavior" framing at
   filing time was itself a casualty of the illegibility, since even
   the operators could not see the warm-up gate from the dashboard.

**Fix in flight** (next-gen fix session, 2026-07-24): warm-up seeding
from history + explicit 2-bar burn-in; Sae hydration behind a
default-OFF `--enable-sae` flag (Phase AE pre-reg gate retained);
calendar failure visibility (event rows + rate-limited Telegram);
and this item's `/v2` fixes (upcoming-events panel, why-quiet line,
Sae/Karasu roster presence) — shipping ahead of Sprint 3. The
H4-cadence gap is parked to Phase AE design (Sae likely needs an M15
sub-loop).

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
