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
