"""F007 broker wizard page rendering tests.

These pin the shape of ``BROKER_WIZARD_PAGE`` -- the multi-step form
that the user walks through to save an MT5 connection. Guardrails:

- Password field has ``type="password"`` and ``autocomplete="off"``.
- The default step is Sandbox / Demo (selected radio card).
- Live-account confirmation UI exists (checkbox + typed LIVE gate).
- The server field is a validated hint list backed by
  ``ALLOWED_SERVERS`` -- no free-text hints of a bogus URL.
- The wiz includes the F005 withStates() JS + baseline CSS + nav.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform.broker_connection import ALLOWED_SERVERS  # noqa: E402
from agent.platform.pages import (  # noqa: E402
    BROKER_WIZARD_PAGE, _BASE_CSS_VERSION,
)


class TestPasswordFieldSafety:

    def test_password_input_has_password_type(self):
        assert 'id="in-pw"' in BROKER_WIZARD_PAGE
        # Extract the input tag around id="in-pw" and check attributes.
        idx = BROKER_WIZARD_PAGE.find('id="in-pw"')
        pw_slice = BROKER_WIZARD_PAGE[max(0, idx - 200): idx + 200]
        assert 'type="password"' in pw_slice
        assert 'autocomplete="off"' in pw_slice
        assert 'spellcheck="false"' in pw_slice

    def test_password_is_never_defaulted_in_html(self):
        # The rendered HTML must not carry a `value=` for the password
        # field. Look at the region around it.
        idx = BROKER_WIZARD_PAGE.find('id="in-pw"')
        pw_slice = BROKER_WIZARD_PAGE[max(0, idx - 100): idx + 300]
        assert " value=" not in pw_slice, (
            "password field must not ship with a default value")


class TestAccountTypeDefaults:

    def test_demo_radio_selected_by_default(self):
        # Demo card must be selected; live card must not be.
        demo_marker = 'data-type="demo"'
        live_marker = 'data-type="live"'
        assert demo_marker in BROKER_WIZARD_PAGE
        assert live_marker in BROKER_WIZARD_PAGE
        # The demo card must sit inside a `wiz-radio-card selected` block
        # and the live card inside a plain `wiz-radio-card`.
        demo_idx = BROKER_WIZARD_PAGE.find(demo_marker)
        live_idx = BROKER_WIZARD_PAGE.find(live_marker)
        # Grab the full opening `<div ...>` tag around each marker so we
        # can assert on its class + aria-checked attribute.
        demo_open = BROKER_WIZARD_PAGE.rfind("<div", 0, demo_idx)
        demo_close = BROKER_WIZARD_PAGE.find(">", demo_idx)
        live_open = BROKER_WIZARD_PAGE.rfind("<div", 0, live_idx)
        live_close = BROKER_WIZARD_PAGE.find(">", live_idx)
        demo_tag = BROKER_WIZARD_PAGE[demo_open:demo_close + 1]
        live_tag = BROKER_WIZARD_PAGE[live_open:live_close + 1]
        assert "wiz-radio-card selected" in demo_tag
        assert "wiz-radio-card selected" not in live_tag
        assert 'aria-checked="true"' in demo_tag
        assert 'aria-checked="false"' in live_tag


class TestLiveConfirmationGate:

    def test_live_step_has_ack_checkbox_and_typed_confirmation(self):
        assert 'id="in-live-ack"' in BROKER_WIZARD_PAGE
        assert 'id="in-live-typed"' in BROKER_WIZARD_PAGE
        assert "Type LIVE to continue" in BROKER_WIZARD_PAGE
        # Next button must start disabled -- only unlocks when both
        # gates pass.
        idx = BROKER_WIZARD_PAGE.find('id="btn-next-live"')
        next_slice = BROKER_WIZARD_PAGE[max(0, idx - 200): idx + 200]
        assert "disabled" in next_slice

    def test_live_warning_loaded_from_api(self):
        assert "/api/broker/live-warning" in BROKER_WIZARD_PAGE
        assert "loadLiveWarning" in BROKER_WIZARD_PAGE


class TestServerFieldSafety:

    def test_server_input_backed_by_datalist(self):
        assert 'id="in-server"' in BROKER_WIZARD_PAGE
        assert 'list="server-suggestions"' in BROKER_WIZARD_PAGE
        assert 'id="server-suggestions"' in BROKER_WIZARD_PAGE

    def test_datalist_options_only_carry_allow_listed_prefixes(self):
        # Every option value must be a member of ALLOWED_SERVERS.
        # Slice out the datalist section.
        start = BROKER_WIZARD_PAGE.find('id="server-suggestions"')
        end = BROKER_WIZARD_PAGE.find("</datalist>", start)
        assert start != -1 and end != -1
        section = BROKER_WIZARD_PAGE[start:end]
        # Extract value="..." occurrences.
        import re
        values = re.findall(r'value="([^"]+)"', section)
        assert values, "no server options rendered"
        for v in values:
            assert v in ALLOWED_SERVERS, (
                f"server datalist value {v!r} not in ALLOWED_SERVERS")


class TestSharedPrimitives:

    def test_uses_withstates_and_error_copy(self):
        assert "withStates" in BROKER_WIZARD_PAGE
        # `errorCopy` is the identifier _ERROR_COPY_JS exposes to
        # withStates() call sites -- if it's missing, the shared
        # in-flight state / friendly-error render helpers are not
        # actually linked.
        assert "errorCopy" in BROKER_WIZARD_PAGE

    def test_carries_base_css_tokens(self):
        # _BASE_CSS carries the shared CSS variables + nav classes. If
        # those are missing the wizard isn't reusing the Sprint-0
        # visual system.
        assert "var(--panel)" in BROKER_WIZARD_PAGE
        assert "var(--accent)" in BROKER_WIZARD_PAGE
        assert 'class="nav"' in BROKER_WIZARD_PAGE

    def test_base_css_version_still_1_1_0(self):
        assert _BASE_CSS_VERSION == "1.1.0"


class TestApiWiring:

    def test_wizard_talks_to_the_broker_endpoints(self):
        for endpoint in (
            "/api/broker/test-connection",
            "/api/broker/save",
            "/api/broker/list",
            "/api/broker/",  # delete uses per-alias URL
        ):
            assert endpoint in BROKER_WIZARD_PAGE, (
                f"wizard does not wire to {endpoint}")


class TestMobileCare:

    def test_media_query_for_narrow_viewports(self):
        assert "@media (max-width: 700px)" in BROKER_WIZARD_PAGE
