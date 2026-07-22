# F013 — User journey: `/approvals` + `/settings/live-mode`

**Persona:** Meguru (curious operator who wants to trust the platform
with real money, but only after seeing the queue behave for a few
days first).

**Trigger:** Meguru has completed onboarding, saved a broker, added
kill-switches and reviewed the /risk dashboard. He now wants to see
whether he can actually enable live-mode -- but with clear friction
so he can't do it by accident.

## 1. Landing on `/settings/live-mode`

- Big banner: **OFF -- no live orders will be sent.**
- Below the banner: a "Enable live mode" section that renders the
  verbatim `live-mode-warning.md` inside a scrollable box.
- Below the warning: the ceremony.
  - Checkbox: "I understand this will place real orders with real money."
  - Text input requiring the exact phrase `ENABLE LIVE MODE`.
  - "Enable" button, disabled until BOTH checks pass.
  - Cancel link back to `/hq`.

Meguru CANNOT enable live-mode by clicking the button until he:

- Ticks the checkbox.
- Types the confirmation exactly (case + spacing pinned).

If either check is relaxed by future code, the P0
`test_live_mode_off_invariant.py` test fails and the sprint stops.

## 2. Enabling live-mode

Meguru satisfies both checks. Clicks Enable. The page reloads with:

- **ON -- live orders are authorised** in the red state indicator.
- A "Turn off live mode" button (one click, no ceremony).
- Links to `/approvals`, `/settings/kill-switches`, `/risk`.

The keyring now holds `namespace="bluelock", key="live_mode_enabled",
value="true"`. Any keyring error on the next read returns False (fail
closed) -- Meguru would see OFF again and would need to re-do the
ceremony.

## 3. Landing on `/approvals`

Empty state: "Nothing resolved yet." above a "No proposals yet"
message under the pending section. The verbatim
`approval-queue-warning.md` renders above -- Meguru reads it and
understands that:

- Every approval sends a real order (subject to the other 3 gates).
- Timeouts are 5 minutes; ignored proposals expire and are discarded.
- Rejection is safe -- has zero market side-effect.

## 4. The (deferred) live pathway

Sprint 2 does NOT wire the squad's proposal path to the approval
queue's `submit(...)` API. Meguru will not see any proposals on the
queue until a future sprint delivers the integration. That's the
D065 SCAFFOLDING invariant -- Meguru sees the CEREMONY and the
QUEUE, but the pipeline that feeds them is intentionally absent.

The queue does accept manual `POST /api/approvals/submit` for the
integration test's benefit, but the endpoint is gated by an
internal-only token (`[internal].token` in `platform.toml`,
default empty == fails closed).

## 5. Approving a proposal (future scenario)

For docs completeness, the interaction if a proposal were on the
queue:

- Big Approve (green) and Reject (red) buttons per card.
- Reason textarea appears only on the Reject path.
- Countdown timer per card: "timeout in 04:47".
- After clicking Approve, the page re-fetches and the card moves to
  the "Recent" section with an `approved` pill.
- Meguru can now expect an order to hit the broker -- ASSUMING the
  other three gates (live-mode ON, kill-switch off, risk-budget
  ok) are all clear. If any is not, no order sends even though
  Meguru approved.

## 6. Trust receipts

- "Live-mode is one click away at `/settings/live-mode`" -- pinned
  in the Sprint 2 disclaimer under the pending list.
- "The 4-check pathway is the only pathway a future live-order flow
  can travel" -- Meguru can read the code (Legal claim register
  cites it) or trust the P0 invariant test that pins it.

## 7. Handoff into F014

F014 replaces the 3-second poll with a live SSE stream and adds
Telegram notifications. Meguru can then step away from the browser
without missing a proposal.
