# F025 B1 — Proposal → approval bridge: design for review

- **Sprint:** sprint-4-squad-demo-execution (the new sprint D065
  requires; this document is the design its two reviews judge).
- **Status:** `DESIGN, NOT IMPLEMENTED` — 2026-08-19. No code in this
  document exists. It is written to be reviewed and rejected or
  amended, not to record something already built.
- **Parent charter:** `F025-squad-to-demo-account-bridge.md` §B1.
- **Blocks on:** security review + legal review (both below, both
  outstanding). D065 makes this non-negotiable.
- **Blocked by:** B7 recommended first — see §8.

## 1. Why this document exists before the code

D065 says any commit adding `approval_queue.submit(...)` on a live
pathway ships under a new sprint with fresh security and legal review.
That gate is easy to satisfy dishonestly: build it, then write two
reviews that describe what was built and approve it. A review of a
finished thing you already intend to ship is a formality.

So the design is written first, the reviews interrogate the design, and
implementation starts only after both sign off. If a review kills a
choice here, nothing has to be unpicked.

**Neither review below has been performed.** The sections are agendas,
not verdicts.

## 2. What B1 actually is

Today `approval_queue.submit()` has exactly one caller —
`serve_platform.py`, acting for a human who typed the trade. The squad
proposes continuously and nothing carries those proposals to the queue.
B1 is that carriage, and it is the last missing link between a squad
that thinks and an account that moves.

Everything downstream already exists: the four gates (F013 live-mode,
F011 kill, F012 risk budget, F013 approval), the executor (F018), the
close path (B4), the magic number (B5), the reconciler (B6), the
aggregate cap (B8), and the capital-derived ceiling (B2).

## 3. The field-mapping problem

`AgentProposal` and the queue's entry payload do not line up. Three
fields have to be *manufactured*, and manufacturing is where the risk
lives.

| Queue field | Source | Risk |
|---|---|---|
| `symbol` | `proposal.symbol` | Direct. |
| `entry` / `stop` | `proposal.entry` / `.stop` | Direct. |
| `side` | derived from `direction` | `direction` admits `"flat"`, which has no side. Must refuse, not guess. |
| `take_profit` | `proposal.ladder` | A ladder is N rungs; the queue field is scalar. Choosing one is a **strategy decision**. |
| `size` | decided | Not in the proposal at all. |
| `risk_snapshot.worst_case_loss` | computed | `sl_pips × lot × pip_value_per_lot_for(symbol)` — wrong pip table means a wrong risk number reaching a real gate. |
| `rationale` | `proposal.rationale` (dict) | Queue wants `str`. Lossy flatten. |
| `source_agent` | `proposal.agent_id` | Direct. |

### 3.1 `side`

```
long -> "buy"   short -> "sell"   flat -> REFUSE
```

`flat` is an intent to hold nothing. Mapping it to either side would
invent a trade nobody proposed. The bridge drops it and logs.

### 3.2 `take_profit` — the decision this design most wants challenged

The proposal carries a ladder; the queue carries one number. Options:

1. **Nearest rung.** Conservative, and systematically understates the
   plan's intent. The paper book and the broker book then diverge on
   every laddered trade, which is the same reconciliation failure B2
   was raised to prevent.
2. **Furthest rung.** Overstates. Turns partial-scaling plans into
   all-or-nothing.
3. **Fraction-weighted average.** Reconciles in expectation, matches no
   actual rung, and is a price the strategy never chose.
4. **Refuse to bridge multi-rung proposals; single-rung only.**

**Recommendation: (4) for the first cut.** It ships the narrowest
honest thing. A multi-rung plan collapsed to a scalar is not the plan
the agent proposed, and the account cannot be reconciled against a
leaderboard built on a different exit. Single-rung proposals are a real
and sufficient population to start. If (4) starves the bridge of
volume, that is data worth having before choosing among 1–3.

### 3.3 `size`

`risk_budget_lot()` (B3), capped by the capital-derived ceiling (B2).
With `--player-lot-intent`, the striker's `lot_intent()` supplies the
desired lot and the budget still caps it. **No path lets a player set
the final size.**

### 3.4 `worst_case_loss`

`sl_pips × lot × pip_value_per_lot_for(symbol)`, using the symbol-aware
pip tables from the I030 fix. This number feeds the risk budget and the
B8 aggregate cap, so an error here is not cosmetic — it silently
mis-states the gate. **Must fail closed:** an unknown symbol yields no
number and the bridge refuses, rather than substituting a major's pip
value. I030 is the precedent — a hardcoded `PIP_SIZE=0.0001` censored
100% of 14,621 USDJPY winners.

## 4. Dedup: key on setup identity

The squad re-proposes the same setup on every poll tick. Submitting per
instance would bury the operator and, with auto-execution armed, fire
repeatedly on one idea.

**Setup key:** `(symbol, side, round(entry, tick), round(stop, tick),
source_agent)`. Deliberately excludes timestamp, tick_id and
conviction — those change on re-detection while the *setup* does not.

- Key already `pending` → update the existing card in place, do not
  enqueue.
- Key `rejected` within the suppression window → do not resubmit. An
  operator who said no should not be asked again about the same idea
  minutes later.
- Key `approved` / `auto_approved` / executed → do not resubmit;
  position management is not this path's job.

## 5. Delivery failure: drop and log

If submission fails, **drop it and log loudly.** No retry. A setup that
reaches the operator late is worse than one that never arrives: the
price has moved, the countdown starts against a stale premise, and with
auto-execution armed a retry could fire an order the operator never had
a fair chance to refuse.

Drops surface non-modally ("3 setups expired unsent") with a
plain-language reason, so the system is never silently deciding.

## 6. Security review agenda — OUTSTANDING

To be exercised against the implementation, not this document.

1. **New writer to a security-critical queue.** `submit()` gains a
   non-human caller for the first time. Does the internal-token gate on
   `POST /api/approvals/submit` still hold? Can the bridge's credential
   reach a user-facing endpoint?
2. **Can the bridge forge attribution?** `source_agent` becomes
   machine-set. Audit rows must remain trustworthy.
3. **Does the P0 live-mode-off invariant still pass** with a live
   submitter present? A clean install must still send nothing.
4. **Rate / volume bound.** What stops a proposal storm from filling
   the queue? Dedup is a correctness mechanism, not a security bound.
5. **Does dedup leak across operators or sessions?**
6. **Failure-path side effects.** Confirm a dropped submission has zero
   market effect and cannot half-write queue state.
7. **Interaction with auto-execution.** With `auto_execute_on_timeout`
   armed, submission plus silence equals an order. That is a
   qualitatively different threat surface from every prior sprint and
   deserves its own pass.

## 7. Legal review agenda — OUTSTANDING

1. **Inaction-inversion, now reachable.** The right-of-first-refusal
   semantics are built but inert because nothing submits. B1 is what
   makes them real. `approval-queue-warning.md` was already rewritten;
   Legal must confirm it is accurate once the path is live.
2. **"No order without a human click" is retired.** Every surviving
   instance of that claim must be found and corrected. It is false when
   auto-execution is armed.
3. **Demo-only structural guard** must remain unreachable-by-
   construction, not policy-forbidden.
4. **Claim register** entries for every new accessor.
5. **`worst_case_loss` is an operator-facing risk claim.** If it can be
   wrong for any symbol, the disclaimer must say so.
6. **B2's outstanding ask.** The charter asked for the raised ceiling to
   be ratified under this sprint's legal review. The mechanism shipped
   (capital-derived, tighten-only); ratification is still owed.
7. **Ladder truncation** (§3.2) if anything other than option 4 is
   chosen: the operator is shown one take-profit while the strategy
   intended several.

## 8. Recommended order

**B7 before B1.** B7 is unblocked and needs no review; B1 is the first
thing that lets a proposal reach a broker. Shipping the bridge while
halt coverage has gaps means the first time you need to stop everything
is the first time you find out what the kill switch does not cover.

*(B7's fail-open hole was closed 2026-08-19 — every kill flag on disk is
now honoured. Its residual gap, out of scope: a kill stops new orders
and does not flatten open ones. Halting is not flattening.)*

## 9. Open questions for the operator

1. §3.2 — single-rung-only, or one of the collapse rules?
2. Rejection suppression window — how long before the same setup may be
   offered again?
3. Should the bridge run with `auto_execute_on_timeout` OFF for a
   settling period, so the first live proposals require a real click?
