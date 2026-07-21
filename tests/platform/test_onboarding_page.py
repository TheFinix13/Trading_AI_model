"""F008 -- ONBOARDING_PAGE + RESET_INSTALL_PAGE rendering smoke tests.

Pins the shape of the onboarding wizard HTML:

- Five explicit steps (welcome / passphrase / broker / pairs / confirm).
- Legal agreement text visible on the welcome step verbatim.
- Passphrase input carries type=password + autocomplete=new-password.
- Default pairs section has EURUSD pre-checked; GBPUSD + USDCAD present.
- Mobile media query present.
- Talks to the /api/onboarding/* endpoints.

Also pins the reset-install page:

- Warning is amber, mentions "cannot be undone".
- Reset button triggers POST /api/onboarding/reset.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform.pages import (  # noqa: E402
    ONBOARDING_PAGE, RESET_INSTALL_PAGE, _BASE_CSS_VERSION,
)


class TestStepsPresent:

    def test_five_step_ids(self):
        for step in ("welcome", "passphrase", "broker", "pairs", "confirm"):
            assert f'id="step-{step}"' in ONBOARDING_PAGE, (
                f"missing step id: {step}")

    def test_stepper_progressbar_labelled(self):
        assert 'role="progressbar"' in ONBOARDING_PAGE
        for label in ("1. Welcome", "2. Passphrase", "3. Broker",
                      "4. Pairs", "5. Confirm"):
            assert label in ONBOARDING_PAGE, f"missing stepper label: {label}"


class TestLegalAgreement:

    def test_agreement_text_verbatim(self):
        # The welcome step must carry the Legal agreement paragraph.
        # The HTML wraps whitespace so we normalise before checking.
        compact = " ".join(ONBOARDING_PAGE.lower().split())
        assert "not a regulated broker" in compact
        assert "not financial advice" in compact or \
               "nothing this platform outputs is financial advice" in compact

    def test_by_continuing_frame(self):
        assert "By continuing you agree" in ONBOARDING_PAGE


class TestPassphraseInput:

    def test_password_input_shape(self):
        idx = ONBOARDING_PAGE.find('id="in-passphrase"')
        assert idx != -1
        slc = ONBOARDING_PAGE[max(0, idx - 200): idx + 300]
        assert 'type="password"' in slc
        assert 'autocomplete="new-password"' in slc
        assert 'spellcheck="false"' in slc

    def test_password_never_ships_with_value_attribute(self):
        idx = ONBOARDING_PAGE.find('id="in-passphrase"')
        slc = ONBOARDING_PAGE[max(0, idx - 200): idx + 300]
        assert " value=" not in slc

    def test_skip_checkbox_present(self):
        assert 'id="in-noop-passphrase"' in ONBOARDING_PAGE
        assert "keychain is available" in ONBOARDING_PAGE


class TestPairsStep:

    def test_default_pair_precheck(self):
        idx = ONBOARDING_PAGE.find('id="pair-EURUSD"')
        assert idx != -1
        slc = ONBOARDING_PAGE[max(0, idx - 100): idx + 100]
        assert "checked" in slc

    def test_gbpusd_and_usdcad_present_but_not_checked(self):
        for pair in ("GBPUSD", "USDCAD"):
            idx = ONBOARDING_PAGE.find(f'id="pair-{pair}"')
            assert idx != -1
            slc = ONBOARDING_PAGE[max(0, idx - 50): idx + 50]
            assert "checked" not in slc


class TestApiWiring:

    def test_talks_to_state_endpoint(self):
        assert "/api/onboarding/state" in ONBOARDING_PAGE

    def test_talks_to_passphrase_endpoint(self):
        assert "/api/onboarding/passphrase" in ONBOARDING_PAGE

    def test_talks_to_pairs_endpoint(self):
        assert "/api/onboarding/pairs" in ONBOARDING_PAGE

    def test_talks_to_complete_endpoint(self):
        assert "/api/onboarding/complete" in ONBOARDING_PAGE

    def test_broker_step_links_to_wizard(self):
        assert 'href="/settings/broker"' in ONBOARDING_PAGE


class TestSharedPrimitives:

    def test_uses_withstates_and_error_copy(self):
        assert "withStates" in ONBOARDING_PAGE
        assert "errorCopy" in ONBOARDING_PAGE

    def test_carries_base_css_tokens(self):
        assert "var(--panel)" in ONBOARDING_PAGE
        assert "var(--accent)" in ONBOARDING_PAGE

    def test_base_css_version_stays_1_0_0(self):
        assert _BASE_CSS_VERSION == "1.0.0"


class TestMobileCare:

    def test_media_query_for_narrow_viewports(self):
        assert "@media (max-width: 700px)" in ONBOARDING_PAGE


# ---------------------------------------------------------------------------
# RESET_INSTALL_PAGE
# ---------------------------------------------------------------------------

class TestResetInstallPage:

    def test_reset_page_warning_present(self):
        assert "cannot be undone" in RESET_INSTALL_PAGE.lower()
        assert "Warning" in RESET_INSTALL_PAGE

    def test_reset_page_talks_to_reset_endpoint(self):
        assert "/api/onboarding/reset" in RESET_INSTALL_PAGE

    def test_reset_page_carries_nav(self):
        assert 'class="nav"' in RESET_INSTALL_PAGE

    def test_reset_page_cancel_link(self):
        assert 'href="/"' in RESET_INSTALL_PAGE
