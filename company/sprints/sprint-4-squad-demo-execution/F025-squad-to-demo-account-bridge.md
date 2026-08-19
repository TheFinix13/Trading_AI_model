# F025 — Squad → $500 demo account: the bridge that does not exist yet

- **Sprint:** sprint-4-squad-demo-execution (NEW sprint, per D065's
  requirement that any commit adding `approval_queue.submit(...)` on a
  live pathway ships under a new sprint with fresh security + legal
  reviews).
- **Status:** `CHARTERED, NOT STARTED` — 2026-08-19. Nothing in this
  document is implemented. Written so the operator ask is scoped
  honestly rather than answered with a flag flip that would not work.
- **Priority:** P1 — the operator's stated destination for v2.
- **Lane:** Real-Trading integration, DEMO ONLY.
- **Consumes:** F018 `live_executor.execute_approved` (and its four
  gates), F013 approval queue, F012 risk budget, F011 kill switches,
  F007 broker credentials, `agent/squad/engine.py`, `paper_broker.py`,
  `sentinel.py`.
- **Feature flags:** `auth: true`, `credentials: true`,
  `security_relevant: true`, `legal_relevant: true`.

## Operator ask (verbatim intent, 2026-08-19)

> "we already have this account and we also set it up on the vmware in
> another chat so can v2 start using this. ideally it should be 100$ but
> we will start with 500 instead and see how long it takes for them to
> reach 1000$ from the 500$"

The destination is right and this document does not argue against it.
What it argues is that the ask is a **feature**, not a setting, and that
shipping it as a setting would produce an account nobody can reconcile.

## Where things actually stand

**What already works today (no new code):** the squad paper book can run
$500 semantics. `run_squad_live.py --equity 500`, or — as of commit
`97b1fac` — `equity = 500` under `[squad_live]` in `platform.toml`, which
was documented but silently unparsed before that fix. This changes
Sentinel R1's per-trade cap from $5 to $25, i.e. the maximum admissible
stop goes from 50 to 250 pips on EURUSD (and from 10 to 50 on XAGUSD,
which is why the AN-3 field card required it). It is a paper book that
mirrors the real account's size.

**What does not work:** the squad placing an actual order. There is no
code path from a Sentinel-passing proposal to the broker. `_admit()`
ends at `PaperBroker.open_from_proposal` and an `open` row on the tape.
`live_executor` has exactly one caller — the human **Execute** button on
`/approvals` — and `run_squad_live.py` does not import it,
`approval_queue`, or anything else on that path. F018's own scope
section lists "Squad → `approval_queue.submit` wiring" as out of scope.

So the gap is not a disabled flag. It is a missing component.

## The eight blockers (each is real work, in dependency order)

### B1 — The proposal→approval bridge (the actual feature)

Nothing calls `approval_queue.submit()` except `serve_platform.py:962`
on behalf of a human. A bridge must construct
`{symbol, side, size, entry, stop, take_profit, rationale, source_agent,
risk_snapshot: {worst_case_loss}}` from an `AgentProposal`, which carries
none of `side`, `size`, or `worst_case_loss` — `side` must be derived
from `direction`, `size` must be *decided*, and `worst_case_loss` must be
computed as `sl_pips × lot × pip_value_per_lot_for(symbol)`.

Governance: D065 and `company/handoffs/F013-legal-to-ceo.json` make this
a new-sprint + fresh-security-and-legal-review event. Non-negotiable.

### B2 — The lot-size contradiction (would refuse 100 % of orders)

The squad fills at `FIXED_LOT = 0.1`. The executor hard-caps at
`max_volume_lots = 0.01` and refuses anything above it. Every
squad-sized order would be refused on gate 8.

Two options, both requiring a decision:

- Submit `size = 0.01`. Orders go through, but the paper book and the
  broker book diverge 10×, so the leaderboard stops describing the real
  account and the "$500 → $1000" question becomes unanswerable.
- Raise `max_volume_lots`. This trips `F018-review.md` rolling
  constraint #1 ("raising the `max_volume_lots` default … requires a
  fresh Legal review of this file") and removes a real safety bound.

Recommendation: raise the cap deliberately under this sprint's legal
review, to a value derived from the account size rather than inherited,
and pin it in `platform.toml` with the derivation written down.

### B3 — The R1-vs-fill risk mismatch (a correctness bug, not a policy)

Sentinel R1 measures risk at **min lot (0.01)** but the broker fills at
**0.1**. A 50-pip EURUSD stop passes R1 at $5 (5 % of a $100 book) while
the position actually risks `50 × 0.1 × $10 = $50` — 50 % of that book.
On paper this is a scoreboard artefact. Routed to a real account it
makes the advertised "5 % per trade" cap wrong by 10×.

This must be fixed **before** B1, not after. It is the single most
dangerous item in the list.

### B4 — Nobody closes positions

`Mt5OrderAdapter.close_position` exists, has no caller and no HTTP route
(`sprint-2b/REPORT.md` says so outright). Orders would go out with SL/TP
attached and then be broker-managed, while the squad's own `_check_exit`
closes the *paper* trade and the real position lives on independently —
including through the time-stop gap that let Bachira's GBPUSD short run
5 days against a 24 h target.

### B5 — No magic number, so orders are unidentifiable

`send_market_order` sets no `magic`. Orders from the v2 executor are
indistinguishable from anything else on the account. Reconciliation,
"close only my positions", and any post-hoc attribution all require one
first. Add it before the first order, not after.

### B6 — The risk budget never accumulates

`execute_approved` calls `record_fill(symbol, source_agent, 0.0)` —
literal zero. Only negative PnL counts against the per-day $100 /
per-symbol $50 / per-strategy $50 caps, so those caps read as untouched
forever and gate #3 is inert for anything unattended. Realised PnL has
to feed back in.

### B7 — Kill-switch coverage is incomplete

`kill_switches.SUPPORTED_SYMBOLS = ("EURUSD", "GBPUSD", "USDCAD",
"USDJPY", "USDCHF")` and `is_killed()` returns `False` for anything
else. A per-symbol kill on **XAGUSD** — the AN-3 candidate and a likely
first non-major on this account — silently does nothing. Only the global
flag would stop it. Also note the kill switch stops *new* orders and
does nothing about open ones (see B4).

### B8 — No aggregate exposure cap

R1 is per-trade, R4 is per-agent weight, R6 is per-symbol and only
evaluated on the `arm4` aggregator. Nothing bounds total open risk
across symbols and players. Seven proposers × 3–4 symbols × 0.1 lots can
exceed a $500 account several times over. A portfolio-level cap has to
be designed and inserted, and it is the rule that makes the "$500 →
$1000" experiment survivable.

## Design decisions the operator has to make (not implementation detail)

1. **Who clicks Execute.** Today: one human click per order, a 5-minute
   pending timeout and a 5-minute approved TTL. An H4 squad produces
   signals overnight, so most would expire unseen. Auto-executing means
   an internal caller of `POST /api/executor/execute/<id>` holding an
   install token in a background process — which removes the
   human-in-the-loop that D064's "shadow default + live opt-in with
   heavy friction" posture is built on. This is the crux of the sprint
   and it is a values decision, not a technical one.
2. **What "per player" means on one account.** `per_agent_equity` is
   currently a scoreboard no gate reads, and it increments *pips* onto a
   *dollar* baseline (dimensionally wrong, never exercised at n=0 closed
   trades). On a shared account, choose: notional attribution (each
   player credited a share of realised PnL, no risk meaning) or real
   sub-books with enforced per-player allocations. Only the second gives
   players independent risk budgets. Neither exists.
3. **Equity source of truth.** Static config number, or live
   `account_info()["balance"]`? A shared account's equity moves with
   every fill, so a static 500 drifts and R1's cap goes wrong in
   whichever direction the account moved. The "$500 → $1000" question
   specifically requires the live value.
4. **Restart and reconciliation semantics.** `state.json` tracks paper
   positions; the broker tracks real ones; nothing compares them. A
   crash mid-session leaves the broker holding positions the engine will
   never close, and a restart happily opens duplicates.
5. **Two accounts, one squad.** The bar feed logs into v1's account
   (`.env MT5_LOGIN`, read-only per I015) while the executor logs into
   `v2-demo` (keyring). Prices from one account, orders to another —
   acceptable for demo FX, but contract specs must be verified to match,
   especially XAGUSD, whose `pip_value_per_min_lot = 0.50` is a
   hardcoded assumption in `provenance_pips.py` rather than a broker
   read.

## Hard prerequisite that has nothing to do with code

Enabling `[live_executor]` **without** `[broker] terminal_path` +
`portable = true` on a single-terminal VM reproduces incident I015: the
platform's `mt5.initialize(login=…)` switches the machine-default
terminal's logged-in account, v1 sees a phantom drawdown, writes
`kill.txt`, and attempts emergency closes against the wrong account.
`docs/RUNBOOK_demo_launch.md` §7c.1 omits the pin from its checklist.
**Fix that checklist as the first commit of this sprint.**

## Also true, and worth saying plainly

G7 has no passing verdict. The latest firing (§11.18, 2026-07-15, third
attempt) was **FAIL 3/7** on phi41, and "No v2 arc authorised." Routing
squad proposals to a broker account — even a demo one — puts an ungated
system on a real order path. That is defensible on a demo account whose
entire purpose is to find the operational gaps that paper trading hides
(B4 through B8 are exactly those gaps), and it is the reason this
document exists rather than a refusal. But it should be entered as a
dated, ledgered decision with the G7 status stated in the same sentence,
not as an implied promotion.

## Recommended sequencing

1. Fix the §7c.1 terminal-pin omission (docs only).
2. B3 (R1-vs-fill mismatch) and B5 (magic number) — both small, both
   prerequisites for anything else being safe.
3. B4 (close path) and B7 (kill-switch symbol coverage).
4. B6 (realised PnL into the risk budget) and B8 (aggregate cap).
5. Decision 1 (who clicks Execute) and Decision 2 (per-player meaning),
   recorded in `company/ledger/decisions_log.md`.
6. B1 + B2 under fresh security and legal reviews.
7. First order, manually approved, single symbol, smallest lot, with the
   §7c.3 kill-switch drill run immediately after.

Until step 7, the correct answer to "can v2 start using the $500
account" is: **it runs $500 book semantics on paper today, and the real
order path is this sprint.**
