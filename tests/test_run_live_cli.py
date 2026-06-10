"""run_live CLI contract: --symbol must plumb through to route building and
the live config, undeployed symbols must still refuse to start, and the
per-symbol daily log file must be wired to the root logger.

No real broker connections: route building and startup health are stubbed
at the same seams used by tests/test_live_router_wiring.py.
"""
from __future__ import annotations

import asyncio
import importlib.util
import logging
import logging.handlers
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.live.broker import MT5Broker
from agent.live.router_wiring import UndeployedSymbolError

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# scripts/ is not a package; load run_live.py as a module the same way the
# CLI runs it.
_spec = importlib.util.spec_from_file_location(
    "run_live", _PROJECT_ROOT / "scripts" / "run_live.py")
run_live = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_live)


# ----------------------------------------------------------------------
# --symbol flag plumbs through to route building
# ----------------------------------------------------------------------

def _run_main_capturing_routes(monkeypatch, argv: list[str]) -> dict:
    """Drive run_live.main() up to build_live_routes with stubs, capturing
    the symbol it was asked to route. Raises SystemExit via the undeployed
    path so no broker is ever touched."""
    captured: dict = {}

    def fake_build(symbol, cfg):
        captured["symbol"] = symbol
        captured["cfg_symbol"] = cfg.symbol
        raise UndeployedSymbolError("stop before broker")

    monkeypatch.setattr(run_live, "build_live_routes", fake_build)

    def fake_setup(symbol, log_dir=None):
        captured["log_dir"] = log_dir
        return Path(f"/dev/null/{symbol}/{symbol}_2026-06-10.log")

    monkeypatch.setattr(run_live, "setup_live_logging", fake_setup)
    monkeypatch.setattr(sys, "argv", ["run_live.py", *argv])
    with pytest.raises(SystemExit):
        run_live.main()
    assert "symbol" in captured, "build_live_routes was never reached"
    return captured


def test_symbol_flag_overrides_env_for_route_building(monkeypatch):
    monkeypatch.setenv("SYMBOL", "EURUSD")
    captured = _run_main_capturing_routes(monkeypatch, ["--symbol", "GBPUSD"])
    assert captured["symbol"] == "GBPUSD"
    assert captured["cfg_symbol"] == "GBPUSD"


def test_symbol_flag_short_form_and_lowercase(monkeypatch):
    captured = _run_main_capturing_routes(monkeypatch, ["-s", "usdcad"])
    assert captured["symbol"] == "USDCAD"


def test_default_still_honors_symbol_env_var(monkeypatch):
    monkeypatch.setenv("SYMBOL", "USDCAD")
    captured = _run_main_capturing_routes(monkeypatch, [])
    assert captured["symbol"] == "USDCAD"


def test_log_dir_flag_passed_to_setup(monkeypatch, tmp_path):
    captured = _run_main_capturing_routes(
        monkeypatch, ["--symbol", "EURUSD", "--log-dir", str(tmp_path)])
    assert captured["log_dir"] == tmp_path


def test_log_dir_defaults_to_none_for_setup_default(monkeypatch):
    captured = _run_main_capturing_routes(monkeypatch, ["-s", "EURUSD"])
    assert captured["log_dir"] is None


def test_undeployed_symbol_refuses_to_start(monkeypatch):
    """Real build_live_routes: a symbol with no deployed cell exits(1)."""
    monkeypatch.setattr(run_live, "setup_live_logging",
                        lambda symbol, log_dir=None: Path(f"/dev/null/{symbol}/x.log"))
    monkeypatch.setattr(sys, "argv", ["run_live.py", "--symbol", "USDJPY"])
    with pytest.raises(SystemExit) as exc:
        run_live.main()
    assert exc.value.code == 1


def test_symbol_flag_flows_into_live_config(monkeypatch):
    """live.symbol (built by _build_live_config) must reflect the flag."""
    captured: dict = {}

    fake_route = SimpleNamespace(
        symbol="GBPUSD", timeframe="H4", session="all", mode="htf_against",
        risk_scale=0.5, alpha=SimpleNamespace(name="zone_h4_all"),
    )
    monkeypatch.setattr(run_live, "build_live_routes",
                        lambda symbol, cfg: [fake_route])
    monkeypatch.setattr(run_live, "setup_live_logging",
                        lambda symbol, log_dir=None: Path(f"/dev/null/{symbol}/x.log"))

    async def fake_health(args, cfg, live):
        captured["live"] = live
        return False  # forces exit(1) before any SignalLoop is built

    monkeypatch.setattr(run_live, "_startup_health", fake_health)
    monkeypatch.setattr(sys, "argv", ["run_live.py", "--symbol", "GBPUSD"])
    with pytest.raises(SystemExit):
        run_live.main()

    assert captured["live"].symbol == "GBPUSD"
    assert captured["live"].timeframes == ["H4"]


# ----------------------------------------------------------------------
# Per-symbol daily log files: {log_dir}/{SYMBOL}/{SYMBOL}_{YYYY-MM-DD}.log
# ----------------------------------------------------------------------

def _attach_logging(tmp_path):
    """Call setup_live_logging into tmp_path; return (path, handler, cleanup)."""
    root = logging.getLogger()
    before = list(root.handlers)
    path = run_live.setup_live_logging("EURUSD", log_dir=tmp_path)
    new = [h for h in root.handlers if h not in before]

    def cleanup():
        for h in new:
            root.removeHandler(h)
            h.close()

    return path, new, cleanup


def test_setup_live_logging_per_symbol_dated_file(tmp_path):
    path, new, cleanup = _attach_logging(tmp_path)
    try:
        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        assert path == tmp_path / "EURUSD" / f"EURUSD_{today}.log"
        assert path.parent.is_dir()
        assert len(new) == 1
        handler = new[0]
        assert isinstance(handler, logging.handlers.TimedRotatingFileHandler)
        assert handler.when == "MIDNIGHT"
        assert handler.utc is True
        assert handler.backupCount == 30

        # Root attachment: any agent.* logger flows into the file.
        # (WARNING so the check is independent of the ambient root level,
        # which pytest leaves at its default.)
        logging.getLogger("agent.live.signal_loop").warning("file sink check")
        handler.flush()
        assert "file sink check" in path.read_text(encoding="utf-8")
    finally:
        cleanup()


def test_rollover_switches_to_new_dated_file(tmp_path, monkeypatch):
    """A process left running across UTC midnight starts a NEW
    symbol-prefixed dated file (no rename of the old one)."""
    path, new, cleanup = _attach_logging(tmp_path)
    try:
        handler = new[0]
        logging.getLogger("agent.live.signal_loop").warning("day one line")
        monkeypatch.setattr(
            run_live._DailyDateFileHandler, "_current_name",
            lambda self: f"{self._symbol}_2099-01-01.log")
        handler.doRollover()
        logging.getLogger("agent.live.signal_loop").warning("day two line")
        handler.flush()

        next_day = tmp_path / "EURUSD" / "EURUSD_2099-01-01.log"
        assert "day one line" in path.read_text(encoding="utf-8")
        assert "day one line" not in next_day.read_text(encoding="utf-8")
        assert "day two line" in next_day.read_text(encoding="utf-8")
        assert handler.rolloverAt > time.time()
    finally:
        cleanup()


def test_default_log_root_is_user_documents_folder():
    assert run_live.DEFAULT_LOG_ROOT == (
        Path.home() / "Documents" / "TradingAgentLogs")


# ----------------------------------------------------------------------
# MT5 Market Watch selection (stubbed mt5 module — no Windows needed)
# ----------------------------------------------------------------------

class _FakeMT5:
    """Records the call order of symbol_select vs copy_rates."""

    TIMEFRAME_H4 = 4

    def __init__(self, known: set[str] = frozenset({"EURUSD"})):
        self._known = known
        self.calls: list[tuple] = []

    def symbol_info(self, name):
        return SimpleNamespace(name=name) if name in self._known else None

    def symbol_select(self, name, enable=True):
        self.calls.append(("select", name, enable))
        return True

    def symbols_get(self):
        return [SimpleNamespace(name=n) for n in self._known]

    def copy_rates_from_pos(self, symbol, tf, start, count):
        self.calls.append(("copy_rates", symbol))
        return [{"time": 1_718_000_000, "open": 1.07, "high": 1.08,
                 "low": 1.06, "close": 1.075, "tick_volume": 100.0}]

    def last_error(self):
        return (0, "ok")


def _broker_with(fake: _FakeMT5) -> MT5Broker:
    broker = MT5Broker(login=1, password="x", server="test")
    broker._mt5 = fake
    broker._connected = True
    return broker


def test_resolve_symbol_selects_into_market_watch():
    fake = _FakeMT5()
    broker = _broker_with(fake)
    resolved = asyncio.run(broker.resolve_symbol("EURUSD"))
    assert resolved == "EURUSD"
    assert ("select", "EURUSD", True) in fake.calls


def test_resolve_symbol_selects_suffixed_broker_variant():
    fake = _FakeMT5(known={"GBPUSDm"})
    broker = _broker_with(fake)
    resolved = asyncio.run(broker.resolve_symbol("GBPUSD"))
    assert resolved == "GBPUSDm"
    assert ("select", "GBPUSDm", True) in fake.calls


def test_get_latest_bars_selects_before_copy_rates():
    """Every fetch re-selects the symbol, so no chart / manual Market Watch
    entry is ever required (and a user removing it mid-session self-heals)."""
    fake = _FakeMT5()
    broker = _broker_with(fake)
    bars = asyncio.run(broker.get_latest_bars("EURUSD", "H4", 1))
    assert len(bars) == 1

    copy_idx = fake.calls.index(("copy_rates", "EURUSD"))
    select_idxs = [i for i, c in enumerate(fake.calls) if c[0] == "select"]
    assert select_idxs and min(select_idxs) < copy_idx
