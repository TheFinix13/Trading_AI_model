"""F014 -- ALERTS_PAGE rendering tests (spec asked 2)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform.pages import ALERTS_PAGE  # noqa: E402


class TestChips:
    def test_filter_chips_present(self) -> None:
        assert 'id="alerts-chips"' in ALERTS_PAGE
        # All six event types render as chips.
        for t in ("trade_fill", "stop_hit", "kill_switch_trip",
                  "risk_budget_breach", "approval_submitted",
                  "platform_down"):
            assert f'"{t}"' in ALERTS_PAGE or f"'{t}'" in ALERTS_PAGE


class TestTestButton:
    def test_test_button_present_and_hits_api(self) -> None:
        assert 'id="alerts-test-btn"' in ALERTS_PAGE
        assert "/api/alerts/test" in ALERTS_PAGE


class TestConnection:
    def test_connects_event_source(self) -> None:
        assert "new EventSource(" in ALERTS_PAGE
        assert "/api/alerts/stream" in ALERTS_PAGE

    def test_reconnect_backoff_is_bounded(self) -> None:
        # F023: on error (incl. a 429 refusal at the stream cap) the
        # page closes the source and retries itself with exponential
        # backoff capped at RECONNECT_MAX_MS -- never the browser's
        # tight default loop.
        assert "RECONNECT_MAX_MS" in ALERTS_PAGE
        assert "es.close()" in ALERTS_PAGE
        assert "setTimeout(openStream, reconnectDelay)" in ALERTS_PAGE
        assert "Math.min(reconnectDelay * 2, RECONNECT_MAX_MS)" \
            in ALERTS_PAGE


class TestMobile:
    def test_mobile_media_query(self) -> None:
        assert "@media (max-width: 700px)" in ALERTS_PAGE

    def test_actions_stack_on_mobile(self) -> None:
        idx = ALERTS_PAGE.rfind("@media (max-width: 700px)")
        assert "flex-direction:column" in ALERTS_PAGE[idx:idx + 500]


class TestSharedPrimitives:
    def test_uses_withstates(self) -> None:
        assert "withStates" in ALERTS_PAGE
