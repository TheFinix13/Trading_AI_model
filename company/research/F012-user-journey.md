# F012 — User journey: `/risk` dashboard + budget headroom

**Persona:** Yoichi (curious, wants to see numbers before he trusts the
platform). Also fits Isagi's power-user lens later.

**Trigger:** After configuring a broker (Sprint 1 F007) and installing
kill-switches (F011), the trader wants a single glance at *how much
money the platform is allowed to lose today* and *whether the broker
would even accept an order right now*.

## 1. Landing on `/risk`

Yoichi hits `/risk` from the top-nav (added Sprint 2). The page shows
three panels stacked on desktop, one column on mobile:

- **Live exposure** — open positions, lot size, current price
- **Budget headroom** — three progress cards (per-day / per-symbol /
  per-strategy) each with `remaining / cap` and `% consumed`
- **Broker connections** — status per configured alias, colour-coded

## 2. Reading the budget

For a clean install the three headroom cards render:

| Scope       | Cap    | Used   | Remaining |
|-------------|--------|--------|-----------|
| Per-day     | $100   | $0     | $100      |
| Per-symbol  | $50 ea | $0     | $50 ea    |
| Per-strategy| $50 ea | $0     | $50 ea    |

Yoichi understands "if the day's realised losses hit any of those caps
the platform will refuse to send further orders on that scope". He does
NOT expect wins to reset the cap -- the caveat is in the Sprint 2
disclaimer at the bottom of the page.

## 3. Editing budgets

Yoichi hits "Edit budgets" (deferred to a follow-up sprint; Sprint 2
ships the API only; power users can `POST /api/risk/budgets` from a
script).

## 4. Checking broker connectivity

The Broker connections panel lists his `main-broker` alias with
`account_type=demo`, `alive=true`, `checked_at=<15s ago>`, `cached=true`.
If the probe were failing he'd see `alive=false` and a human error like
`"connection refused"`, never a password.

## 5. Trust receipts he needs

- "This budget is enforced BEFORE any order is sent" -- documented via
  the Sprint 2 caveat block.
- "The broker probe uses a 30-second cache" -- documented on the panel.
- "Live-mode is OFF; nothing is going to send even if the numbers say
  it could" -- pinned banner at the top of `/risk`.

## 6. Handoff into F013

F012's `can_send_order` is the THIRD live-mode-off gate. F013's approval
queue is the FOURTH. F012's page is the honest window into "here is what
the gate will say". Yoichi trusting the numbers here is the pre-condition
for him ever trusting the toggle in F013.
