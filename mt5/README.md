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
