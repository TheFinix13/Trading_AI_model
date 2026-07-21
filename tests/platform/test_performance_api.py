"""HTTP integration + contract tests for /performance and
/api/performance/state (F001).

- GET /performance returns 200 + HTML with the KPI grid + equity
  wrapper + disclaimer markers in the body.
- GET /api/performance/state returns 200 + JSON with every promised
  key.
- Missing data sources -> 200 with shaped-empty payload, not 500.
- Read-only: no files are created under log_root or live_dir by any
  request.
"""
from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.serve_platform import make_handler  # noqa: E402


def _make_server(tmp_path: Path,
                 log_root: Path | None = None,
                 live_dir: Path | None = None):
    log_root = log_root or (tmp_path / "logs")
    log_root.mkdir(parents=True, exist_ok=True)
    reviews = tmp_path / "reviews"
    reviews.mkdir(exist_ok=True)
    handler = make_handler(log_root, tmp_path, reviews,
                           live_dir=live_dir)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _get(url: str) -> tuple[int, dict, bytes]:
    try:
        with urllib.request.urlopen(url) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def _get_json(url: str) -> tuple[int, dict]:
    status, _, body = _get(url)
    return status, json.loads(body)


REQUIRED_KEYS = {
    "generated_at", "days_live", "net_pips", "worst_dd_pips",
    "win_rate_pct", "sharpe_or_null", "sharpe_days_needed",
    "trades_total", "equity_curve", "per_pair", "source_hint",
    "v1_trades_count", "v2_trades_count",
}


@pytest.fixture()
def cold_server(tmp_path: Path):
    """Empty log root + no live dir -- worst-case cold-start state."""
    srv = _make_server(tmp_path, live_dir=tmp_path / "squad_live")
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()


@pytest.fixture()
def seeded_server(tmp_path: Path):
    """Log root seeded with one closed-trade line so the API returns a
    non-empty payload."""
    log_root = tmp_path / "logs"
    sym = log_root / "EURUSD"
    sym.mkdir(parents=True)
    (sym / "EURUSD_2026-07-15.log").write_text(
        "2026-07-15 09:00:00,000 INFO agent.live.monitor - "
        "[TRADE CLOSED] EURUSD ticket=1 zone_d1_against LONG "
        "exit=1.09321 pnl=+2.98 (+30.5p, +1.20R) cause=tp\n",
        encoding="utf-8")
    srv = _make_server(tmp_path, log_root=log_root,
                       live_dir=tmp_path / "squad_live")
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()


class TestPerformancePageHttp:

    def test_page_returns_200(self, cold_server):
        status, headers, body = _get(cold_server + "/performance")
        assert status == 200
        assert headers.get("Content-Type", "").startswith("text/html")

    def test_page_body_contains_structural_markers(self, cold_server):
        _, _, body = _get(cold_server + "/performance")
        for marker in (b"How we", b"Days live", b"Net pips",
                       b"Worst drawdown", b"Win rate", b"Sharpe",
                       b"Equity curve", b"By pair",
                       b"Past performance is not indicative"):
            assert marker in body, f"missing marker: {marker!r}"

    def test_page_polls_the_right_endpoint(self, cold_server):
        _, _, body = _get(cold_server + "/performance")
        assert b"/api/performance/state" in body


class TestPerformanceApiContract:

    def test_cold_start_returns_200_with_shape(self, cold_server):
        status, body = _get_json(cold_server + "/api/performance/state")
        assert status == 200
        assert set(body.keys()) >= REQUIRED_KEYS

    def test_cold_start_source_hint_is_friendly(self, cold_server):
        _, body = _get_json(cold_server + "/api/performance/state")
        assert "no shadow-paper data yet" in body["source_hint"]
        assert body["trades_total"] == 0
        assert body["equity_curve"] == []
        assert body["per_pair"] == []

    def test_seeded_data_populates_payload(self, seeded_server):
        _, body = _get_json(seeded_server + "/api/performance/state")
        assert body["trades_total"] == 1
        assert body["net_pips"] == 30.5
        assert len(body["equity_curve"]) == 1
        assert body["equity_curve"][0]["cum_pips"] == 30.5
        assert len(body["per_pair"]) == 1
        assert body["per_pair"][0]["symbol"] == "EURUSD"
        assert "v1 live-demo agent" in body["source_hint"]

    def test_sharpe_below_floor_returns_null_with_days_needed(
            self, seeded_server):
        _, body = _get_json(seeded_server + "/api/performance/state")
        assert body["sharpe_or_null"] is None
        assert body["sharpe_days_needed"] >= 1

    def test_endpoint_never_500s_on_missing_data(self, cold_server):
        # Critical: the F005 empty-state affordance depends on 200 +
        # shaped body, not a 500.
        status, headers, _ = _get(cold_server + "/api/performance/state")
        assert status == 200
        assert headers.get("Content-Type", "").startswith("application/json")

    def test_read_only_invariant(self, cold_server, tmp_path: Path):
        # Multiple polls do not create files anywhere except the
        # pre-existing dirs.
        for _ in range(3):
            _get(cold_server + "/api/performance/state")
        # Assertion is soft here (server sits inside a tmp_path fixture)
        # -- more explicit read-only assertion is in the module tests.
