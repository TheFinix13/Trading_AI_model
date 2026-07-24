"""E2E browser test: the /v2 pitch page actually plays a match.

Boots the real platform server on an ephemeral port over a synthetic
replay cache, drives it with headless Chromium via Playwright, and
asserts the scoreboard, ticker and league table render after playback.

Self-skipping: when playwright (requirements-dev.txt) or its Chromium
build (``python -m playwright install chromium``) is missing, the whole
module skips so VM/CI runs without the browser stack stay green.
"""
from __future__ import annotations

import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.serve_platform import make_handler  # noqa: E402

try:
    from playwright.sync_api import sync_playwright
    _PLAYWRIGHT_ERR = None
    try:
        with sync_playwright() as _p:
            _browser = _p.chromium.launch()
            _browser.close()
    except Exception as exc:  # chromium not installed / cannot launch
        _PLAYWRIGHT_ERR = f"chromium unavailable: {exc}"
except ImportError as exc:
    _PLAYWRIGHT_ERR = f"playwright not installed: {exc}"

pytestmark = pytest.mark.skipif(
    _PLAYWRIGHT_ERR is not None,
    reason=_PLAYWRIGHT_ERR or "")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                    encoding="utf-8")


@pytest.fixture()
def server(tmp_path: Path):
    reviews = tmp_path / "reviews"
    cache = reviews / "g7_replay_cache_e2e-match"
    cache.mkdir(parents=True)
    _write_jsonl(cache / "proposals_all.jsonl", [
        {"agent_id": "isagi_yoichi", "timestamp": "2024-01-01T00:00:00+00:00",
         "symbol": "EURUSD", "direction": "long", "conviction": 0.75,
         "rationale": {"signal_reason": "zone_demand"}},
        {"agent_id": "bachira_meguru",
         "timestamp": "2024-01-01T04:00:00+00:00",
         "symbol": "USDCAD", "direction": "short", "conviction": 0.8},
    ])
    _write_jsonl(cache / "proposals_rejected.jsonl", [
        {"tick_id": 1, "symbol": "GBPUSD",
         "timestamp": "2024-01-01T08:00:00+00:00",
         "winner_agent_id": "isagi_yoichi", "loser_agent_id": "barou_shoei",
         "rejection_reason": "lower_conviction_same_symbol"},
    ])
    _write_jsonl(cache / "trades.jsonl", [
        {"agent_id": "isagi_yoichi", "symbol": "EURUSD",
         "entry_time": "2024-01-01 00:00:00+00:00",
         "exit_time": "2024-01-01 12:00:00+00:00",
         "direction": "long", "exit_reason": "tp", "pnl_pips": 42.5,
         "r_multiple": 1.5, "tqs_components": {"tqs": 0.61}},
    ])
    (cache / "workspace_counts.json").write_text("{}", encoding="utf-8")

    log_root = tmp_path / "logs"
    log_root.mkdir()
    handler = make_handler(log_root, tmp_path, reviews)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_v2_page_plays_a_match(server):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(server + "/v2")

        # The match loads: clock reports the event count, pitch has the
        # full ten-striker roster drawn (Sae + Karasu joined the pitch
        # with the I002 legibility fix -- squad_events.ROSTER is the
        # source of truth).
        page.wait_for_function(
            "document.getElementById('clock').innerText.includes('ready')",
            timeout=10_000)
        assert page.locator("#pitch g[id^='pl_']").count() == 10

        # League table rendered from the summary (header + agent rows).
        assert page.locator("#league tr").count() >= 3
        assert page.locator("#league").inner_text().find("Isagi") >= 0

        # Play the whole timeline at max speed.
        page.select_option("#speed", "120")
        page.click("#play")
        page.wait_for_function(
            "document.getElementById('goals').innerText === '1'",
            timeout=15_000)

        # Scoreboard counted the winning trade; ticker filled up.
        assert page.locator("#goals").inner_text() == "1"
        assert page.locator("#ticker .tk").count() >= 4
        ticker_text = page.locator("#ticker").inner_text()
        assert "GOAL!" in ticker_text

        # Drill-down: clicking a ticker row opens the event modal.
        page.locator("#ticker .tk").first.click()
        page.wait_for_selector("#overlay.open", timeout=5_000)
        assert page.locator("#mbody").inner_text().strip() != ""
        page.click("#mclose")

        # Player profile card from the pitch.
        page.click("#pl_isagi_yoichi")
        page.wait_for_selector("#overlay.open", timeout=5_000)
        profile = page.locator("#mbody").inner_text()
        assert "Isagi" in profile
        assert "Win rate" in profile

        browser.close()
