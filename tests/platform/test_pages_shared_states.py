"""Tests for the F005 shared `withStates()` helper + brand copy library.

The helper lives in `agent/platform/pages.py` as three constants
(`_SKELETON_CSS`, `_ERROR_COPY_JS`, `_WITH_STATES_JS`) that get
injected into every consuming page. Direct JS execution is out of
scope here, but we can pin the contract by asserting the constants
contain the expected shape.

Three groups:

1. **Skeleton CSS** — animation keyframes, `.sk` base class,
   variant classes (`sk-tile`, `sk-chart`, `sk-row`).
2. **Error copy library** — every key defined in
   `company/brand/error_copy.md` shows up in the JS constant so a
   copy tweak in the doc without a code change is caught.
3. **`withStates()` API** — the helper takes (box, fetcher, renderer,
   opts), branches on unconfigured / auth / http-code / json-parse,
   and offers a retry button with the "Try again" label.

Plus a smoke test that the copy files exist on disk with the right
top-level sections, so a rename doesn't silently break the review
chain.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform import pages  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[2]


class TestBaseCssVersion:
    """Sprint 1 D047 §5.5 -- `_BASE_CSS_VERSION` is pinned here so
    an unversioned edit to `_BASE_CSS` fails the suite."""

    def test_version_constant_present(self):
        assert hasattr(pages, "_BASE_CSS_VERSION"), (
            "agent/platform/pages.py must expose _BASE_CSS_VERSION")

    def test_version_is_semver_string(self):
        v = pages._BASE_CSS_VERSION
        assert isinstance(v, str) and v.count(".") == 2, (
            f"_BASE_CSS_VERSION must be semver X.Y.Z, got {v!r}")
        for part in v.split("."):
            assert part.isdigit(), f"non-numeric semver part in {v!r}"

    def test_version_pinned_to_current(self):
        assert pages._BASE_CSS_VERSION == "1.1.0", (
            "bumping _BASE_CSS_VERSION requires updating this pin (per "
            "review-chain §5.5); layout/typography/class-name break = "
            "major, additive token = minor, patch = a11y/typo")


class TestSkeletonCss:

    def test_shimmer_keyframes_defined(self):
        assert "@keyframes shimmer" in pages._SKELETON_CSS

    def test_base_and_variant_classes_present(self):
        css = pages._SKELETON_CSS
        for cls in (".sk ", ".sk-line", ".sk-tile", ".sk-chart",
                    ".sk-row", ".sk-error", ".sk-empty"):
            assert cls in css, f"missing skeleton class: {cls!r}"

    def test_retry_button_styled(self):
        assert ".retry" in pages._SKELETON_CSS

    def test_no_new_palette_tokens_introduced(self):
        # F005 spec: skeleton uses only --panel + a slightly lighter
        # shade; no new colours. Sanity check the CSS references the
        # existing tokens.
        for tok in ("var(--panel)", "var(--border)", "var(--fg)",
                    "var(--dim)"):
            assert tok in pages._SKELETON_CSS, (
                f"missing shared token: {tok!r}")


class TestErrorCopyLibrary:

    def test_every_canonical_key_declared(self):
        # These keys are the contract with company/brand/error_copy.md.
        expected = {
            "server_restarting", "temporary_glitch", "unauthorized",
            "not_configured", "no_data_yet", "unknown_route",
            "api_not_found", "stale_data",
        }
        for key in expected:
            assert f'"{key}"' in pages._ERROR_COPY_JS, (
                f"missing canonical copy key: {key!r}")

    def test_default_map_covers_common_outcomes(self):
        js = pages._ERROR_COPY_JS
        for fetch_kind in ("network", "http_5xx", "http_401",
                           "http_404", "json_parse", "unconfigured"):
            assert f'"{fetch_kind}"' in js, (
                f"missing outcome key in default map: {fetch_kind!r}")

    def test_no_banned_phrases_leak(self):
        # Never expose raw JS values or stack-tracey text; F005 spec's
        # "what NOT to say" list.
        for banned in ("Error 500", "undefined", "null", "NaN",
                       "Failed to fetch", "Please contact support"):
            assert banned not in pages._ERROR_COPY_JS, (
                f"banned phrase leaked into copy library: {banned!r}")


class TestWithStatesApi:

    def test_function_signature_present(self):
        assert "async function withStates(box, fetcher, renderer, opts)" \
            in pages._WITH_STATES_JS

    def test_branches_on_outcome_kinds(self):
        js = pages._WITH_STATES_JS
        # The helper reads classifyFetchOutcome() -> one of the six
        # DEFAULT_ERROR_MAP keys; the branches are baked into the
        # classifier + the map lookup.
        for hook in ("classifyFetchOutcome",
                     "renderErrorState", "renderEmptyState"):
            assert hook in js, f"missing helper: {hook!r}"

    def test_retry_button_label_is_try_again(self):
        # Brand rule: "Try again", not "Retry". Regression-catch.
        assert '"Try again"' in pages._WITH_STATES_JS

    def test_unconfigured_payload_routes_to_error_state(self):
        # Meta.unconfigured -- coming from any backend module's
        # graceful-degradation path -- gets its own copy key.
        assert "meta.unconfigured" in pages._WITH_STATES_JS

    def test_empty_return_swaps_to_empty_state(self):
        # If the caller's renderer returns "empty", we swap to the
        # empty-state affordance. This is the contract F001/F002/F003
        # rely on to keep empty-state copy per-surface.
        assert '=== "empty"' in pages._WITH_STATES_JS or \
               "verdict === \"empty\"" in pages._WITH_STATES_JS

    def test_skeleton_default_html_helper_present(self):
        # A generic default skeleton so pages that don't need custom
        # sizing get sane placeholders "for free".
        assert "function skeletonHtml" in pages._WITH_STATES_JS


class TestBrandCopyOnDisk:

    def test_error_copy_file_present_with_canonical_keys(self):
        path = REPO_ROOT / "company" / "brand" / "error_copy.md"
        assert path.is_file(), (
            "company/brand/error_copy.md missing -- F005 deliverable")
        text = path.read_text(encoding="utf-8")
        for section in ("server_restarting", "temporary_glitch",
                        "unauthorized", "no_data_yet",
                        "api_not_found"):
            assert section in text, (
                f"error_copy.md missing section: {section!r}")

    def test_copy_md_present_with_page_headings(self):
        path = REPO_ROOT / "company" / "brand" / "copy.md"
        assert path.is_file(), (
            "company/brand/copy.md missing -- D008 deliverable")
        text = path.read_text(encoding="utf-8")
        for section in ("/performance", "/players", "/research"):
            assert section in text, (
                f"copy.md missing section: {section!r}")


class TestNavExtension:

    def test_nav_pills_include_new_routes(self):
        n = pages.nav("performance")
        for href in ('href="/"', 'href="/v1"', 'href="/v2"',
                     'href="/hq"', 'href="/performance"',
                     'href="/players"', 'href="/research"'):
            assert href in n, f"missing nav pill: {href!r}"

    def test_active_pill_marked_here(self):
        assert 'href="/performance" class="here"' in pages.nav("performance")
        assert 'href="/players" class="here"' in pages.nav("players")
        assert 'href="/research" class="here"' in pages.nav("research")

    def test_hub_active_still_works(self):
        # Regression: existing HQ / v1 / v2 / hub `.here` targets
        # keep the same behaviour after the pill extension.
        assert 'href="/" class="here"' in pages.nav("hub")
        assert 'href="/v1" class="here"' in pages.nav("v1")
        assert 'href="/v2" class="here"' in pages.nav("v2")
        assert 'href="/hq" class="here"' in pages.nav("hq")

    def test_unknown_active_renders_with_no_here(self):
        # Silent-safe default: garbage arg doesn't crash; renders all
        # seven pills without a .here marker.
        n = pages.nav("nonexistent")
        assert 'class="here"' not in n
        assert 'href="/performance"' in n
