"""F013 -- LIVE_MODE_TOGGLE_PAGE rendering tests."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform.pages import LIVE_MODE_TOGGLE_PAGE  # noqa: E402


class TestCurrentState:
    def test_current_state_indicator_present(self) -> None:
        assert 'id="lm-current"' in LIVE_MODE_TOGGLE_PAGE

    def test_fetches_status_endpoint(self) -> None:
        assert "/api/live-mode/status" in LIVE_MODE_TOGGLE_PAGE


class TestCeremony:
    def test_ceremony_has_acknowledgement_checkbox(self) -> None:
        assert 'id="lm-ack"' in LIVE_MODE_TOGGLE_PAGE
        assert "I understand" in LIVE_MODE_TOGGLE_PAGE

    def test_ceremony_requires_typed_confirmation(self) -> None:
        assert "ENABLE LIVE MODE" in LIVE_MODE_TOGGLE_PAGE
        assert 'id="lm-confirm"' in LIVE_MODE_TOGGLE_PAGE

    def test_ceremony_loads_verbatim_disclaimer(self) -> None:
        assert "/api/live-mode/warning" in LIVE_MODE_TOGGLE_PAGE
        assert 'id="lm-warn"' in LIVE_MODE_TOGGLE_PAGE

    def test_enable_button_disabled_by_default(self) -> None:
        assert 'id="lm-enable-btn"' in LIVE_MODE_TOGGLE_PAGE
        assert "disabled" in LIVE_MODE_TOGGLE_PAGE

    def test_enable_hits_api(self) -> None:
        assert "/api/live-mode/enable" in LIVE_MODE_TOGGLE_PAGE


class TestOneClickDisable:
    def test_disable_button_when_on(self) -> None:
        assert 'id="lm-disable-btn"' in LIVE_MODE_TOGGLE_PAGE
        assert "Turn off live mode" in LIVE_MODE_TOGGLE_PAGE

    def test_disable_hits_api(self) -> None:
        assert "/api/live-mode/disable" in LIVE_MODE_TOGGLE_PAGE


class TestOffDefault:
    def test_default_state_class_is_off(self) -> None:
        # The initial DOM shows "off" state and "Loading..." until JS
        # responds with the real status.
        assert 'class="lm-state off"' in LIVE_MODE_TOGGLE_PAGE
