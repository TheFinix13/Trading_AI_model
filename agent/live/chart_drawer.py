"""
MT5 Chart Drawing Bridge

Writes drawing instructions as JSON to MT5's shared file directory.
The MQL5 EA (TradingPartner_Overlay.mq5) reads these and renders on chart.
"""
import json
import os
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict

logger = logging.getLogger(__name__)


class ChartDrawer:
    """Writes agent analysis as JSON for the MT5 EA to visualize."""

    def __init__(self, mt5_data_path: Optional[str] = None):
        """
        mt5_data_path: Path to MT5's MQL5/Files directory.
        On Windows: C:/Users/<user>/AppData/Roaming/MetaQuotes/Terminal/<hash>/MQL5/Files/
        """
        if mt5_data_path:
            self.output_dir = Path(mt5_data_path)
        else:
            self.output_dir = self._find_mt5_files_dir()

        self.output_file = self.output_dir / "agent_drawings.json" if self.output_dir else None

        if self.output_file:
            logger.info(f"Chart drawer initialized: {self.output_file}")
        else:
            logger.warning("MT5 Files directory not found. Chart drawings disabled.")

    def _find_mt5_files_dir(self) -> Optional[Path]:
        """Auto-detect MT5 terminal data directory on Windows."""
        if os.name != 'nt':
            return None

        appdata = os.environ.get('APPDATA', '')
        if not appdata:
            return None

        mq_path = Path(appdata) / "MetaQuotes" / "Terminal"
        if not mq_path.exists():
            return None

        for terminal_dir in mq_path.iterdir():
            if terminal_dir.is_dir() and len(terminal_dir.name) == 32:
                files_dir = terminal_dir / "MQL5" / "Files"
                if files_dir.exists():
                    return files_dir

        return None

    @property
    def enabled(self) -> bool:
        return self.output_file is not None

    def update(self, zones: List[Dict], levels: List[Dict], fibs: List[Dict],
               bias: Dict, signals: List[Dict]):
        """
        Write the complete drawing state to the JSON file.
        The EA will read this and redraw everything.
        """
        if not self.enabled:
            return

        payload = {
            "timestamp": self._now_iso(),
            "zones": zones,
            "levels": levels,
            "fibs": fibs,
            "bias": bias,
            "signals": signals,
        }

        try:
            with open(self.output_file, 'w') as f:
                json.dump(payload, f, indent=2)
            logger.debug(
                f"Chart drawings updated: {len(zones)} zones, "
                f"{len(levels)} levels, {len(signals)} signals"
            )
        except Exception as e:
            logger.error(f"Failed to write chart drawings: {e}")

    def update_from_context(self, htf_context, lzi_zones=None, fvg_zones=None,
                            sd_zones=None, active_signals=None):
        """
        Convenience method that takes agent internal objects and converts
        to drawing format.
        """
        zones: List[Dict] = []
        levels: List[Dict] = []
        fibs: List[Dict] = []
        signals: List[Dict] = []

        if lzi_zones:
            for i, zone in enumerate(lzi_zones):
                zones.append({
                    "type": "LZI",
                    "high": getattr(zone, 'high', getattr(zone, 'zone_high', 0)),
                    "low": getattr(zone, 'low', getattr(zone, 'zone_low', 0)),
                    "quality": getattr(zone, 'quality', 'B'),
                    "status": getattr(zone, 'status', 'ACTIVE'),
                    "label": f"LZI Zone {chr(65 + i)}",
                })

        if fvg_zones:
            for i, fvg in enumerate(fvg_zones):
                zones.append({
                    "type": "FVG",
                    "high": getattr(fvg, 'high', 0),
                    "low": getattr(fvg, 'low', 0),
                    "quality": getattr(fvg, 'quality', 'B'),
                    "status": "ACTIVE",
                    "label": f"FVG {chr(65 + i)}",
                })

        if sd_zones:
            for i, sd in enumerate(sd_zones):
                zones.append({
                    "type": "SD",
                    "high": getattr(sd, 'high', getattr(sd, 'upper', 0)),
                    "low": getattr(sd, 'low', getattr(sd, 'lower', 0)),
                    "quality": getattr(sd, 'quality', 'B'),
                    "status": getattr(sd, 'status', 'ACTIVE'),
                    "label": f"SD Zone {chr(65 + i)}",
                })

        if htf_context and hasattr(htf_context, 'structural_levels'):
            for level in htf_context.structural_levels[:10]:
                levels.append({
                    "price": level.price,
                    "type": level.level_type,
                    "timeframe": level.timeframe,
                    "label": (
                        f"{level.level_type.title()} "
                        f"({level.timeframe}, strength {level.strength})"
                    ),
                })

        if htf_context and hasattr(htf_context, 'htf_fib_levels'):
            for price, label in htf_context.htf_fib_levels:
                fibs.append({
                    "price": price,
                    "label": label,
                })

        bias: Dict = {}
        if htf_context:
            bias = {
                "direction": (
                    htf_context.combined_bias.value.upper()
                    if hasattr(htf_context.combined_bias, 'value')
                    else str(htf_context.combined_bias)
                ),
                "confidence": (
                    f"{htf_context.bias_confidence:.0%}"
                    if hasattr(htf_context, 'bias_confidence')
                    else "N/A"
                ),
                "patterns_summary": (
                    "; ".join(
                        p.description[:60]
                        for p in (htf_context.active_patterns or [])[:3]
                    )
                    if hasattr(htf_context, 'active_patterns')
                    else ""
                ),
            }

        if active_signals:
            for sig in active_signals:
                signals.append({
                    "direction": getattr(sig, 'direction', 'BUY'),
                    "entry": getattr(sig, 'entry_price', 0),
                    "sl": getattr(sig, 'stop_loss', 0),
                    "tp": getattr(sig, 'take_profit', 0),
                    "strategy": getattr(sig, 'strategy', 'Unknown'),
                    "time": self._now_iso(),
                })

        self.update(zones, levels, fibs, bias, signals)

    def clear(self):
        """Clear all drawings (write empty state)."""
        if not self.enabled:
            return
        self.update([], [], [], {}, [])

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()
