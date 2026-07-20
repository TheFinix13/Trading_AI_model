"""Fix 3 HTTP integration — /v1 renders parsed excursion pills.

The complaint that triggered this fix: on the /v1 USDCAD card the
``excursion`` field was rendered as ``JSON.stringify(excursion)``,
overflowing the card visually. The fix parses the dict client-side
into readable pills (MAE / MFE / Last / Profit / Stop / TP).

These tests hit the actual HTTP surface:

1. ``GET /api/v1/status`` returns the raw excursion dict inside
   ``symbols[i].positions[j].excursion`` (unchanged wire contract).
2. ``GET /v1`` serves the JS that parses that dict via
   ``excursionPills`` — the raw ``JSON.stringify(p.excursion)`` sink
   is gone.
3. The card body has the ``word-break: break-word`` /
   ``overflow-wrap: anywhere`` safety net so any future stray value
   still can't overflow.
"""
from __future__ import annotations

import json
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.serve_platform import make_handler  # noqa: E402


def _get(url: str) -> tuple[int, dict, bytes]:
    with urllib.request.urlopen(url) as resp:
        return resp.status, dict(resp.headers), resp.read()


@pytest.fixture()
def log_root_with_excursion(tmp_path: Path) -> Path:
    """A live log root where the symbol dir carries a realistic
    excursion payload -- the exact shape agent/live/monitor.py writes."""
    root = tmp_path / "logs"
    sym = root / "USDCAD"
    sym.mkdir(parents=True)
    (sym / "state.json").write_text(json.dumps({
        "saved_at": "2026-07-21T00:04:00+00:00",
        "position_monitor": {
            "entry_ctx": {
                "12345": {
                    "direction": "long",
                    "entry": 1.39522,
                    "sl": 1.39522,
                    "tp": 1.40851,
                    "lot_size": 0.01,
                    "timeframe": "H4",
                    "alpha": "zone_d1_against",
                    "opened_at": "2026-07-20T20:00:00+00:00",
                },
            },
            "excursion": {
                "12345": {
                    "mae_pips": 8.0,
                    "mfe_pips": 34.7,
                    "last_price": 1.40714,
                    "last_profit": 4.93,
                    "open_price": 1.39522,
                    "direction": "long",
                    "broker_stop": 1.39522,
                    "broker_tp": 1.40851,
                },
            },
        },
        "risk_manager": {"day_pnl": 4.93, "halted_today": False},
        "post_loss_guard": {"consecutive_losses": 0},
    }), encoding="utf-8")
    return root


@pytest.fixture()
def server(tmp_path: Path, log_root_with_excursion: Path):
    reviews = tmp_path / "reviews"
    reviews.mkdir()
    live_dir = tmp_path / "squad_live"
    handler = make_handler(
        log_root_with_excursion, tmp_path, reviews, live_dir=live_dir,
    )
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()


def test_api_v1_status_returns_excursion_dict(server):
    status, _, body = _get(server + "/api/v1/status")
    assert status == 200
    payload = json.loads(body)
    syms = payload["symbols"]
    assert len(syms) == 1
    pos = syms[0]["positions"]
    assert pos[0]["excursion"]["mae_pips"] == 8.0
    assert pos[0]["excursion"]["mfe_pips"] == 34.7
    # Wire contract is unchanged: the field is a dict, not a string.
    assert isinstance(pos[0]["excursion"], dict)


def test_v1_page_serves_html_with_excursion_helpers(server):
    status, headers, body = _get(server + "/v1")
    assert status == 200
    assert headers.get("Content-Type", "").startswith("text/html")
    html = body.decode("utf-8")
    # The pill helper + labels ship, the raw-stringify path is gone.
    assert "excursionPills" in html
    assert "JSON.stringify(p.excursion)" not in html
    for label in ("MAE", "MFE", "Last", "Profit", "Stop", "TP"):
        assert label in html, f"missing pill label: {label!r}"
    # Overflow safety net.
    assert "word-break:break-word" in html
    assert "overflow-wrap:anywhere" in html
    # Direction chip -- long/short styling for the ticker's LONG /
    # SHORT badge on the /v1 card.
    assert "dir-chip" in html
