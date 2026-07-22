"""F012 -- RISK_PAGE rendering tests.

Guardrails:
- Three sections rendered (Live exposure, Budget headroom, Broker connections).
- Consumes withStates() + carries base CSS + nav.
- Mobile media query at 700px collapses grid to `1fr`.
- Explicit Sprint 2 disclaimer visible.
- Polls /api/risk/state every 30 s.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform.pages import RISK_PAGE, _BASE_CSS_VERSION  # noqa: E402


class TestSections:
    def test_live_exposure_section(self) -> None:
        assert "Live exposure" in RISK_PAGE
        assert 'id="risk-live-body"' in RISK_PAGE

    def test_budget_headroom_section(self) -> None:
        assert "Budget headroom" in RISK_PAGE
        assert 'id="risk-budget-body"' in RISK_PAGE

    def test_broker_connections_section(self) -> None:
        assert "Broker connections" in RISK_PAGE
        assert 'id="risk-brokers-body"' in RISK_PAGE


class TestSharedPrimitives:
    def test_uses_withstates(self) -> None:
        assert "withStates" in RISK_PAGE

    def test_carries_base_css_and_nav(self) -> None:
        assert "var(--panel)" in RISK_PAGE
        assert "var(--accent)" in RISK_PAGE
        assert 'class="nav"' in RISK_PAGE

    def test_base_css_version_pinned(self) -> None:
        assert _BASE_CSS_VERSION == "1.0.0"


class TestApiWiring:
    def test_polls_risk_state(self) -> None:
        assert "/api/risk/state" in RISK_PAGE

    def test_thirty_second_refresh_interval(self) -> None:
        assert "setInterval(refresh, 30000)" in RISK_PAGE


class TestMobileCare:
    def test_media_query_collapses_grid(self) -> None:
        # Two @media blocks total (one in _BASE_CSS, one in F012). The
        # RISK_PAGE-owned rule is the LAST occurrence -- pin the grid
        # collapse inside it.
        assert "@media (max-width: 700px)" in RISK_PAGE
        idx = RISK_PAGE.rfind("@media (max-width: 700px)")
        assert "grid-template-columns:1fr" in RISK_PAGE[idx:idx + 500]


class TestSprint2Disclaimer:
    def test_sprint_2_caveat_visible(self) -> None:
        assert "Sprint 2 caveat" in RISK_PAGE
        assert "Live-mode is" in RISK_PAGE
        assert "OFF" in RISK_PAGE
