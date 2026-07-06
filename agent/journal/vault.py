"""Near-miss and loss vaults — observation-only JSONL + chart snapshots.

Two append-only evidence stores under the per-symbol live log folder
(``~/Documents/TradingAgentLogs/{SYMBOL}/``):

* ``near_misses/events.jsonl`` — trades the agent ALMOST took: zone touches
  rejected only by the HTF alignment gate (alpha-level, via the optional
  ``near_miss_hook`` on :class:`SupplyDemandAlpha`) and alpha signals dropped
  downstream by the post-loss guard / risk manager / sizing skip
  (loop-level, via :class:`SignalLoop`).
* ``losses/events.jsonl`` — live positions that closed at a loss, with the
  trade's lifetime rendered on the chart.
* ``ladders/events.jsonl`` — extension-target ladders: the structural levels
  beyond each live trade's mechanical TP (published at entry, scored against
  realised MFE at close). See :mod:`agent.journal.target_ladder`.

Each event appends ONE JSON line and renders a PNG snapshot beside it.

Hard contract: this module is pure logging. Every public method swallows its
own exceptions (warning log only), so a full disk, a bad event dict or a
matplotlib failure can never affect trading behaviour. The hypothetical
outcomes are scored later by ``scripts/resolve_near_misses.py`` — they are
hypothesis-generating evidence only, never a reason to bypass the validation
pipeline.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

from agent.journal.chart_snapshot import render_snapshot
from agent.types import Bar

log = logging.getLogger(__name__)

DEFAULT_VAULT_ROOT = Path.home() / "Documents" / "TradingAgentLogs"

# A hook receives (event dict, bars at decision time). Matches
# SupplyDemandAlpha.near_miss_hook.
AlphaNearMissHook = Callable[[dict, Sequence[Bar]], None]


def _parse_ts(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _png_name(ts: datetime | None, tag: str) -> str:
    stamp = (ts or datetime.now(tz=timezone.utc)).strftime("%Y-%m-%d_%H%M")
    safe_tag = "".join(c if (c.isalnum() or c in "-_") else "_" for c in tag)
    return f"{stamp}_{safe_tag}.png"


class VaultRecorder:
    """Appends vault events and renders their chart snapshots."""

    def __init__(self, symbol: str, root: Path | str | None = None) -> None:
        self.symbol = symbol
        self.root = Path(root) if root is not None else DEFAULT_VAULT_ROOT
        self.near_miss_dir = self.root / symbol / "near_misses"
        self.loss_dir = self.root / symbol / "losses"
        self.ladder_dir = self.root / symbol / "ladders"

    # ------------------------------------------------------------------
    # Near misses
    # ------------------------------------------------------------------
    def record_near_miss(self, event: dict, bars: Sequence[Bar] | None = None) -> None:
        """Append one near-miss event + render its snapshot. Never raises."""
        try:
            record = self._normalise(event)
            record.setdefault("reason", "unknown")
            record.setdefault("resolved", False)
            record.setdefault("outcome", "open")
            self._append_jsonl(self.near_miss_dir / "events.jsonl", record)
            self._render(self.near_miss_dir, record, bars,
                         tag=record["reason"])
        except Exception as e:
            log.warning("near-miss vault write failed: %s", e)

    def alpha_hook(self, timeframe: str) -> AlphaNearMissHook:
        """Build the callback to attach as ``SupplyDemandAlpha.near_miss_hook``."""
        def hook(event: dict, bars: Sequence[Bar]) -> None:
            evt = dict(event)
            evt.setdefault("tf", timeframe)
            self.record_near_miss(evt, bars)
        return hook

    # ------------------------------------------------------------------
    # Losses
    # ------------------------------------------------------------------
    def record_loss(self, event: dict, bars: Sequence[Bar] | None = None) -> None:
        """Append one losing-trade event + render its lifetime snapshot.
        Never raises."""
        try:
            record = self._normalise(event)
            self._append_jsonl(self.loss_dir / "events.jsonl", record)
            self._render(self.loss_dir, record, bars, tag="loss",
                         entry_time=_parse_ts(record.get("entry_time")))
        except Exception as e:
            log.warning("loss vault write failed: %s", e)

    # ------------------------------------------------------------------
    # Extension-target ladders
    # ------------------------------------------------------------------
    def record_ladder(self, event: dict, bars: Sequence[Bar] | None = None) -> None:
        """Append one extension-ladder event + render its snapshot with the
        rung levels drawn. ``event["phase"]`` is "entry" (opinion published
        at fill time) or "close" (rungs scored against realised MFE).
        Never raises."""
        try:
            record = self._normalise(event)
            record.setdefault("phase", "entry")
            self._append_jsonl(self.ladder_dir / "events.jsonl", record)
            rung_prices = [
                r.get("price") for r in (record.get("rungs") or [])
                if isinstance(r, dict)
            ]
            self._render(self.ladder_dir, record, bars,
                         tag=f"ladder_{record['phase']}",
                         entry_time=_parse_ts(record.get("entry_time")),
                         extra_levels=rung_prices)
        except Exception as e:
            log.warning("ladder vault write failed: %s", e)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _normalise(self, event: dict) -> dict:
        record = dict(event)
        record.setdefault("ts", datetime.now(tz=timezone.utc).isoformat())
        if isinstance(record["ts"], datetime):
            record["ts"] = record["ts"].isoformat()
        record["symbol"] = self.symbol
        return record

    @staticmethod
    def _append_jsonl(path: Path, record: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def _render(
        self,
        folder: Path,
        record: dict,
        bars: Sequence[Bar] | None,
        *,
        tag: str,
        entry_time: datetime | None = None,
        extra_levels: Sequence[float] | None = None,
    ) -> None:
        if not bars:
            return
        ts = _parse_ts(record.get("ts"))
        zone = record.get("zone") or {}
        title = (f"{self.symbol} {record.get('tf', '')} — {tag} "
                 f"@ {record.get('ts', '')}")
        detail = self._build_detail(record)
        render_snapshot(
            bars,
            folder / _png_name(ts, tag),
            title=title,
            event_time=ts,
            entry=record.get("entry"),
            stop=record.get("stop"),
            take_profit=record.get("take_profit"),
            zone_top=zone.get("top"),
            zone_bottom=zone.get("bottom"),
            zone_direction=zone.get("direction"),
            zone_created_at=_parse_ts(zone.get("created_at")),
            zone_impulse_pips=zone.get("impulse_pips"),
            entry_time=entry_time,
            extra_levels=extra_levels,
            reason=record.get("reason") or tag,
            direction=record.get("direction"),
            detail=detail,
        )

    @staticmethod
    def _build_detail(record: dict) -> str | None:
        """Compose the bottom-right caption from whichever fields a given
        event type carries. Returns None when nothing useful is present."""
        # Per-reason captions read from the event dict the loop / alpha
        # built, so a near-miss caused by the HTF gate shows the bias and
        # mode while a risk-manager rejection shows the decision string.
        reason = record.get("reason")
        if reason == "htf_gate":
            parts = []
            bias = record.get("htf_bias")
            if bias:
                parts.append(f"htf_bias={bias}")
            mode = record.get("htf_align_mode")
            align = record.get("htf_align")
            if align or mode:
                parts.append(f"htf={align or '?'}({mode or '?'})")
            conv = record.get("conviction")
            if conv is not None:
                parts.append(f"conviction={float(conv):.2f}")
            return " · ".join(parts) if parts else None
        # Generic fallback: prefer an explicit detail string, then a
        # signal_reason fingerprint plus conviction so the operator still
        # gets context for sizing_skip / post_loss_guard / risk_manager.
        detail = record.get("detail")
        if detail:
            return str(detail)
        bits = []
        sig_reason = record.get("signal_reason")
        if sig_reason:
            bits.append(f"signal={sig_reason}")
        conv = record.get("conviction")
        if conv is not None:
            bits.append(f"conviction={float(conv):.2f}")
        return " · ".join(bits) if bits else None
