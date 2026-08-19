This folder holds the two MQL5 artifacts the agents need from inside the
terminal: a chart overlay EA (`TradingPartner_Overlay.mq5`) and a
one-shot calendar exporter (`ExportCalendarHistory.mq5`).

---

# Calendar history export — unblocking the surprise panel

`ExportCalendarHistory.mq5` dumps MetaQuotes' economic-calendar history
(actual / forecast / previous per event) to CSV. The research lane's
surprise panel — the study that decides whether Aoshi's event weapon can
be made content-conditional instead of firing on every release — has
been blocked on this one export since 2026-08-04. It is a manual run
because MT5 exposes `CalendarValueHistory` only to code running inside
the terminal.

## Which terminal to run it in

**Run it in terminal A — v1's long-running terminal, not the v2 portable
one.** The calendar database is per-terminal and only populates while a
terminal is online with the Calendar tab opened at least once. Terminal A
has been online for months; the v2 portable terminal is fresh, which is
almost certainly why the first attempt (commit `f0a9062`) returned zero
rows. Reading the calendar does not place orders and does not disturb
v1's positions.

## Steps

1. **Populate the calendar DB first.** In MT5: `View → Toolbox` (Ctrl+T),
   click the **Calendar** tab, and leave it open for about a minute while
   it downloads. If the tab is empty, check
   `Tools → Options → Server → Enable news` is ticked, then stay online.
   Skipping this step is the failure mode — the script will print
   `Calendar DB looks EMPTY/disabled` and write a header-only CSV.

2. **Install the script.** `File → Open Data Folder`, then
   `MQL5\Scripts\` — **Scripts, not Experts.** This file is a script
   (`#property script_show_inputs`), so it will not appear under Expert
   Advisors in the Navigator.

3. **Compile.** Press F4 for MetaEditor, open
   `ExportCalendarHistory.mq5`, press F7. Expect zero errors.

4. **Run it.** In MT5's Navigator, expand **Scripts**, double-click
   `ExportCalendarHistory` on any open chart. An inputs dialog appears
   (defaults: USD, from 2015-01-01) — click OK.

5. **Read the Experts tab, not the chart.** `View → Toolbox → Experts`.
   Four lines matter, and they are the whole diagnosis:

   ```
   calendar probe (all currencies, last 30 days): ok=true n=<N> err=0
   raw USD values returned: <N>  (from 2015.01.01)
   importance split: high=<N> moderate=<N> low=<N> none=<N>
   wrote <N> high-impact USD rows to MQL5/Files/calendar_history_usd.csv
   ```

   A probe `n=0` means step 1 did not take — go back and sync the
   Calendar tab. A healthy 2015-onward pull should write a few thousand
   high-importance USD rows.

6. **Retrieve the CSV.** `File → Open Data Folder`, then
   `MQL5\Files\calendar_history_usd.csv`. Copy it out of the VM and
   report the four Experts lines above; the exact counts determine
   whether the panel has enough history to be worth running.

## Why the export is worth the manual step

The squad's live calendar feed tells it *when* news happens, never *what
it said*. Every event therefore looks identical to the agents, which is
the structural reason Aoshi trades all 349 NFP/CPI/FOMC releases at a
28.7 % win rate: most releases land near consensus and are noise, and he
cannot tell those from the minority that actually surprise. This CSV is
the only path to testing that distinction on history.

---

# MT5 Chart Overlay — AI Trading Partner

This EA visualizes the AI agent's analysis directly on your MT5 chart.

## Installation

1. Copy `TradingPartner_Overlay.mq5` to your MT5 data folder:
   - In MT5, go to File → Open Data Folder → MQL5 → Experts
   - Paste the file there

2. Compile the EA:
   - Open MetaEditor (F4 in MT5)
   - Open the file and press Compile (F7)

3. Attach to chart:
   - In MT5, open a EURUSD chart (any timeframe)
   - Drag "TradingPartner_Overlay" from Navigator → Expert Advisors onto the chart
   - Enable "Allow Algo Trading" in the toolbar
   - In EA settings, all toggles should be ON by default

4. The EA will automatically read the agent's analysis and draw:
   - Purple rectangles: LZI (Liquidity) zones
   - Blue rectangles: FVG zones
   - Orange rectangles: Supply/Demand zones
   - Red lines: Resistance levels
   - Green lines: Support levels
   - Gold dotted lines: Fibonacci levels
   - Arrows: Entry signals (green=buy, red=sell)
   - Top-left label: Current HTF bias and confidence

## Customization

In the EA settings (right-click chart → Expert Advisors → Properties):
- Toggle individual elements on/off (zones, levels, fibs, bias, signals)
- Change colors for each element type
- Adjust update interval (default: 5 seconds)

## How It Works

The Python agent writes its analysis to `MQL5/Files/agent_drawings.json`.
The EA reads this file every 5 seconds and redraws all objects.
When the agent is stopped, the EA shows the last known state.
Removing the EA clears all AI drawings from the chart.
