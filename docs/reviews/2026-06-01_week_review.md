# Week Review — 2026-06-01 → 2026-06-05 (context from 2026-05-28)

> A post-mortem of a discretionary EURUSD week on the Exness demo
> (account `10000189685`, 1:1000 leverage), mapped trade-by-trade onto the
> capabilities this agent already has. Source data: the broker statement PDF
> (period 2026 Apr 30 – Jun 08) and five TradingView screenshots (D1 / H4 / D1
> wide). Module references point at real code so each lesson is actionable, not
> generic. Start at [00 — Overview](../00-overview.md) for the system itself.

---

## Headline

| Metric | Value |
|--------|-------|
| **Net closed P/L (week incl. May 28)** | **−$50.60** |
| Filled trades | 11 (4 win / 1 breakeven / 6 loss) |
| Win rate | 36% (40% excl. breakeven) |
| Gross win / gross loss | +$163.20 / −$213.80 |
| Profit factor | **0.76** |
| Account trajectory | ~$108 → blown to ~$0 (Jun 2) → re-deposited $72 → blown to ~$0 (Jun 5) |
| Single most costly trade | Jun 2, **1.0 lot, −$124.00** broker margin **Stop Out** |
| Trades with a stop set | **1 of 11** (Jun 4 — and it won) |

The two largest losses (−$124.00 and −$58.20 = −$182.20) are **85% of all
losses**. Both were **oversized, counter-trend BUYS with no stop**. Remove just
those two trades and the week is **+$131.60**. Everything else is noise around a
single behavioural failure repeated twice.

---

## 1. What the statement actually shows (and what the user left out)

The trades the user pasted were the *flattering* subset. The broker statement
tells the full story — the account was **blown to zero twice** and refunded once.
The broker aggregates same-direction scale-ins that share an open price into one
row, which is why "three May 28 buys" appear as a single 0.8-lot line.

| # | Date / time (server) | Side | Lot | Open | Close | Pips | P/L | SL set? | Read |
|---|---|---|---|---|---|---|---|---|---|
| — | May 28 12:38 | buy stop | 1.0 | 1.16350 | — | — | **cancelled** | — | order pulled |
| 1 | May 28 12:40 → 14:27 | BUY | 0.8 | 1.16339 | 1.16535 | +19.6 | **+131.40** | no | scaled 0.1+0.1+0.6, let to run — the one good trade |
| 2 | Jun 1 16:55 → 20:10 | BUY | 0.8 | 1.16306 | 1.16312 | +0.6 | **+14.20** | no | premature; captured a sliver of the move |
| 3 | **Jun 2 06:31 → 10:21** | BUY | **1.0** | 1.16505 | 1.16381 | −12.4 | **−124.00** | **no — margin Stop Out** | oversized, naked, bought into a falling 4H |
| 4 | Jun 2 20:05 → 20:34 | BUY | 0.4 | 1.16346 | 1.16310 | −3.6 | −14.40 | no | revenge re-entry after re-deposit |
| 5 | Jun 2 22:17 → 23:15 | SELL | 0.2 | 1.16270 | 1.16255 | +1.6 | +3.20 | no | scratch |
| 6 | Jun 2 23:20 → 23:35 | SELL | 0.3 | 1.16235 | 1.16235 | 0 | 0.00 | no | breakeven scratch |
| 7 | Jun 2 23:37 → 23:58 | SELL | 0.3 | 1.16202 | 1.16223 | −2.1 | −6.30 | no | over-trading the Asia chop |
| 8 | Jun 3 01:35 → 01:55 | BUY | 0.2 | 1.16316 | 1.16299 | −1.7 | −3.40 | no | 20-min flip, no thesis |
| 9 | Jun 3 06:42 → 07:50 | SELL | 0.1 | 1.16140 | 1.16215 | −7.5 | −7.50 | no | sold the low, stopped into the bounce |
| 10 | **Jun 4 15:13 → 18:33** | SELL | 0.2 | 1.16236 | 1.16164 | +7.2 | **+14.40** | **yes (1.16160)** | the only disciplined trade — with-trend short, **had a stop, won** |
| 11 | **Jun 5 10:31 → 12:30** | BUY | 0.3 | 1.16441 | 1.16247 | −19.4 | **−58.20** | no | bought the **double top**, rode it into demand |

Cash flow around it: +$108.26 deposit (May 28), −$130.00 withdrawal (May 28),
−$124.00 stop-out + $0.14 compensation (Jun 2), **+$72.19 re-deposit (Jun 2
19:14)** to keep trading after the blow-up, and a final $0.01 dust on Jun 5 when
equity hit zero again. **Net deposit $50.60, closed P/L −$50.60, ending equity
$0.**

> The hidden middle of the week (trades 4–9) is the tell. After the Jun 2
> stop-out wiped the account, the user re-funded it and fired **six trades in ~24
> hours**, flipping long/short with no structure. That is the revenge-trading
> signature, and the statement makes it undeniable.

---

## 2. Day-by-day timeline

### May 28 (Thu) — the template for *good* behaviour
Price was holding above the daily demand zone (~1.1605–1.1635 on the D1 chart)
and pushed up off it. The user bought 1.16339 in three clips and **let the runner
go to 1.16535** (+19.6 pips), banking +$131.40. This is the only time all week
the user (a) traded with the structure off a zone and (b) let a winner extend. A
1.0-lot buy *stop* above (1.16350) was placed and cancelled — the only flicker of
a plan.

### Jun 1 (Mon) — premature exit
Bought the same demand area (1.16306) at size 0.8 but bailed at 1.16312 — **+0.6
pips on the 0.6-lot clip**. The thesis was fine; the exit gave back essentially
the entire intended move. This is the "I close before it bounces back" pattern in
the user's own words.

### Jun 2 (Tue) — the account-killer, then revenge
The H4 had been carving **lower highs into a descending trendline** (see the H4
screenshot) and price was rolling over from the 50–78.6% fib band. The user bought
**1.0 lot at 1.16505 with no stop**, into that falling structure. Price dropped
12.4 pips to 1.16381 and the broker issued a **margin Stop Out** at −$124.00,
taking equity to ~$0. The user **re-deposited $72.19** and immediately traded
again — a 0.4-lot buy (−$14.40), then three quick sells (+3.20 / 0 / −6.30) in the
Asia session. Net Jun 2: **−$141.50**.

### Jun 3 (Wed) — over-trading the chop
Two small, directionless trades (a 20-minute 0.2-lot buy −$3.40; a 0.1-lot sell
that sold the low and got run over for −$7.50). No structural reason for either —
boredom / tilt residue.

### Jun 4 (Thu) — the one trade done right
A **0.2-lot SELL at 1.16236 with a stop at 1.16160**, held ~3 hours to 1.16164 for
+$14.40. With-trend (short into the prevailing H4 down-move), correctly sized,
**stop defined in advance**. This is the entire system in one trade — and it won.

### Jun 5 (Fri) — the double-top trap, account gone again
Price rallied to the marked overhead zone (~1.1644) and printed a **double top**:
two pushes at the same high, buy-side liquidity swept, no hold. Instead of the
"upward liquidity grab" the user was waiting for, price **rejected, broke 1H
support and the daily pullback line, and dropped into the demand zone**. The user
**bought the second top at 1.16441 with no stop** and rode it down 19.4 pips to
1.16247: **−$58.20**, equity back to ~$0.

---

## 3. The Friday double-top failure — why it was readable

The user's bias was "wait for price to take liquidity **upward** from the marked
boxes." On a market making **lower highs under a descending trendline**, that is
backwards. Here is the order-flow read:

- The overhead boxes are **supply**, not a launchpad. The equal highs sitting
  under them are **buy-side liquidity** — fuel that smart money runs *to fill
  shorts*, not a level price expands up through.
- The poke above the highs is the **manipulation** leg (ICT Power of Three). The
  **distribution** leg that follows is the real move — and in a bearish structure
  it goes **down**.
- A **double top is a `failed_breakout_high`**: two attempts sweep the liquidity
  above the level, neither holds, the second failure is the high-conviction
  reversal. Our HTF layer encodes exactly this.

This agent's `agent/context/htf_context.py` would have flagged it directly.
`HTFAnalyzer._detect_failed_breakouts()` looks for two swing highs within ~10 pips
that fail to hold, and emits:

```68:70:docs/04-reaction-engine.md
│ Conviction: 0.74 ✓ (threshold 0.58) | dir SELL | agreement 1.00
│ Level: at PDL
│ ✅ reaction fired
```

```319:332:agent/context/htf_context.py
                        patterns.append(PatternSignal(
                            pattern_type=PatternType.FAILED_BREAKOUT_HIGH,
                            timeframe="H4",
                            confidence=min(0.9, 0.5 + valley_depth / (100 * 0.0001)),
                            implied_direction=MarketBias.BEARISH,
                            key_level=level,
                            invalidation=level + 20 * 0.0001,
                            description=(
                                f"Failed breakout at {level:.5f} (double top mechanics). "
                                f"Two attempts swept liquidity above but couldn't hold. "
                                f"Expect reversal toward demand below."
                            ),
                        ))
```

A `FAILED_BREAKOUT_HIGH` sets `implied_direction = BEARISH`, which flips
`sell_aligned = True` in `HTFContext`. Combined with a D1/H4 bias that was already
bearish (lower highs), **both the bias and the pattern pointed SHORT**. The user
took the only long the structure forbade.

> "Waiting for liquidity upward" was a *thesis*, and the market **invalidated it
> in real time** when the second top failed and price broke support. The mistake
> was not the original idea — it was refusing to abandon it once price committed
> the other way.

---

## 4. Trade-by-trade mistake classification

| # | Date | Mistake type(s) | Quantified harm |
|---|---|---|---|
| 1 | May 28 | *(none — the model trade)* | +$131.40; let runner go |
| 2 | Jun 1 | **premature exit** | captured +0.6 pips of a multi-pip move |
| 3 | Jun 2 | **oversizing + no stop + counter-trend** | **−$124, ~100% of account; margin stop-out** |
| 4 | Jun 2 | **revenge entry** (post-blow-up) | −$14.40 |
| 5 | Jun 2 | over-trading | +$3.20 (scratch) |
| 6 | Jun 2 | over-trading | $0 |
| 7 | Jun 2 | over-trading / chasing | −$6.30 |
| 8 | Jun 3 | chasing, no thesis | −$3.40 |
| 9 | Jun 3 | counter-move, no stop | −$7.50 |
| 10 | Jun 4 | *(none — disciplined)* | +$14.40; **had a stop** |
| 11 | Jun 5 | **counter-trend + no stop + oversizing-for-context** | **−$58.20, ~100% of remaining account** |

**Why every meaningful trade risked ~100% of the account.** With no stop, the
"risk" is whatever the broker tolerates before a margin call. On 1:1000 leverage
the margin for 1.0 lot is `100,000 × 1.16505 / 1000 = $116.50` — about **94% of a
~$124 balance committed as margin with zero buffer**, so a 12-pip adverse move was
a full-account stop-out. The Jun 5 0.3-lot (−$58.20) wiped ~100% of the ~$58
balance it had left. Even the *winners* (May 28 and Jun 1, 0.8 lot on ~$110) were
full-account-risk bets — they simply went the right way. **The wins were direction
luck, not risk control.**

R-multiples can't be computed honestly because there were no stops (no defined
1R). That absence *is* the finding.

---

## 5. Root-cause themes

1. **Position-sizing chaos.** Lots ran 0.1 → 0.6 → 0.8 → **1.0** → 0.4 → 0.2 →
   0.3 with no link to conviction or stop distance. The **biggest size (1.0) sat
   on the worst entry** (buying into a falling H4 after a liquidity sweep).
2. **No risk management.** `S/L` and `T/P` were **empty on 10 of 11 trades**. The
   Jun 2 loss was a *broker* Stop Out, not a planned exit. The single trade with a
   stop (Jun 4) is the single clean win.
3. **Revenge trading.** A margin wipe → instant re-deposit → six trades in ~24h,
   flipping direction with no structure.
4. **Premature profit-taking.** May 28 and Jun 1 closed for slivers ("I close
   before it bounces back").
5. **Directional-bias bias.** Only hunted **longs / upward liquidity** all week in
   a **bearish-structured** market. The one short that respected the structure
   (Jun 4) was the only process-correct trade — and it paid.

---

## 6. Mapping each mistake to the agent's existing capabilities

| Mistake | Agent capability that prevents it | Code |
|---|---|---|
| 1.0-lot stop-out on a ~$100 account | **Adaptive position sizer** caps risk in a 0.5–2% band by conviction; rounds *down* to lot step; never exceeds free margin. On $100 with a 20-pip stop it sizes ~0.005 → snaps to 0.01 min lot — **100× smaller than 1.0 lot**. The −$124 becomes ~−$1.24. | `agent/live/position_sizer.py` (`PositionSizer.calculate_lot`, `risk_pct_for_conviction`) |
| Naked positions / margin stop-outs | **Mandatory structural SL + PD-array TP on every order**; setups failing `min_rr` are rejected; **3% daily drawdown halt**; one position at a time. There is no code path that opens a position without a stop. | `agent/risk/manager.py`, `agent/reaction/engine.py` (stop/target), `docs/05-position-sizing-and-risk.md` §05.2 |
| Buying the Friday double top | **HTF pattern mechanics** emit `FAILED_BREAKOUT_HIGH → BEARISH`, flipping `sell_aligned` and biasing short; counter-trend longs get a conviction penalty (or are rejected in `strict` `htf_bias_mode`). | `agent/context/htf_context.py` (`_detect_failed_breakouts`), `agent/rules/engine.py` (`htf_bias_mode`) |
| Anchoring to "upward liquidity" after price committed down | **Anticipation→reaction flip**: when a strong opposing reaction clears `flip_min_conviction`, the agent abandons the anticipated long and engages the reaction engine in the dominant (down) direction toward the next liquidity level. | `SignalLoop._decide_action` (flip), `agent/reaction/` (`engine.py`, `components.py`) |
| Premature exits | **Breakeven-at-1R + PD-array targeting**: stop trails to entry at 1R and the position runs to the next unswept liquidity level instead of a discretionary panic-close. The **counterfactual** then logs "gave back N R — consider trailing/partial." | `docs/05-position-sizing-and-risk.md` §05.2, `agent/journal/live_journal.py` (MAE/MFE counterfactual) |
| The revenge trade itself | **Learning journal attribution** classifies a low-conviction loss as **`bad_setup`** ("shouldn't have fired"); the **calibration check** prints `⚠️ MISCALIBRATED` when size/conviction don't track outcomes — which is exactly what a 1.0-lot tilt entry looks like. | `agent/journal/live_journal.py` (attribution, calibration), `agent/journal/performance_memory.py` |
| Sitting out the move while "waiting" | **Declined-setups detector** logs every detected-but-skipped signal and, in backtest, scores whether it *would have won* — the over-strict-filter alarm. The backtest showed **~32% of declined setups would have won**, i.e. the "wait forever" bias is measurable and tunable. | `agent/journal/live_journal.py` + learning backtest, `docs/06-learning-journal.md` §06.4 |

The one thing the agent **does not** have today: an explicit **post-loss
cooldown / no-revenge guard** (confirmed — no `cooldown` / `revenge` /
`consecutive_loss` logic exists in the codebase). That is the top recommendation
below.

---

## 7. Recommendations (prioritized — not yet implemented)

1. **Post-loss cooldown + size-reduction guard (NEW — highest impact).** After
   any loss, enforce a minimum cooldown (N bars or minutes) before a new entry;
   **halve `risk_pct` until the next win**; block same-direction re-entry into the
   same level; and after a *stop-out specifically*, halt new trades for the rest of
   the session. Add a re-deposit guard so refunding a blown account does not reset
   the risk state. This directly kills the Jun 2 evening cluster and the Jun 5
   re-attempt. Natural home: `agent/risk/manager.py` + `config/default.yaml`.

2. **Make "every order has SL+TP" a hard pre-trade invariant.** The agent already
   sets them; add an explicit assertion in the execution path that *rejects* any
   order missing a structural stop or a target below `min_rr`. Cheap, and it makes
   a naked Jun-2-style position structurally impossible.

3. **Calibrate the reaction engine against this week.** Tune
   `conviction_threshold` / `flip_min_conviction` so the **Jun 5 down-commitment**
   (displacement + range expansion through 1H support) clears the bar and fires
   SHORT, and so the **Jun 4 with-trend short** profile is reinforced. Use the
   learning backtest over May 28–Jun 5 as the calibration set.

4. **Loosen the over-strict anticipation gates.** With **~32% of declined setups
   would-have-won**, the anticipation stack is leaving money on the table — the
   same "wait for the perfect upward grab" trap the user fell into. Relax the gate
   stack toward the reaction path (or lower the conviction floor) and re-measure
   declined-would-have-won until it drops.

5. **Add a directional-bias sanity check to the daily roll-up.** Surface a warning
   when realised trades cluster on one side while HTF bias points the other way
   (the user was net-long a bearish week). This is a journal/calibration addition,
   not a new gate.

> Priority order by expected P&L impact on *this* week: (1) and (2) alone convert
> −$50.60 into roughly **+$130** by removing the two account-killers; (3)–(5) are
> the edge-recovery layer that stops the slow bleed and the missed shorts.

---

## 8. One-paragraph verdict

The week was not lost to bad analysis — the user's zone and liquidity reads were
mostly reasonable, and the demand-zone touch they called played out. It was lost
to **risk behaviour**: no stops, sizing untethered from conviction, and an
inability to abandon a long thesis once price committed down. The agent's existing
sizer, mandatory-SL/TP discipline, HTF `failed_breakout_high` detection and
anticipation→reaction flip would have turned the two −$124 / −$58 disasters into
~−$1 paper-cuts and likely caught the Friday short. The **only missing piece** is a
post-loss cooldown to stop the human reflex the statement exposes: re-funding a
blown account and trading angrier. Build that, calibrate the reaction thresholds
on this week, and the same five days are green.
