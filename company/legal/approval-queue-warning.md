# Approval-queue warning (verbatim)

> This body renders above the pending list on `/approvals`. It is
> the "even approved orders can lose money" note that Legal wants
> visible every time a user is about to click **Approve**.

---

**Approving a proposal sends a real order.**

- Every card below is a proposal from the trading squad. Approving
  a card causes the platform to attempt to send the associated
  order to your broker.
- The kill-switches and risk budget still gate execution after
  approval. If either says "no", the order is not sent even though
  you approved.
- Timeouts are 5 minutes by default. Proposals you ignore expire
  and are discarded — they do NOT get retried automatically.
- Rejection is safe: rejecting a proposal has no market side-effect.
  The rejection is logged (with your reason, if provided) for the
  audit trail.

If a proposal looks wrong — wrong pair, wrong direction, wrong
size, or anything you don't understand — **reject it** or let it
time out. Live-mode is one click away at `/settings/live-mode`.
