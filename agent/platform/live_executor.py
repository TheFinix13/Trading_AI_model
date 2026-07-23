"""F018 -- demo-order executor: the four gates get their ONE caller.

Sprint 2 shipped four independent gates and D065 forbade wiring them.
Sprint 2b (D097) supersedes that invariant NARROWLY, for DEMO accounts
only: this module is the single pathway through which an approved
entry may reach a broker, and it is structurally unable to reach a
non-demo server.

The stack, in refusal order (every step fail-closed):

1. ``[live_executor] enabled`` -- gate #5, DEFAULT FALSE.
2. The approval exists and has never been consumed (single-use).
3. :func:`approval_queue.can_send_live_order` -- all FOUR Sprint-2
   gates (live-mode ceremony, kill-switches, risk budget, approval),
   re-run fresh immediately before send, never cached.
4. A broker alias is configured AND credentials exist in the F006
   keyring for it (credentials are loaded by the adapter, never
   logged, never echoed).
5. DEMO-ONLY guard: ``demo_only = true`` literal acknowledgement AND
   the CONNECTED server's reported name matches
   ``allowed_server_patterns`` (fnmatch, case-sensitive, fail-closed
   on blank/missing/unmatched).
6. Volume hard-cap: ``max_volume_lots`` (default 0.01).

On fill: the fill is recorded to ``risk_budget`` (audit row, pnl 0.0
at fill time -- realised pnl is a later concern), the approval is
consumed, and a ``trade_fill`` alert is published. On send error: the
approval is ALSO consumed (an approval whose send errored must not be
silently replayable), an alert is published, and there is NO
automatic retry. Every attempt -- refusals included -- appends one
row to ``<config_dir>/executions.jsonl``.

MetaTrader5 is a Windows-only package; ALL MT5 interaction rides the
injectable :class:`Mt5OrderAdapter` seam. :class:`RealMt5OrderAdapter`
imports MetaTrader5 lazily inside methods; tests (and non-Windows
hosts) use :class:`FakeMt5OrderAdapter`.

This module MUST NOT import from ``agent/live/*``, ``agent/risk/*``,
or ``agent/squad/*`` (Sprint 2b zero-diff invariant).
"""
from __future__ import annotations

import importlib.util
import json
import threading
import time
from datetime import datetime, timezone
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Protocol

from agent.platform import approval_queue, broker_connection, risk_budget

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

EXECUTIONS_FILENAME: str = "executions.jsonl"
DEFAULT_MAX_VOLUME_LOTS: float = 0.01
DEFAULT_ALLOWED_SERVER_PATTERNS: tuple[str, ...] = (
    "*Trial*", "*Demo*", "*demo*")

# Reported by executor_status().state:
#   disabled       -- [live_executor] enabled is false (gate #5)
#   not-on-windows -- enabled, but MetaTrader5 is not importable here
#   ready          -- enabled and the adapter package is importable
EXECUTOR_STATES: tuple[str, ...] = ("disabled", "not-on-windows", "ready")

# Execution-row statuses that CONSUME the approval (single-use). A
# refusal happens before any send attempt and does not burn the
# human's approval; a send attempt -- filled OR errored -- does.
_CONSUMING_STATUSES: frozenset[str] = frozenset({"filled", "error"})

_LOCK = threading.RLock()
_CONSUMED: set[str] = set()


# ---------------------------------------------------------------------
# adapter seam
# ---------------------------------------------------------------------

class Mt5OrderAdapter(Protocol):
    """The injectable MT5 seam. Implementations MUST NOT log or echo
    credentials; ``connect`` receives only the broker ALIAS and loads
    the credential tuple itself via
    ``broker_connection.load_credentials``."""

    def connect(self, alias: str) -> bool: ...

    def account_info(self) -> dict: ...

    def send_market_order(self, symbol: str, side: str, volume: float,
                          sl: float, tp: float) -> dict: ...

    def close_position(self, ticket: int) -> dict: ...

    def shutdown(self) -> None: ...


def adapter_available() -> bool:
    """True iff the MetaTrader5 package is importable on this host
    (it is Windows-only; macOS / Linux hosts return False)."""
    try:
        return importlib.util.find_spec("MetaTrader5") is not None
    except (ImportError, ValueError):
        return False


class RealMt5OrderAdapter:
    """MetaTrader5-backed adapter. The import happens lazily INSIDE
    methods so that merely constructing (or importing this module on
    a non-Windows host) never touches the package."""

    def __init__(self) -> None:
        self._connected = False

    @staticmethod
    def _mt5():
        import MetaTrader5 as mt5  # noqa: PLC0415 -- lazy, Windows-only
        return mt5

    def connect(self, alias: str) -> bool:
        creds = broker_connection.load_credentials(alias)
        if creds is None:
            return False
        mt5 = self._mt5()
        if not mt5.initialize():
            return False
        ok = mt5.login(int(creds["login"]), password=creds["password"],
                       server=creds["server"])
        # The credential dict stays local; nothing here logs it.
        self._connected = bool(ok)
        if not ok:
            mt5.shutdown()
        return self._connected

    def account_info(self) -> dict:
        mt5 = self._mt5()
        info = mt5.account_info()
        if info is None:
            return {}
        return {
            "login": getattr(info, "login", None),
            "server": getattr(info, "server", "") or "",
            "balance": getattr(info, "balance", None),
            "currency": getattr(info, "currency", None),
            "trade_mode": getattr(info, "trade_mode", None),
        }

    def send_market_order(self, symbol: str, side: str, volume: float,
                          sl: float, tp: float) -> dict:
        mt5 = self._mt5()
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return {"error": f"no tick data for {symbol}"}
        is_buy = side == "buy"
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(volume),
            "type": mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL,
            "price": tick.ask if is_buy else tick.bid,
            "sl": float(sl),
            "tp": float(tp),
            "deviation": 20,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None:
            return {"error": "order_send returned None"}
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return {"error": f"retcode {result.retcode}: "
                             f"{getattr(result, 'comment', '')}"}
        return {"ticket": int(result.order),
                "price": float(getattr(result, "price", 0.0)),
                "volume": float(getattr(result, "volume", volume))}

    def close_position(self, ticket: int) -> dict:
        mt5 = self._mt5()
        positions = mt5.positions_get(ticket=int(ticket))
        if not positions:
            return {"error": f"no open position with ticket {ticket}"}
        pos = positions[0]
        tick = mt5.symbol_info_tick(pos.symbol)
        if tick is None:
            return {"error": f"no tick data for {pos.symbol}"}
        closing_buy = pos.type == mt5.POSITION_TYPE_SELL
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": float(pos.volume),
            "type": mt5.ORDER_TYPE_BUY if closing_buy
            else mt5.ORDER_TYPE_SELL,
            "position": int(ticket),
            "price": tick.ask if closing_buy else tick.bid,
            "deviation": 20,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            return {"error": "close failed"}
        return {"ticket": int(ticket), "closed": True}

    def shutdown(self) -> None:
        if self._connected:
            try:
                self._mt5().shutdown()
            except Exception:
                pass
            self._connected = False


class FakeMt5OrderAdapter:
    """Deterministic test double (also used by the dogfood harness).

    Configure the server name it reports and the result of
    ``send_market_order``; it records every call for assertions.
    """

    def __init__(self, *, server: str = "Exness-MT5Trial9",
                 connect_ok: bool = True,
                 send_result: dict | None = None,
                 connect_raises: bool = False,
                 send_raises: bool = False) -> None:
        self.server = server
        self.connect_ok = connect_ok
        self.send_result = send_result if send_result is not None \
            else {"ticket": 10001, "price": 1.0, "volume": 0.01}
        self.connect_raises = connect_raises
        self.send_raises = send_raises
        self.calls: list[tuple] = []
        self.connected_alias: str | None = None
        self.shutdown_called = False

    def connect(self, alias: str) -> bool:
        self.calls.append(("connect", alias))
        if self.connect_raises:
            raise RuntimeError("fake connect explosion")
        if self.connect_ok:
            self.connected_alias = alias
        return self.connect_ok

    def account_info(self) -> dict:
        self.calls.append(("account_info",))
        return {"login": 436983644, "server": self.server,
                "balance": 500.0, "currency": "USD"}

    def send_market_order(self, symbol: str, side: str, volume: float,
                          sl: float, tp: float) -> dict:
        self.calls.append(("send_market_order", symbol, side, volume,
                           sl, tp))
        if self.send_raises:
            raise RuntimeError("fake send explosion")
        return dict(self.send_result)

    def close_position(self, ticket: int) -> dict:
        self.calls.append(("close_position", ticket))
        return {"ticket": int(ticket), "closed": True}

    def shutdown(self) -> None:
        self.calls.append(("shutdown",))
        self.shutdown_called = True


# ---------------------------------------------------------------------
# config
# ---------------------------------------------------------------------

def load_executor_config(cfg: dict | None = None) -> dict:
    """Normalised ``[live_executor]`` block.

    ``cfg`` may be a full platform config dict (the ``live_executor``
    key is used), the block itself, or None (platform.toml is read via
    ``agent.platform.config.load_config``). Every field falls back to
    the fail-closed default.
    """
    if cfg is None:
        from agent.platform.config import load_config as _load
        cfg = _load(REPO_ROOT)
    block = cfg.get("live_executor") if isinstance(cfg, dict) \
        and "live_executor" in cfg else cfg
    if not isinstance(block, dict):
        block = {}
    patterns = block.get("allowed_server_patterns")
    if isinstance(patterns, (list, tuple)):
        cleaned = [str(p).strip() for p in patterns if str(p).strip()]
    else:
        cleaned = list(DEFAULT_ALLOWED_SERVER_PATTERNS)
    try:
        max_vol = float(block.get("max_volume_lots",
                                  DEFAULT_MAX_VOLUME_LOTS))
        if not max_vol > 0:
            max_vol = DEFAULT_MAX_VOLUME_LOTS
    except (TypeError, ValueError):
        max_vol = DEFAULT_MAX_VOLUME_LOTS
    return {
        "enabled": block.get("enabled") is True,
        "demo_only": block.get("demo_only") is True,
        "allowed_server_patterns": cleaned,
        "max_volume_lots": max_vol,
        "broker_alias": str(block.get("broker_alias") or "").strip(),
    }


def is_enabled(cfg: dict | None = None) -> bool:
    """Gate #5. False on a clean install, false on junk config."""
    return load_executor_config(cfg)["enabled"]


def demo_guard(server: str, cfg: dict | None = None) -> tuple[bool, str]:
    """DEMO-ONLY guard (Sprint 2b P0 invariant #3). Fail-closed:

    * ``demo_only = true`` must be the LITERAL acknowledgement in
      platform.toml -- absent/false/junk refuses.
    * The connected server's reported name must be non-blank and
      match at least one ``allowed_server_patterns`` glob
      (case-sensitive fnmatch).
    """
    block = load_executor_config(cfg)
    if not block["demo_only"]:
        return False, ("demo_only acknowledgement missing: set "
                       "[live_executor] demo_only = true in "
                       "platform.toml")
    name = str(server or "").strip()
    if not name:
        return False, "connected server reported a blank name (refusing)"
    patterns = block["allowed_server_patterns"]
    if not patterns:
        return False, "allowed_server_patterns is empty (refusing)"
    if not any(fnmatchcase(name, pat) for pat in patterns):
        return False, (f"server {name!r} does not match the demo "
                       f"allowlist {patterns} (refusing)")
    return True, "ok"


# ---------------------------------------------------------------------
# executions audit trail + single-use marking
# ---------------------------------------------------------------------

def _executions_path() -> Path:
    from agent.platform import credentials as _credentials
    return _credentials._config_dir() / EXECUTIONS_FILENAME


def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _append_execution(row: dict) -> None:
    path = _executions_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    except OSError:
        pass


def _load_consumed_from_disk() -> set[str]:
    """Approvals consumed in PREVIOUS processes still count -- replay
    of a single human approval across restarts must be impossible."""
    consumed: set[str] = set()
    path = _executions_path()
    if not path.is_file():
        return consumed
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return consumed
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) \
                and row.get("status") in _CONSUMING_STATUSES \
                and row.get("approval_id"):
            consumed.add(str(row["approval_id"]))
    return consumed


def _is_consumed(approval_id: str) -> bool:
    with _LOCK:
        if approval_id in _CONSUMED:
            return True
        disk = _load_consumed_from_disk()
        _CONSUMED.update(disk)
        return approval_id in _CONSUMED


def _mark_consumed(approval_id: str) -> None:
    with _LOCK:
        _CONSUMED.add(approval_id)


def recent_executions(limit: int = 20) -> list[dict]:
    """Last N rows of the executions audit JSONL, newest first."""
    path = _executions_path()
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    rows: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows[::-1][:max(0, int(limit))]


# ---------------------------------------------------------------------
# execution flow
# ---------------------------------------------------------------------

def _publish_alert(event_type: str, payload: dict) -> None:
    try:
        from agent.platform import alerts as _alerts
        _alerts.publish(event_type, payload)
    except Exception:
        # A broken bus must never block or crash the executor's
        # refusal/consumption bookkeeping.
        pass


def _outcome(approval_id: str, entry: dict | None, status: str,
             reason: str, *, ticket: int | None = None,
             record: bool = True) -> dict:
    row = {
        "at": _iso_now(),
        "approval_id": approval_id,
        "symbol": (entry or {}).get("symbol"),
        "side": (entry or {}).get("side"),
        "volume": (entry or {}).get("size"),
        "status": status,
        "reason": reason,
        "ticket": ticket,
    }
    if record:
        _append_execution(row)
    return {
        "ok": status == "filled",
        "status": status,
        "reason": reason,
        "ticket": ticket,
        "approval_id": approval_id,
    }


def execute_approved(approval_id: str, adapter: Mt5OrderAdapter,
                     cfg: dict | None = None) -> dict:
    """THE one caller of the four gates. Returns
    ``{ok, status: filled|error|refused, reason, ticket, approval_id}``.

    Refusals happen BEFORE any send attempt and do not consume the
    approval. A send attempt -- filled or errored -- consumes it
    (single-use). There is no automatic retry on any path.
    """
    approval_id = str(approval_id)
    block = load_executor_config(cfg)

    # Gate #5 -- default-disabled.
    if not block["enabled"]:
        return _outcome(approval_id, None, "refused",
                        "executor disabled ([live_executor] enabled = "
                        "false is the default)")

    entry = approval_queue.get_entry(approval_id)
    if entry is None:
        return _outcome(approval_id, None, "refused",
                        "unknown approval id")

    # Single-use: one human approval, at most one send attempt.
    if _is_consumed(approval_id):
        return _outcome(approval_id, entry, "refused",
                        "approval already consumed (single-use)")

    # The four Sprint-2 gates, re-run fresh immediately before send.
    ok, why = approval_queue.can_send_live_order(entry)
    if not ok:
        return _outcome(approval_id, entry, "refused",
                        f"gate refused: {why}")

    # Broker alias + stored credentials must exist (the adapter loads
    # the tuple itself; it is never logged and never leaves process).
    alias = block["broker_alias"]
    if not alias:
        return _outcome(approval_id, entry, "refused",
                        "no [live_executor] broker_alias configured")
    try:
        creds_present = broker_connection.load_credentials(alias) \
            is not None
    except Exception:
        creds_present = False
    if not creds_present:
        return _outcome(approval_id, entry, "refused",
                        f"no stored credentials for alias {alias!r}")

    try:
        connected = adapter.connect(alias)
    except Exception as exc:
        return _outcome(approval_id, entry, "refused",
                        f"adapter connect failed: {exc!s:.120}")
    if not connected:
        return _outcome(approval_id, entry, "refused",
                        "adapter connect refused")

    try:
        # DEMO-ONLY guard against the server the adapter ACTUALLY
        # connected to -- not against config or stored intent.
        try:
            server = str(adapter.account_info().get("server", ""))
        except Exception:
            server = ""
        guard_ok, guard_why = demo_guard(server, cfg)
        if not guard_ok:
            return _outcome(approval_id, entry, "refused",
                            f"demo guard: {guard_why}")

        # Volume hard-cap.
        volume = float(entry["size"])
        if volume > block["max_volume_lots"]:
            return _outcome(
                approval_id, entry, "refused",
                f"volume {volume} exceeds max_volume_lots "
                f"{block['max_volume_lots']} (hard cap)")

        # Send. From here on the approval is consumed regardless of
        # outcome -- an errored send must not be silently replayable.
        _mark_consumed(approval_id)
        try:
            result = adapter.send_market_order(
                str(entry["symbol"]), str(entry["side"]), volume,
                float(entry["stop"]), float(entry["take_profit"]))
        except Exception as exc:
            result = {"error": f"adapter raised: {exc!s:.120}"}

        if not isinstance(result, dict):
            result = {"error": "adapter returned a non-dict result"}

        if result.get("error") or "ticket" not in result:
            reason = str(result.get("error") or
                         "adapter returned no ticket")
            _publish_alert("trade_fill", {
                "status": "error",
                "approval_id": approval_id,
                "symbol": entry.get("symbol"),
                "side": entry.get("side"),
                "volume": volume,
                "reason": reason,
            })
            return _outcome(approval_id, entry, "error", reason)

        ticket = int(result["ticket"])
        # Audit the fill into the F012 ledger (pnl 0.0 at fill time --
        # only realised losses count against caps, and there are none
        # yet at the moment of the fill).
        risk_budget.record_fill(str(entry["symbol"]),
                                str(entry["source_agent"]), 0.0)
        _publish_alert("trade_fill", {
            "status": "filled",
            "approval_id": approval_id,
            "symbol": entry.get("symbol"),
            "side": entry.get("side"),
            "volume": volume,
            "ticket": ticket,
        })
        return _outcome(approval_id, entry, "filled", "ok",
                        ticket=ticket)
    finally:
        try:
            adapter.shutdown()
        except Exception:
            pass


# ---------------------------------------------------------------------
# status surface
# ---------------------------------------------------------------------

def executor_status(cfg: dict | None = None) -> dict:
    """The ``GET /api/executor/status`` payload. Never echoes
    credentials -- only whether an alias is configured."""
    block = load_executor_config(cfg)
    available = adapter_available()
    if not block["enabled"]:
        state = "disabled"
    elif not available:
        state = "not-on-windows"
    else:
        state = "ready"
    return {
        "enabled": block["enabled"],
        "demo_only_ack": block["demo_only"],
        "allowed_server_patterns": list(block["allowed_server_patterns"]),
        "max_volume_lots": block["max_volume_lots"],
        "broker_alias_configured": bool(block["broker_alias"]),
        "adapter_available": available,
        "state": state,
        "recent_executions": recent_executions(10),
    }


def reset_state_for_tests() -> None:  # claim-exempt: test-only state wipe, no HTTP surface
    """Clear the consumed-set and drop executions.jsonl. Callers must
    have pointed ``credentials.set_config_dir`` at a throwaway dir."""
    with _LOCK:
        _CONSUMED.clear()
    path = _executions_path()
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


__all__ = [
    "EXECUTIONS_FILENAME",
    "DEFAULT_MAX_VOLUME_LOTS",
    "DEFAULT_ALLOWED_SERVER_PATTERNS",
    "EXECUTOR_STATES",
    "Mt5OrderAdapter",
    "RealMt5OrderAdapter",
    "FakeMt5OrderAdapter",
    "adapter_available",
    "load_executor_config",
    "is_enabled",
    "demo_guard",
    "execute_approved",
    "recent_executions",
    "executor_status",
    "reset_state_for_tests",
]
