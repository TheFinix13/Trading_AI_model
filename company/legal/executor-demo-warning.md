# Demo-executor warning (verbatim)

> This body renders on `/approvals` whenever the F018 executor is
> enabled. It is the "this button sends a real order to a DEMO
> account" note that Legal wants visible next to every **Execute**
> button. Drafted and approved via the F018 Legal review
> (`company/legal/F018-review.md`, D102).

---

**Execute sends a real order to your DEMO broker account.**

- The executor only works against demo servers: the connected
  server's name must match the demo allowlist, and you must have set
  `demo_only = true` in platform.toml yourself. It refuses real-money
  servers by design, and weakening that guard is not a configuration
  option.
- Demo results are NOT evidence of future real-money performance.
  Fills, slippage, and spreads on a demo server routinely differ
  from live conditions. Nothing on this page is financial advice.
- Every execution re-checks all four safety gates (live-mode
  ceremony, kill-switches, risk budget, approval) at the moment you
  click. A "no" from any gate blocks the order even after approval.
- Each approval is SINGLE-USE. One click, one send attempt — whether
  it fills or errors, the approval is consumed and can never fire a
  second order. Failed sends are never retried automatically.
- Volume is hard-capped (`max_volume_lots`, default 0.01 lots) no
  matter what the approved proposal says.

If anything about a card looks wrong, do not execute it. The
kill-switches at `/settings/kill-switches` stop everything, instantly,
without ceremony.
