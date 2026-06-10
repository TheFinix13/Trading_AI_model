"""Live wiring contract: run_live's default path must trade the validated
zone routing table, on the routed timeframe, at the routed risk_scale —
and refuse to start for symbols the router never deployed.

No real broker connections: the SignalLoop test injects a fake broker and
stubs the risk-manager verdict so only the sizing seam is exercised.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from agent.alphas.base import AlphaSignal
from agent.alphas.concepts.zone_alpha import SupplyDemandAlpha
from agent.config import load_config
from agent.live.config import LiveConfig
from agent.live.position_sizer import SizingResult
from agent.live.router_wiring import (
    LiveRoute,
    UndeployedSymbolError,
    build_live_routes,
)
from agent.live.signal_loop import SignalLoop, _RoutedSignal
from agent.risk.manager import RiskDecision
from agent.types import Direction


# ----------------------------------------------------------------------
# Alpha construction from the router
# ----------------------------------------------------------------------

def test_eurusd_builds_one_validated_htf_against_alpha():
    routes = build_live_routes("EURUSD", load_config())
    assert len(routes) == 1
    r = routes[0]
    assert isinstance(r, LiveRoute)
    assert (r.symbol, r.timeframe, r.session) == ("EURUSD", "H4", "all")
    assert r.mode == "htf_against"
    assert r.risk_scale == 1.0

    alpha = r.alpha
    assert isinstance(alpha, SupplyDemandAlpha)
    # Locked htf_against parameter set — drift invalidates the OOS claim.
    assert alpha.htf_align == "D1"
    assert alpha.htf_align_mode == "against"
    assert alpha.htf_lookback == 10
    assert alpha.htf_min_move_pips == 60.0


def test_gbpusd_routes_at_half_risk():
    routes = build_live_routes("GBPUSD", load_config())
    assert len(routes) == 1
    r = routes[0]
    assert (r.timeframe, r.session) == ("H4", "all")
    assert r.risk_scale == 0.5
    assert isinstance(r.alpha, SupplyDemandAlpha)
    assert r.alpha.htf_align_mode == "against"


def test_usdcad_routes_at_half_risk():
    routes = build_live_routes("USDCAD", load_config())
    assert len(routes) == 1
    assert routes[0].risk_scale == 0.5


@pytest.mark.parametrize("symbol", ["USDJPY", "AUDUSD", "XAUUSD", ""])
def test_undeployed_symbol_refuses_to_build(symbol: str):
    with pytest.raises(UndeployedSymbolError):
        build_live_routes(symbol, load_config())


def test_route_alpha_names_are_distinct_sizing_keys():
    """SignalLoop.risk_scales is keyed by alpha name, so every route for a
    symbol must carry a distinct name."""
    for symbol in ("EURUSD", "GBPUSD", "USDCAD"):
        routes = build_live_routes(symbol, load_config())
        names = [r.alpha.name for r in routes]
        assert len(names) == len(set(names))


# ----------------------------------------------------------------------
# risk_scale flows into the live sizing computation
# ----------------------------------------------------------------------

class _FakeBroker:
    """Minimal async stub — never touches MT5 / network."""

    async def get_account_info(self):
        return SimpleNamespace(balance=10_000.0, leverage=500,
                               free_margin=10_000.0)

    async def get_open_positions(self, symbol):
        return []

    async def connect(self):  # pragma: no cover - not exercised
        return True

    async def disconnect(self):  # pragma: no cover - not exercised
        return None


def _captured_risk_pct(risk_scales: dict[str, float], alpha_name: str) -> float:
    """Drive SignalLoop._route_signal to the sizing call with a fake broker
    and return the risk_pct the sizer was asked to use."""
    cfg = load_config()
    live = LiveConfig(symbol="EURUSD", timeframes=["H4"],
                      telegram_enabled=False, revenge_guard_enabled=False)
    loop = SignalLoop(
        [SupplyDemandAlpha(cfg, name=alpha_name)],
        config=cfg, live_config=live, broker=_FakeBroker(),
        risk_scales=risk_scales,
    )

    # Approve unconditionally so the test isn't coupled to kill-switch files
    # or daily-DD state; only the sizing seam is under test.
    loop.risk_manager.evaluate = lambda **kw: SimpleNamespace(
        decision=RiskDecision.APPROVED, reason="")

    captured: dict[str, float] = {}

    def fake_calculate_lot(balance, stop_distance_pips, *, risk_pct=None, **kw):
        captured["risk_pct"] = risk_pct
        # lot=0 short-circuits _route_signal before any order placement.
        return SizingResult(
            lot=0.0, risk_pct=risk_pct, risk_amount=0.0,
            stop_distance_pips=stop_distance_pips, balance=balance,
            conviction=kw.get("conviction", 0.0), margin_required=0.0,
            free_margin=balance,
        )

    loop.position_sizer.calculate_lot = fake_calculate_lot

    signal = AlphaSignal(direction=Direction.LONG, entry=1.1000,
                         stop=1.0950, take_profit=1.1100, conviction=0.8)
    last_closed = SimpleNamespace(time=datetime(2026, 6, 10, tzinfo=timezone.utc))
    routed = _RoutedSignal(loop.alphas[0], signal, "H4")

    asyncio.run(loop._route_signal(routed, last_closed))
    assert "risk_pct" in captured, "sizing was never reached"
    return captured["risk_pct"]


def test_risk_scale_multiplies_live_sizing():
    full = _captured_risk_pct({"zone_h4_all": 1.0}, "zone_h4_all")
    half = _captured_risk_pct({"zone_h4_all": 0.5}, "zone_h4_all")
    assert full > 0
    assert half == pytest.approx(full * 0.5)


def test_unlisted_alpha_defaults_to_unit_scale():
    base = _captured_risk_pct({}, "zone_h4_all")
    explicit = _captured_risk_pct({"zone_h4_all": 1.0}, "zone_h4_all")
    assert base == pytest.approx(explicit)
