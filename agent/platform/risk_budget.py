"""F012 -- risk-budget hard-cap module (Sprint 2).

Three-tier max-loss cap enforced on every proposed live order:

1. **Per-day** -- total realised loss across every live order today
   (UTC-day slice).
2. **Per-symbol** -- per-pair daily cap (independent per pair).
3. **Per-strategy** -- per source-agent daily cap
   (``A1_baseline``, ``A2_widened``, etc.).

Public API
==========

.. code-block:: python

    DEFAULT_PER_DAY_MAX_LOSS: float = 100.0
    DEFAULT_PER_SYMBOL_MAX_LOSS: float = 50.0
    DEFAULT_PER_STRATEGY_MAX_LOSS: float = 50.0

    load_config() -> dict
    save_config(payload: dict) -> bool
    record_fill(symbol, strategy, pnl, ts=None) -> bool
    remaining_budget(scope="all") -> dict
    can_send_order(symbol, strategy, worst_case_loss) -> tuple[bool, str]
    reset_state() -> None

Live-mode-off gate contract
===========================

:func:`can_send_order` is the THIRD gate in the 4-check live-order
pathway (after :func:`live_mode_enabled` from F013 and
:func:`kill_switches.is_killed` from F011, before
``approval_queue.can_send_order`` from F013). Sprint 2 provides the
function only; wiring is future-sprint work.

This module MUST NOT import from ``agent/live/*``, ``agent/risk/*``,
or ``agent/squad/*`` (D065 invariant). It mimics the shape of the v1
risk manager without depending on it.

Persistence
===========

- Config: ``<config_dir>/risk_budget.toml``. Missing / malformed →
  defaults.
- State: ``<config_dir>/risk_state.jsonl``, one line per recorded
  fill: ``{"ts": iso8601, "symbol": ..., "strategy": ..., "pnl": ...}``.
  Only losses (``pnl < 0``) count against the cap; winning fills are
  recorded but do NOT add headroom (asymmetric cap by design so a
  lucky streak can't buy you the right to blow up harder).

Gate performance (A007, 2026-07-24 audit)
=========================================

``_today_losses`` used to re-parse the FULL history file on every
gate call, which degrades linearly as ``risk_state.jsonl`` grows. It
now keeps an in-process cache keyed by ``(file mtime_ns, file size,
UTC day)`` with the full scan as the fallback correctness path. This
was chosen over day-keyed segment files / compact-on-day-roll because
it changes no on-disk format and no other accessor: the gate is on
the order path, so correctness beats cleverness. Any append
(``record_fill``) changes mtime+size and invalidates the key; a UTC
day roll changes the day component; anything unexpected (missing
file, stat error) simply falls back to the scan.
"""
from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.platform import credentials

try:
    import tomllib as _tomllib
    _HAS_TOMLLIB = True
except ImportError:  # pragma: no cover
    try:
        import tomli as _tomllib
        _HAS_TOMLLIB = True
    except ImportError:  # pragma: no cover
        _HAS_TOMLLIB = False
        _tomllib = None  # type: ignore[assignment]

DEFAULT_PER_DAY_MAX_LOSS: float = 100.0
DEFAULT_PER_SYMBOL_MAX_LOSS: float = 50.0
DEFAULT_PER_STRATEGY_MAX_LOSS: float = 50.0

CONFIG_FILENAME: str = "risk_budget.toml"
STATE_FILENAME: str = "risk_state.jsonl"


def _config_path() -> Path:
    return credentials._config_dir() / CONFIG_FILENAME


def _state_path() -> Path:
    return credentials._config_dir() / STATE_FILENAME


def _default_config() -> dict:
    return {
        "per_day": {"max_loss": DEFAULT_PER_DAY_MAX_LOSS},
        "per_symbol": {"default": DEFAULT_PER_SYMBOL_MAX_LOSS},
        "per_strategy": {"default": DEFAULT_PER_STRATEGY_MAX_LOSS},
    }


def _coerce_number(value: Any, fallback: float) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(num) or num < 0:
        return fallback
    return num


def _merge_config(raw: dict) -> dict:
    """Fill missing tables / keys with defaults; ignore stray junk."""
    cfg = _default_config()
    if not isinstance(raw, dict):
        return cfg
    per_day = raw.get("per_day") or {}
    if isinstance(per_day, dict):
        cfg["per_day"]["max_loss"] = _coerce_number(
            per_day.get("max_loss"), DEFAULT_PER_DAY_MAX_LOSS)
    per_symbol = raw.get("per_symbol") or {}
    if isinstance(per_symbol, dict):
        merged: dict[str, float] = {
            "default": _coerce_number(
                per_symbol.get("default"), DEFAULT_PER_SYMBOL_MAX_LOSS),
        }
        for k, v in per_symbol.items():
            if k == "default":
                continue
            if isinstance(k, str) and k.isupper():
                merged[k] = _coerce_number(v, merged["default"])
        cfg["per_symbol"] = merged
    per_strategy = raw.get("per_strategy") or {}
    if isinstance(per_strategy, dict):
        merged_strat: dict[str, float] = {
            "default": _coerce_number(
                per_strategy.get("default"), DEFAULT_PER_STRATEGY_MAX_LOSS),
        }
        for k, v in per_strategy.items():
            if k == "default":
                continue
            if isinstance(k, str) and k:
                merged_strat[k] = _coerce_number(v, merged_strat["default"])
        cfg["per_strategy"] = merged_strat
    return cfg


def load_config() -> dict:
    """Read + normalise the risk-budget config.

    Missing file → :func:`_default_config`. Malformed TOML → also
    defaults (never raises). No side effects.
    """
    path = _config_path()
    if not path.exists() or not _HAS_TOMLLIB:
        return _default_config()
    try:
        with path.open("rb") as fh:
            raw = _tomllib.load(fh)
    except (OSError, _tomllib.TOMLDecodeError):  # type: ignore[attr-defined]
        return _default_config()
    return _merge_config(raw)


def _serialise_toml(cfg: dict) -> str:
    lines: list[str] = ["[per_day]"]
    lines.append(f"max_loss = {float(cfg['per_day']['max_loss'])}")
    lines.append("")
    lines.append("[per_symbol]")
    lines.append(f"default = {float(cfg['per_symbol']['default'])}")
    for sym, cap in cfg["per_symbol"].items():
        if sym == "default":
            continue
        lines.append(f"{sym} = {float(cap)}")
    lines.append("")
    lines.append("[per_strategy]")
    lines.append(f"default = {float(cfg['per_strategy']['default'])}")
    for strat, cap in cfg["per_strategy"].items():
        if strat == "default":
            continue
        lines.append(f"{strat} = {float(cap)}")
    return "\n".join(lines) + "\n"


def save_config(payload: dict) -> bool:
    """Merge ``payload`` with defaults and write TOML atomically.

    Returns True on success; False on IO failure.
    """
    cfg = _merge_config(payload)
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = _serialise_toml(cfg)
    try:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
        return True
    except OSError:
        return False


def _today_utc_iso_prefix(now: float | None = None) -> str:
    dt = datetime.now(tz=timezone.utc) if now is None \
        else datetime.fromtimestamp(now, tz=timezone.utc)
    return dt.date().isoformat()


def _iter_state(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    out: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _now_iso(ts: float | None = None) -> str:
    dt = datetime.now(tz=timezone.utc) if ts is None \
        else datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.isoformat(timespec="seconds")


def record_fill(symbol: str, strategy: str, pnl: float,
                ts: float | None = None) -> bool:
    """Append one fill to ``risk_state.jsonl``. Returns True on success."""
    row = {
        "ts": _now_iso(ts),
        "symbol": str(symbol),
        "strategy": str(strategy),
        "pnl": float(pnl),
    }
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True))
            fh.write("\n")
        return True
    except OSError:
        return False


@dataclass
class _TodayLosses:
    total: float
    by_symbol: dict[str, float]
    by_strategy: dict[str, float]


# A007 -- gate-call cache: {"key": ((mtime_ns, size) | None, day_prefix),
# "value": _TodayLosses}. See the module docstring for the rationale.
_LOSSES_CACHE_LOCK = threading.Lock()
_LOSSES_CACHE: dict | None = None


def _losses_cache_key(prefix: str) -> tuple:
    path = _state_path()
    try:
        st = path.stat()
        stat_key: tuple | None = (st.st_mtime_ns, st.st_size)
    except OSError:
        stat_key = None
    # Path is part of the key so a config-dir change (tests, env
    # override) can never serve losses computed for a different file.
    return (str(path), stat_key, prefix)


def _scan_today_losses(prefix: str) -> _TodayLosses:
    """Full-scan fallback: parse every row and sum today's losses."""
    total = 0.0
    by_symbol: dict[str, float] = {}
    by_strategy: dict[str, float] = {}
    for row in _iter_state(_state_path()):
        ts = row.get("ts", "")
        if not isinstance(ts, str) or not ts.startswith(prefix):
            continue
        try:
            pnl = float(row.get("pnl", 0.0))
        except (TypeError, ValueError):
            continue
        if pnl >= 0:
            continue
        loss = -pnl
        total += loss
        sym = str(row.get("symbol", ""))
        strat = str(row.get("strategy", ""))
        by_symbol[sym] = by_symbol.get(sym, 0.0) + loss
        by_strategy[strat] = by_strategy.get(strat, 0.0) + loss
    return _TodayLosses(total=total, by_symbol=by_symbol,
                        by_strategy=by_strategy)


def _copy_losses(losses: _TodayLosses) -> _TodayLosses:
    return _TodayLosses(total=losses.total,
                        by_symbol=dict(losses.by_symbol),
                        by_strategy=dict(losses.by_strategy))


def _today_losses(now: float | None = None) -> _TodayLosses:
    """Today's realised losses, O(1) on repeated gate calls.

    Cached per (file mtime_ns, file size, UTC day); any append or day
    roll misses the cache and re-runs the full scan (the correctness
    path). Callers receive copies so cached state is mutation-safe."""
    global _LOSSES_CACHE
    prefix = _today_utc_iso_prefix(now)
    key = _losses_cache_key(prefix)
    with _LOSSES_CACHE_LOCK:
        if _LOSSES_CACHE is not None and _LOSSES_CACHE["key"] == key:
            return _copy_losses(_LOSSES_CACHE["value"])
    losses = _scan_today_losses(prefix)
    with _LOSSES_CACHE_LOCK:
        _LOSSES_CACHE = {"key": key, "value": _copy_losses(losses)}
    return losses


def _cap_for_symbol(cfg: dict, symbol: str) -> float:
    per_symbol = cfg.get("per_symbol", {})
    return float(per_symbol.get(symbol,
                                per_symbol.get("default",
                                               DEFAULT_PER_SYMBOL_MAX_LOSS)))


def _cap_for_strategy(cfg: dict, strategy: str) -> float:
    per_strategy = cfg.get("per_strategy", {})
    return float(per_strategy.get(strategy,
                                  per_strategy.get(
                                      "default",
                                      DEFAULT_PER_STRATEGY_MAX_LOSS)))


def remaining_budget(scope: str = "all",
                     now: float | None = None) -> dict:
    """Return a dict of remaining-loss headroom by scope.

    Shape::

        {
          "per_day":       {"cap": 100.0, "used": 12.5, "remaining": 87.5},
          "per_symbol":    {"EURUSD": {"cap": 50.0, "used": 8.0, ...}, ...},
          "per_strategy":  {"A1_baseline": {"cap": 50.0, "used": 4.5, ...}, ...},
          "as_of":         iso8601,
        }

    ``scope`` is accepted for future filtering (``"per_day"``,
    ``"per_symbol"``, ``"per_strategy"``, ``"all"``); Sprint 2 always
    returns the full payload -- the argument is a compat placeholder.
    """
    del scope
    cfg = load_config()
    losses = _today_losses(now)

    per_day_cap = float(cfg["per_day"].get(
        "max_loss", DEFAULT_PER_DAY_MAX_LOSS))
    per_day_used = round(losses.total, 4)
    per_day_remaining = round(max(0.0, per_day_cap - per_day_used), 4)

    per_symbol: dict[str, dict[str, float]] = {}
    seen_symbols = set(losses.by_symbol.keys())
    seen_symbols.update(k for k in cfg["per_symbol"].keys() if k != "default")
    for sym in sorted(seen_symbols):
        cap = _cap_for_symbol(cfg, sym)
        used = round(losses.by_symbol.get(sym, 0.0), 4)
        per_symbol[sym] = {
            "cap": cap,
            "used": used,
            "remaining": round(max(0.0, cap - used), 4),
        }

    per_strategy: dict[str, dict[str, float]] = {}
    seen_strat = set(losses.by_strategy.keys())
    seen_strat.update(k for k in cfg["per_strategy"].keys() if k != "default")
    for strat in sorted(seen_strat):
        cap = _cap_for_strategy(cfg, strat)
        used = round(losses.by_strategy.get(strat, 0.0), 4)
        per_strategy[strat] = {
            "cap": cap,
            "used": used,
            "remaining": round(max(0.0, cap - used), 4),
        }

    return {
        "per_day": {
            "cap": per_day_cap,
            "used": per_day_used,
            "remaining": per_day_remaining,
        },
        "per_symbol": per_symbol,
        "per_symbol_default": float(cfg["per_symbol"]["default"]),
        "per_strategy": per_strategy,
        "per_strategy_default": float(cfg["per_strategy"]["default"]),
        "as_of": _now_iso(now),
    }


def can_send_order(symbol: str, strategy: str,
                   worst_case_loss: float,
                   now: float | None = None) -> tuple[bool, str]:
    """Return ``(allowed, reason)`` for a proposed live order.

    ``worst_case_loss`` must be a NON-NEGATIVE dollar amount; a
    negative or non-finite value is treated as an invalid ask and
    refused with a descriptive reason. Returns ``(True, "ok")`` iff
    every one of the three caps has enough headroom for the ask.
    """
    try:
        loss = float(worst_case_loss)
    except (TypeError, ValueError):
        return False, "invalid worst_case_loss (not numeric)"
    if not math.isfinite(loss) or loss < 0:
        return False, "invalid worst_case_loss (must be finite and >= 0)"

    cfg = load_config()
    losses = _today_losses(now)

    per_day_cap = float(cfg["per_day"].get(
        "max_loss", DEFAULT_PER_DAY_MAX_LOSS))
    if losses.total + loss > per_day_cap:
        return False, (
            f"per-day cap exceeded: {losses.total + loss:.2f} > "
            f"{per_day_cap:.2f}"
        )

    sym_cap = _cap_for_symbol(cfg, symbol)
    sym_used = losses.by_symbol.get(symbol, 0.0)
    if sym_used + loss > sym_cap:
        return False, (
            f"per-symbol cap exceeded for {symbol}: "
            f"{sym_used + loss:.2f} > {sym_cap:.2f}"
        )

    strat_cap = _cap_for_strategy(cfg, strategy)
    strat_used = losses.by_strategy.get(strategy, 0.0)
    if strat_used + loss > strat_cap:
        return False, (
            f"per-strategy cap exceeded for {strategy}: "
            f"{strat_used + loss:.2f} > {strat_cap:.2f}"
        )
    return True, "ok"


def reset_state() -> None:  # claim-exempt: test-only state wipe, no HTTP surface
    """Test helper -- wipe ``risk_state.jsonl`` (and the A007 cache)."""
    global _LOSSES_CACHE
    with _LOSSES_CACHE_LOCK:
        _LOSSES_CACHE = None
    path = _state_path()
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass
