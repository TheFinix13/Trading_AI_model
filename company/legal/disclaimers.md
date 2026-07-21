# Legal disclaimer library

Canonical disclaimer text for user-visible surfaces. Each entry has
a **key** referenced by feature specs and code comments, the
**required copy** (verbatim), and the **when it fires** clause so a
future feature author knows whether they need it.

CEO signoff required to change any entry; propose changes via a
`D###` decision in `company/ledger/decisions_log.md` prefixed
`[LEGAL]`.

## `performance` (F001)

**Copy (verbatim):**

> **Past performance is not indicative of future results.**
>
> These numbers are from a demo (paper-money) MetaTrader 5 account.
> The v1 zones agent places real orders on that demo account; the
> v2 striker squad runs in shadow-paper mode and never sends orders
> to the broker. No real capital is at risk. Nothing on this page
> is investment advice or a solicitation. The Sharpe metric (when
> shown) is a raw daily-pip Sharpe annualised by √252 — use it as
> a sanity ratio, not a target.

**Where:** Footer of `/performance`. Any surface that displays
account-level performance numbers (P&L, drawdown, Sharpe) must
carry this disclaimer or a Legal-approved equivalent.

**Rationale:** Past-performance boilerplate is the industry-standard
disclaimer; the "demo / shadow-paper" clause is the
platform-specific truth-in-source clause the CEO explicitly wants
visible.

## `third-party-name-usage` (F002)

**Copy (verbatim):**

> Blue Lock is a manga / anime by Yusuke Nomura and Muneyuki
> Kaneshiro, published by Kodansha. Characters here are named as
> homage to describe our AI agents' trading playstyles; no
> affiliation, endorsement, or commercial arrangement is claimed.

**Where:** Footer of `/players`, `/players/:id`, `/v2`. Any user-
visible page that names Blue Lock characters must carry this
disclaimer.

**Rationale:** IP posture. Names are used as playstyle metaphors,
not as commercial affiliation. See
`company/legal/blue-lock-ip-notice.md` for the full IP-usage
analysis + fallback naming plan if Kodansha ever objects.

## `research-verdict` (F003)

**Copy (verbatim):**

> Every verdict below is the result of a pre-registered experiment
> on historical market data. "Alive" and "dead" refer to whether
> a mechanism passed the study's specific promotion criteria — not
> to whether it would work on future markets. False-discovery-rate
> corrections are applied across each experiment family; individual
> "alive" verdicts do not compose into a portfolio-level claim.

**Where:** Below the `/research` page's preamble, above the first
verdict card.

**Rationale:** Prevents any single "alive" verdict being interpreted
as a live-trading recommendation. FDR framing is the receipt-trail
component of the anti-marketing-marketing thesis.

## `dashboard-transparency` (`/hq`, no auth surface yet)

**Copy (verbatim):**

> The HQ dashboard is an internal operating view of how features
> get built. Numbers on this page describe process health (feature
> stage, blockers, decisions), not investment outcomes.

**Where:** Bottom of `/hq`. Currently not rendered — the /hq page's
own footer references the source ledger, which is judged
sufficient. Left in the library as a placeholder for Sprint 2+
when auth lands.

**Rationale:** Ensures the process dashboard is never confused with
a performance dashboard, especially if a screenshot circulates.

## Claim register (running list of every public performance claim)

| Feature | Claim | Verified against | Signed off by |
|---|---|---|---|
| F001 | "42 closed trades on tape" (example) | agent/platform/performance.py::trades_total | ceo |
| F001 | "+512.4 net pips" (example) | agent/platform/performance.py::net_pips | ceo |
| F001 | "Worst drawdown -84.2 pips" (example) | agent/platform/performance.py::worst_dd_pips | ceo |
| F001 | Sharpe (only when ≥ 30 daily returns) | agent/platform/performance.py::_sharpe_or_null | ceo |
| F003 | Individual verdict labels (`alive`, `dead`, etc.) | Research repo REPORT.md per-experiment | cpo |

Every entry must trace to a code path that computes the number.
Adding a new number to a public page without a claim-register entry
is a `[LEGAL]` violation surfaced at feature signoff.

## Banned public claims

The following claims are NEVER allowed on user-visible surfaces
without a fresh CEO signoff (each one either can't be substantiated
from the raw numbers, or crosses a regulatory line):

- "We outperform the market."
- "Our strategy beats [any benchmark]."
- "You can expect [X %] returns."
- "This is a proven strategy."
- "Trading with us is safe."
- "AI removes emotion from your trading." (marketing but false)
- Any past-performance number extrapolated forward ("annual return
  of X %" from a partial-year sample).
- Any user testimonial (no users yet — Sprint 1+).

## Legal sign-off log

- **2026-07-21 · F001** — disclaimer text approved for
  `/performance`; claim register updated with the 4 KPI numbers
  that render on that page.
- **2026-07-21 · F002** — IP notice approved for `/players` and
  `/players/:id` (see `blue-lock-ip-notice.md`).
- **2026-07-21 · F003** — research-verdict disclaimer approved for
  `/research` preamble.
