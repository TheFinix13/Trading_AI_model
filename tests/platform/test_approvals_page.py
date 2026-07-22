"""F013 -- APPROVALS_PAGE rendering tests."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform.pages import APPROVALS_PAGE  # noqa: E402


class TestSections:
    def test_pending_section_present(self) -> None:
        assert 'id="pending-body"' in APPROVALS_PAGE
        assert "Pending" in APPROVALS_PAGE

    def test_recent_section_present(self) -> None:
        assert 'id="recent-body"' in APPROVALS_PAGE
        assert "Recent" in APPROVALS_PAGE

    def test_warning_box_present(self) -> None:
        assert 'id="warn-body"' in APPROVALS_PAGE
        assert "/api/approvals/warning" in APPROVALS_PAGE


class TestActions:
    def test_approve_reject_buttons(self) -> None:
        assert "approve" in APPROVALS_PAGE
        assert "reject" in APPROVALS_PAGE
        assert "/api/approvals/" in APPROVALS_PAGE

    def test_countdown_ticker_present(self) -> None:
        assert 'class="countdown"' in APPROVALS_PAGE
        assert "tickCountdowns" in APPROVALS_PAGE


class TestSharedPrimitives:
    def test_uses_withstates(self) -> None:
        assert "withStates" in APPROVALS_PAGE

    def test_polls_pending_every_3s(self) -> None:
        assert "setInterval(refresh, 3000)" in APPROVALS_PAGE

    def test_reason_input_present(self) -> None:
        assert "reject-reason" in APPROVALS_PAGE


class TestMobile:
    def test_mobile_media_query_collapses_grid(self) -> None:
        assert "@media (max-width: 700px)" in APPROVALS_PAGE
        idx = APPROVALS_PAGE.rfind("@media (max-width: 700px)")
        assert "grid-template-columns:1fr" in APPROVALS_PAGE[idx:idx + 500]
