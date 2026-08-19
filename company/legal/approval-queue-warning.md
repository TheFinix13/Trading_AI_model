# Approval-queue warning (verbatim)

> This body renders above the pending list on `/approvals`. It is
> the "even approved orders can lose money" note that Legal wants
> visible every time a user is about to click **Approve**.
>
> The auto-execution section renders ONLY while
> `[approvals] auto_execute_on_timeout` is True. While the flag is
> False, the original discard promise applies and that section must
> not be shown.

---

**Approving a proposal sends a real order.**

- Every card below is a proposal from the trading squad. Approving
  a card causes the platform to attempt to send the associated
  order to your broker.
- The kill-switches and risk budget still gate execution after
  approval. If either says "no", the order is not sent even though
  you approved.
- Rejection is safe: rejecting a proposal has no market side-effect.
  The rejection is logged (with your reason, if provided) for the
  audit trail.

If a proposal looks wrong — wrong pair, wrong direction, wrong
size, or anything you don't understand — **reject it**. Live-mode is
one click away at `/settings/live-mode`.

---

## While auto-execution is OFF (default)

- Proposals you ignore expire and are discarded — they do NOT get
  retried automatically.
- Nothing reaches your broker unless you click **Approve**.

---

## While auto-execution is ON

**Ignoring a proposal is not the safe option. Silence sends the order.**

- Each card shows a countdown. That countdown is your window to
  refuse — not a deadline to approve.
- If the countdown reaches zero and you have done nothing, the
  platform treats your silence as authorisation and sends the order
  by itself. The audit trail records this as `auto_approved`,
  resolved by `auto_timeout` — never as your approval.
- **Reject** is the only way to stop a proposal. Closing the page,
  logging out, or leaving it alone does not stop it.
- Once the countdown reaches zero, rejecting no longer works: the
  order is already going out. To get out of a position that has
  already been sent, use **Close** on `/approvals`, or trip the
  kill-switch for that symbol to stop further orders.
- The kill-switches, risk budget and live-mode switch still apply.
  Auto-execution removes the need for your click and nothing else —
  every other refusal still refuses.
- If the platform is not running when a countdown would have
  expired, the proposal is dropped rather than fired late.

This arrangement means the platform can open positions while you are
asleep or away from the machine. That is its purpose, and it is also
its risk. If you are not willing to have an order placed without
seeing it first, turn auto-execution off.
