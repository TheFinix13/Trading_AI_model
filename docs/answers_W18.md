# Answers to the conceptual questions in your week-of-Apr-27 doc

You asked four big things in the document. Here's a structured take, plus what
we've already wired up and what's still pending.

---

## 1.  The "open ≈ close" days with two-sided wicks

You noticed Mon, Tue, Fri all opened and closed within a few pips of each
other while the day's *range* was 50–87 pips, with extended wicks on both
sides. You wrote: *"There's a pattern here, but I'm not able to fully grasp
it."*

### What it is

This is a **two-sided liquidity sweep day** — sometimes called a "Bart
Simpson" day on FX desks, or in ICT terms a *Daily-MMM (Market-Maker
Manipulation)* day. The institutional read is:

- Price runs **higher highs** to clear stops sitting above the previous-day
  high (or the prior week's high).
- Price then runs **lower lows** to clear stops sitting below the prior-day
  low or week's low.
- Both sweeps happen the **same day** because the market-maker has no
  directional bias for the session — they're harvesting both pools of
  resting liquidity, then closing the day flat near where it opened.

It's the daily-timeframe expression of the same logic you already use on
LTFs (the wick-into-zone-and-reverse). The "tell" is exactly what you
spotted: open ≈ close, range >> body, two long wicks.

### How to trade it (and how NOT to)

- **Avoid breakout trades** in either direction during the day. The probability
  that the breakout has gas behind it is low — the market is collecting both
  pools, not directional.
- **Fade extreme wicks** *only* with confirmation: wait for the candle that
  takes out a session high/low to close back inside the range AND a 1m/5m
  break-of-structure in the opposite direction. This is the same setup you
  used on Thursday at 1.16715, applied at the prior-day high/low.
- **Bigger picture**: a cluster of these in a row (you had 3 in 5 days)
  signals **range expansion is coming**. The pent-up directional energy
  resolves into the next 1-2 session swing. Thursday's explosive +86p range
  is exactly that release.

### What we've added in code

- `DayOHLC.open_close_clustered` (in `agent/llm/weekly.py`) — true when the
  body is ≤ 25% of the range. Already populated in your standardized weekly
  log; you can see the days flagged as
  *"open=close cluster days: 2026-04-27, 2026-04-28, 2026-05-01"*.
- The dashboard's weekly log page will show these days dimmed / tagged.
- **Action queued**: gate entries on T+1 of a cluster day (or require ≥3
  confluences). This is the single highest-leverage win from your week of
  observations.

---

## 2.  "How does today's range relate to yesterday's range?"

You asked this on Tuesday, then again on Friday. The framework you're
groping toward is the **previous-day-range / previous-week-range
framework** — basically: every new session, where price closed yesterday is
the *equilibrium*, and yesterday's high & low are the two liquidity
pools that today is most likely to attack first.

### Three rules of thumb

1. **PDH / PDL / PDM** (previous-day high / low / mid). Today's first
   meaningful move is almost always a sweep of one of these. Your Wednesday
   trade short to 1.16890 was textbook: D1 had been clamped between
   resistance and re-drawn support, and price ran the down-side of the range.
2. **Inside-day vs outside-day**. If today's high < PDH AND today's low > PDL
   (an inside day), it's continuation: tomorrow's expansion is more likely.
   If today's high > PDH AND low < PDL (outside day), today *was* the
   expansion — tomorrow is more likely consolidation.
3. **PWM / PWH / PWL** (week's mid / high / low) become the level of
   reference once you've crossed Wednesday. By Friday close, Friday is
   pricing where next week's directional bias starts.

### What we've added in code

- `agent/detectors/daily_levels.py` — labels every bar with PDH/PDL/PDM
  and PWH/PWL/PWM. **Already firing** in your replay diffs (look at
  `near_PWL` on Thursday, `near_PWM` on Friday).
- The `near_PDX` / `sweep_PDX` confluences carry the timeframe `D1` so
  your trade narrative shows e.g. *"sweep_PDH (D1)"*, not just *"sweep_PDH"*.
- These are now part of every Setup the engine produces. The next scorer
  training run will learn how predictive each daily-level confluence is.

### Open question I can't answer until we have more data

Whether the predictive power of "today is an open=close day" actually
*forecasts* tomorrow's expansion. We need >50 such days in the journal to
test that statistically. Three weeks of live ingest will get us there.

---

## 3.  "What's the most efficient way to enter Thursday's run?"

You scaled in: a small probe long from 1.16715 to confirm the structure
break, then a bigger long after the 38.2% retracement, with TPs ladder'd
at the 4HR resistance, 50% fib, 61.8% fib. All TPs hit but you wrote it was
"a scary trade" and you want a single-shot entry next time.

### My read

What you did was **textbook risk management**. The mistake people make is
the opposite — putting their full size in at the first hint of a structure
break. A scaled entry (probe + add) is *exactly* how funds enter directional
moves. Three thoughts:

1. **The "probe" is your hypothesis test.** You're not paying for it with
   risk; you're paying with opportunity cost. If the probe wins, you scale
   in with the structure now confirmed (and your stop tighter than it would
   have been pre-confirmation). If the probe loses, you lose 1R on a small
   size, not 1R on full.
2. **For one-go entries on the same setup**, the trigger is different. Wait
   for the **first pullback after the BOS** rather than the BOS itself.
   Thursday was unusual because the BOS itself was the breakout candle. On
   most days you get a 38.2% / 50% pullback after BOS — that's the cleaner
   one-shot.
3. **The "real" entry on Thursday was the 10am NY candle** that you missed.
   The way to catch that systematically is a **session-aware re-entry rule**:
   if I'm in profit on this setup AND we're 30 minutes before NY open AND
   the NY candle prints a continuation signal (engulfing, FVG, BOS), I
   re-enter rather than sit on the sidelines. We've added `agent/detectors/
   sessions.py` to label kill zones; the next thing is to add a *re-entry*
   policy in the rules engine.

### What we've added / will add

- `agent/detectors/sessions.py` — every bar carries an "Asia/London/NY/
  off-session" tag. The NY 9:30-11:00 ET window is now `session_ny_killzone`
  in your confluence list.
- **Pending**: a `ReentryPolicy` in `agent/rules/engine.py` that lets the
  agent re-enter on continuation when it has just taken a TP on the same
  direction within the last hour and we're entering a kill zone.
- Once that's in, the M15/H1 backtest over April-May will tell us whether
  the re-entry premium is real on EURUSD or just survivor bias.

---

## 4.  "Should we learn order flow?"

Yes — but not in the institutional-tape sense (that needs CME futures depth
data we don't get from a retail broker). What you want is the **derivative**
of order flow: **delta on each impulse leg**. On charts you see this as:

- **Body % of range per impulse candle** — a true breakout has the body
  sitting in the top 70% of the candle's range. A failed breakout has
  the body in the lower 30% (long upper wick).
- **Volume confirmation** — most retail charts give you tick volume, which
  is a proxy for order flow. A breakout with volume in the top decile of the
  last 20 bars is real; below median is suspect.
- **Multi-bar absorption / accumulation** — 3+ consecutive doji-like bars
  at a level == institutional accumulation, expect a directional move.
  3+ wide-body bars in the same direction == distribution / late-momentum.

This is the ICT *power-of-three* framework: each session has an
**accumulation** phase, a **manipulation** phase (the wick / sweep), and a
**distribution** phase (the directional run). You can label every bar with
its phase.

### What we've added in code

- `agent/detectors/range_phase.py` — every bar gets a phase tag
  `accumulation` / `manipulation` / `distribution` based on session,
  body-to-range ratio, and prior sweeps.
- It surfaced in 3 of your 5 trades' agent reads as `phase_distribution`.
  That's the agent saying: *"You entered during the distribution phase, the
  setup has gas behind it."*
- **Pending**: a real volume-derivative detector — body/range %, tick
  volume z-score, and consecutive-bar absorption pattern. We need to wire
  it into the scorer feature set.

---

## What you can already do in the dashboard right now

- `http://127.0.0.1:8000/`         — overall stats (open=close days will be
                                      tagged once you ingest more weeks)
- `http://127.0.0.1:8000/lessons`  — your 5 trades from this week, with the
                                      agent's diff next to each
- `http://127.0.0.1:8000/lesson/3` — example: your big Wednesday short with
                                      the agent's "AGREE" reasoning
- `http://127.0.0.1:8000/chat`     — talk to the agent. Ask it about
                                      "open=close days" or "what would you
                                      have done on Monday morning?".
                                      Now backed by `qwen2.5:7b-instruct`
                                      and `qwen2.5:14b-instruct` (both pulled).

The standardized markdown of your week is at
`tmp/weekly_log_2026_W18/standardized.md`. You can edit that file by hand
and re-feed it; the schema round-trips.

## Open questions I'd flag back to you

1. Is your "stop after one good trade" rule formalized as a daily P&L
   threshold (e.g. close for the day after +1R)? Worth encoding as a
   `daily_take_profit_pct` in `agent/config.py` — easy add.
2. On Thursday, the trade you missed was the 10am NY power-of-three
   candle. Were you watching for an NY-session re-entry signal, or
   something different?
3. For the scaled entries — would you prefer the agent to *journal both
   legs* (probe + add) as separate trades, or roll them into one position
   in the dashboard? Lots of UI implications.
