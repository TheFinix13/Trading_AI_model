"""F011 -- kill_switches (READ path) tests.

Coverage:

- Empty state: no flag files -> is_killed() False for every scope.
- Global kill masks every per-symbol query.
- Per-symbol kill only affects the named symbol.
- SUPPORTED_SYMBOLS gate rejects unknown symbols.
- kill_dir override via BLUELOCK_KILL_DIR env var takes precedence.
- list_killed() shape is ordered [GLOBAL, EURUSD, GBPUSD, ...].
- Cache invalidates when directory mtime changes.
- Reset helper wipes the cache.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from agent.platform import credentials, kill_switch_admin, kill_switches


@pytest.fixture(autouse=True)
def _fresh_kill_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate every test in its own kill dir so cross-test flag
    files can't leak state."""
    kill_dir = tmp_path / "kill"
    kill_dir.mkdir()
    monkeypatch.setenv(kill_switches.KILL_DIR_ENV, str(kill_dir))
    credentials.set_config_dir(tmp_path)
    kill_switches.reset_cache_for_tests()
    yield kill_dir
    credentials.set_config_dir(None)
    kill_switches.reset_cache_for_tests()


def _write_flag(kill_dir: Path, scope: str, reason: str = "test") -> None:
    (kill_dir / f"{scope}.flag").write_text(
        json.dumps({"reason": reason,
                    "activated_at": "2026-07-22T01:30:00+00:00",
                    "by": "user"}),
        encoding="utf-8",
    )


class TestEmpty:
    def test_no_flags_no_kill(self) -> None:
        assert kill_switches.is_killed() is False
        assert kill_switches.is_killed("EURUSD") is False
        assert kill_switches.list_killed() == []


class TestGlobalKill:
    def test_global_kill_masks_all(self, _fresh_kill_dir: Path) -> None:
        _write_flag(_fresh_kill_dir, kill_switches.GLOBAL_KEY, "flash halt")
        kill_switches.reset_cache_for_tests()
        assert kill_switches.is_killed() is True
        for sym in kill_switches.SUPPORTED_SYMBOLS:
            assert kill_switches.is_killed(sym) is True, sym

    def test_list_killed_reports_global_first(self, _fresh_kill_dir: Path) -> None:
        _write_flag(_fresh_kill_dir, "EURUSD", "spread")
        _write_flag(_fresh_kill_dir, kill_switches.GLOBAL_KEY, "wobble")
        kill_switches.reset_cache_for_tests()
        rows = kill_switches.list_killed()
        assert [r["scope"] for r in rows] == ["GLOBAL", "EURUSD"]
        assert rows[0]["reason"] == "wobble"


class TestPerSymbol:
    def test_only_named_symbol_killed(self, _fresh_kill_dir: Path) -> None:
        _write_flag(_fresh_kill_dir, "EURUSD", "broker jitter")
        kill_switches.reset_cache_for_tests()
        assert kill_switches.is_killed() is False   # global not set
        assert kill_switches.is_killed("EURUSD") is True
        assert kill_switches.is_killed("GBPUSD") is False


class TestUnknownSymbol:
    def test_unknown_symbol_never_killed(self, _fresh_kill_dir: Path) -> None:
        _write_flag(_fresh_kill_dir, "EURUSD")
        kill_switches.reset_cache_for_tests()
        assert kill_switches.is_killed("ZZZXYZ") is False
        assert kill_switches.is_killed("") is False


class TestKillDirOverride:
    def test_env_var_wins_over_config_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        override = tmp_path / "alt_kill"
        override.mkdir()
        monkeypatch.setenv(kill_switches.KILL_DIR_ENV, str(override))
        assert kill_switches.kill_dir() == override

    def test_default_is_config_dir_slash_kill(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(kill_switches.KILL_DIR_ENV, raising=False)
        credentials.set_config_dir(tmp_path)
        try:
            expected = tmp_path / kill_switches.DEFAULT_KILL_DIRNAME
            assert kill_switches.kill_dir() == expected
        finally:
            credentials.set_config_dir(None)


class TestHotReload:
    def test_cache_invalidates_on_mtime_change(
        self, _fresh_kill_dir: Path
    ) -> None:
        assert kill_switches.is_killed("EURUSD") is False
        _write_flag(_fresh_kill_dir, "EURUSD")
        # Nudge mtime deterministically -- some filesystems don't
        # reflect a new file's mtime on the parent until touched.
        import os as _os
        _os.utime(_fresh_kill_dir, (time.time(), time.time() + 1))
        assert kill_switches.is_killed("EURUSD") is True

    def test_reset_cache_clears_state(self, _fresh_kill_dir: Path) -> None:
        _write_flag(_fresh_kill_dir, "EURUSD")
        kill_switches.reset_cache_for_tests()
        assert kill_switches.is_killed("EURUSD") is True
        (_fresh_kill_dir / "EURUSD.flag").unlink()
        kill_switches.reset_cache_for_tests()
        assert kill_switches.is_killed("EURUSD") is False


class TestListKilledShape:
    def test_list_killed_ordering_and_fields(
        self, _fresh_kill_dir: Path
    ) -> None:
        _write_flag(_fresh_kill_dir, "USDCAD", "spread")
        _write_flag(_fresh_kill_dir, "EURUSD", "wobble")
        kill_switches.reset_cache_for_tests()
        rows = kill_switches.list_killed()
        assert [r["scope"] for r in rows] == ["EURUSD", "USDCAD"]
        for row in rows:
            assert set(row.keys()) == {"scope", "reason", "activated_at", "by"}


class TestUnsupportedFilesIgnored:
    def test_stray_flag_names_are_ignored(self, _fresh_kill_dir: Path) -> None:
        # A file named after an unsupported symbol should be skipped
        # entirely -- the module never treats it as "killed".
        (_fresh_kill_dir / "NZDUSD.flag").write_text('{"reason": "x"}')
        # Also skip non-.flag files.
        (_fresh_kill_dir / "EURUSD.notflag").write_text("noise")
        kill_switches.reset_cache_for_tests()
        assert kill_switches.list_killed() == []
        assert kill_switches.is_killed("NZDUSD") is False
        assert kill_switches.is_killed("EURUSD") is False


class TestSymbolCoverage:
    """F025 B7: every symbol the squad can size a trade on must be
    killable. Before this, a per-symbol kill on XAGUSD -- the Phase
    AN-3 candidate -- silently did nothing."""

    def test_majors_keep_their_original_order(self) -> None:
        # list_killed documents ordering behaviour, so the first five
        # entries are pinned.
        assert kill_switches.SUPPORTED_SYMBOLS[:5] == (
            "EURUSD", "GBPUSD", "USDCAD", "USDJPY", "USDCHF")

    def test_metals_are_covered(self) -> None:
        for sym in ("XAGUSD", "XAUUSD"):
            assert sym in kill_switches.SUPPORTED_SYMBOLS, sym

    def test_covers_every_symbol_provenance_pips_knows(self) -> None:
        """provenance_pips' override tables are the authoritative set of
        non-FX instruments the squad has pip conventions for; a symbol
        it can size but the kill switch can't halt is a safety gap."""
        from agent.squad.provenance_pips import (
            PIP_SIZE_OVERRIDES, PIP_VALUE_PER_MIN_LOT_OVERRIDES,
        )
        known = set(PIP_SIZE_OVERRIDES) | set(
            PIP_VALUE_PER_MIN_LOT_OVERRIDES)
        missing = sorted(known - set(kill_switches.SUPPORTED_SYMBOLS))
        assert missing == [], f"not killable: {missing}"

    def test_xagusd_kill_actually_halts_xagusd(
        self, _fresh_kill_dir: Path
    ) -> None:
        _write_flag(_fresh_kill_dir, "XAGUSD", "silver spread blowout")
        kill_switches.reset_cache_for_tests()
        assert kill_switches.is_killed("XAGUSD") is True
        assert kill_switches.is_killed("XAUUSD") is False
        assert kill_switches.is_killed("EURUSD") is False

    def test_new_symbols_round_trip_through_the_admin_path(
        self, _fresh_kill_dir: Path
    ) -> None:
        for sym in ("XAGUSD", "USTEC", "USOIL", "BTCUSD"):
            assert kill_switches.is_killed(sym) is False, sym
            kill_switch_admin.activate_kill(sym, reason="coverage test")
            assert kill_switches.is_killed(sym) is True, sym
            kill_switch_admin.clear_kill(sym)
            assert kill_switches.is_killed(sym) is False, sym

    def test_list_killed_orders_new_symbols_by_tuple_position(
        self, _fresh_kill_dir: Path
    ) -> None:
        _write_flag(_fresh_kill_dir, "BTCUSD", "c")
        _write_flag(_fresh_kill_dir, "XAGUSD", "b")
        _write_flag(_fresh_kill_dir, "EURUSD", "a")
        kill_switches.reset_cache_for_tests()
        rows = kill_switches.list_killed()
        assert [r["scope"] for r in rows] == [
            "EURUSD", "XAGUSD", "BTCUSD"]

    def test_unknown_symbol_gap_is_still_open(
        self, _fresh_kill_dir: Path
    ) -> None:
        """DOCUMENTED REMAINING GAP -- not a fix, a description.

        `is_killed` fails OPEN for a symbol outside SUPPORTED_SYMBOLS:
        a per-symbol kill flag for it is silently ignored and only the
        GLOBAL flag can halt it. B7 widened the list, which narrows the
        gap to instruments nothing in the platform can size yet; it did
        NOT change the fail-open semantics, because flipping a safety
        primitive's default is a separate decision.
        """
        assert "NZDUSD" not in kill_switches.SUPPORTED_SYMBOLS
        _write_flag(_fresh_kill_dir, "NZDUSD", "ignored on purpose")
        kill_switches.reset_cache_for_tests()
        # The flag exists on disk and is still not a kill.
        assert (_fresh_kill_dir / "NZDUSD.flag").is_file()
        assert kill_switches.is_killed("NZDUSD") is False
        assert kill_switches.list_killed() == []
        # GLOBAL remains the only thing that halts it.
        _write_flag(_fresh_kill_dir, kill_switches.GLOBAL_KEY, "halt")
        kill_switches.reset_cache_for_tests()
        assert kill_switches.is_killed("NZDUSD") is True


class TestLiveModeOffContract:
    """Sanity: kill_switches.is_killed() is the SECOND gate in the
    4-check live-order pathway. Sprint 2 doesn't wire it into live
    orders (D065 invariant), but the function shape must match what a
    future integration expects."""

    def test_is_killed_returns_bool(self, _fresh_kill_dir: Path) -> None:
        assert isinstance(kill_switches.is_killed(), bool)
        assert isinstance(kill_switches.is_killed("EURUSD"), bool)

    def test_activate_clear_toggles_is_killed(
        self, _fresh_kill_dir: Path
    ) -> None:
        assert kill_switches.is_killed("EURUSD") is False
        kill_switch_admin.activate_kill("EURUSD", reason="test")
        assert kill_switches.is_killed("EURUSD") is True
        kill_switch_admin.clear_kill("EURUSD")
        assert kill_switches.is_killed("EURUSD") is False
