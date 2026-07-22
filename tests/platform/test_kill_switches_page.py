"""F011 -- KILL_SWITCHES_PAGE rendering tests.

Guardrails:
- Toggle grid renders one cell per supported symbol + GLOBAL.
- Reason textarea exists and is required (checked in JS).
- Uses `withStates()` from F005.
- Carries `_BASE_CSS` tokens (visual system reuse).
- Mobile media query at 700px collapses to single column.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform.kill_switches import SUPPORTED_SYMBOLS  # noqa: E402
from agent.platform.pages import (  # noqa: E402
    KILL_SWITCHES_PAGE, _BASE_CSS_VERSION,
)


class TestGridLayout:
    def test_grid_container_present(self) -> None:
        assert 'id="ks-grid"' in KILL_SWITCHES_PAGE
        assert 'class="ks-grid"' in KILL_SWITCHES_PAGE

    def test_symbols_rendered_in_js_array(self) -> None:
        for sym in ("GLOBAL", *SUPPORTED_SYMBOLS):
            assert f'"{sym}"' in KILL_SWITCHES_PAGE, sym

    def test_activate_and_clear_buttons_present(self) -> None:
        assert 'data-act="activate"' in KILL_SWITCHES_PAGE
        assert 'data-act="clear"' in KILL_SWITCHES_PAGE


class TestReasonInput:
    def test_textarea_id_present(self) -> None:
        assert 'id="ks-reason"' in KILL_SWITCHES_PAGE

    def test_reason_required_on_activate(self) -> None:
        # The JS refuses to POST an activate if the reason is empty.
        assert "Reason is required" in KILL_SWITCHES_PAGE


class TestSharedPrimitives:
    def test_uses_withstates(self) -> None:
        assert "withStates" in KILL_SWITCHES_PAGE

    def test_carries_base_css_tokens(self) -> None:
        assert "var(--panel)" in KILL_SWITCHES_PAGE
        assert "var(--accent)" in KILL_SWITCHES_PAGE
        assert 'class="nav"' in KILL_SWITCHES_PAGE

    def test_base_css_version_pinned(self) -> None:
        assert _BASE_CSS_VERSION == "1.0.0"


class TestApiWiring:
    def test_page_talks_to_kill_switches_endpoints(self) -> None:
        for endpoint in (
            "/api/kill-switches/status",
            "/api/kill-switches/activate",
            "/api/kill-switches/clear",
        ):
            assert endpoint in KILL_SWITCHES_PAGE, endpoint


class TestMobileCare:
    def test_media_query_for_narrow_viewports(self) -> None:
        # There are two `@media (max-width: 700px)` blocks in the page:
        # the _BASE_CSS one (nav collapsing) and the F011-specific one
        # (grid collapse). The KILL_SWITCHES_PAGE-owned block is the
        # LAST occurrence -- pin the grid-collapse rule inside it.
        assert "@media (max-width: 700px)" in KILL_SWITCHES_PAGE
        m_idx = KILL_SWITCHES_PAGE.rfind("@media (max-width: 700px)")
        assert "grid-template-columns:1fr" in KILL_SWITCHES_PAGE[m_idx:m_idx + 400]


class TestAuditPanel:
    def test_audit_container_present(self) -> None:
        assert 'id="ks-audit"' in KILL_SWITCHES_PAGE
        assert "Recent events" in KILL_SWITCHES_PAGE
