"""``[squad_live]`` config-block parsing (equity / field_assignments).

`platform.toml.example` has documented `equity = 500` and
`[squad_live.field_assignments]` since the AN-3 XAGUSD candidacy, but
`load_config` never parsed either key, so `run_squad_live.main()` — which
does read `sl["equity"]` / `sl["field_assignments"]` — always saw them
absent and silently fell back to the $100 sandbox with no field
widening. Only the CLI flags worked. These tests pin the file path.

Unset keys must stay None/{} so the runtime's own fallbacks ($100, no
widening, 2 burn-in bars, 9 h staleness) remain the single source of
truth for the default case.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform.config import load_config  # noqa: E402


def _repo(tmp_path: Path, body: str) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "platform.toml").write_text(body, encoding="utf-8")
    return repo


class TestEquity:

    def test_equity_from_file_is_parsed(self, tmp_path: Path):
        repo = _repo(tmp_path, "[squad_live]\nequity = 500\n")
        assert load_config(repo)["squad_live"]["equity"] == 500.0

    def test_absent_equity_stays_none_for_runtime_fallback(self, tmp_path: Path):
        repo = _repo(tmp_path, "[squad_live]\nfeed = \"mt5\"\n")
        assert load_config(repo)["squad_live"]["equity"] is None

    def test_junk_equity_falls_back_to_none(self, tmp_path: Path):
        repo = _repo(tmp_path, "[squad_live]\nequity = \"lots\"\n")
        assert load_config(repo)["squad_live"]["equity"] is None

    def test_no_config_file_leaves_defaults(self, tmp_path: Path):
        repo = tmp_path / "bare"
        repo.mkdir()
        sl = load_config(repo)["squad_live"]
        assert sl["equity"] is None
        assert sl["field_assignments"] == {}


class TestFieldAssignments:

    def test_table_of_lists_is_parsed(self, tmp_path: Path):
        repo = _repo(tmp_path, (
            "[squad_live]\nequity = 500\n"
            "[squad_live.field_assignments]\n"
            "chigiri_hyoma = [\"XAGUSD\"]\n"
        ))
        sl = load_config(repo)["squad_live"]
        assert sl["field_assignments"] == {"chigiri_hyoma": ["XAGUSD"]}

    def test_comma_string_value_is_split(self, tmp_path: Path):
        repo = _repo(tmp_path, (
            "[squad_live.field_assignments]\n"
            "barou_shoei = \"USDJPY, USTEC\"\n"
        ))
        sl = load_config(repo)["squad_live"]
        assert sl["field_assignments"] == {"barou_shoei": ["USDJPY", "USTEC"]}

    def test_empty_symbol_list_is_dropped(self, tmp_path: Path):
        repo = _repo(tmp_path, (
            "[squad_live.field_assignments]\nchigiri_hyoma = []\n"
        ))
        assert load_config(repo)["squad_live"]["field_assignments"] == {}


class TestOtherPreviouslyUnparsedKeys:

    def test_burn_in_and_stale_hours_are_parsed(self, tmp_path: Path):
        repo = _repo(tmp_path, (
            "[squad_live]\nburn_in_bars = 4\nfeed_stale_hours = 12.5\n"
        ))
        sl = load_config(repo)["squad_live"]
        assert sl["burn_in_bars"] == 4
        assert sl["feed_stale_hours"] == 12.5

    def test_existing_keys_still_parsed(self, tmp_path: Path):
        repo = _repo(tmp_path, (
            "[squad_live]\nfeed = \"mt5\"\naggregator = \"arm4\"\n"
            "poll_seconds = 30\nsymbols = [\"EURUSD\", \"XAGUSD\"]\n"
        ))
        sl = load_config(repo)["squad_live"]
        assert sl["feed"] == "mt5"
        assert sl["aggregator"] == "arm4"
        assert sl["poll_seconds"] == 30
        assert sl["symbols"] == ["EURUSD", "XAGUSD"]
