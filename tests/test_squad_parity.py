"""Parity harness: ported engine vs banked g7retry1-phi41 cache rows.

Reads the research replay-cache FILES read-only (never imports research
code). Replays a short early window of the same parquet bars through
the ported engine (Barou v1 sealed, parity_mode) and compares
proposal (time, symbol, direction, agent_id, conviction) tuples.

Honesty: full byte-parity across the 11-year panel is out of scope for
this pass — the cache is an end-to-end artifact without full input
provenance (warmup seeding, float paths, Phase Y Barou default). We
report the achieved match-rate on a bounded early slice and skip the
test outright when the research cache or trading-repo parquet is
absent (CI / fresh checkouts).
"""
from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent.config import load_config
from agent.data.loader import BarLoader
from agent.squad.engine import SquadEngine
from agent.squad.roster import build_roster
from agent.types import Timeframe

REPO_ROOT = Path(__file__).resolve().parents[1]
RESEARCH_CACHE = (
    REPO_ROOT.parent
    / "finance-research-experiments"
    / "programs"
    / "M001_multi_agent_ensemble"
    / "reviews"
    / "g7_replay_cache_g7retry1-phi41"
)

# Early-window slice for the parity check. tick_ids in the cache start
# around the post-warmup region; we match on (timestamp, symbol,
# agent_id, direction) and then compare conviction within TOL.
SLICE_START = datetime(2015, 2, 17, tzinfo=timezone.utc)
SLICE_END = datetime(2015, 3, 17, tzinfo=timezone.utc)
CONV_TOL = 0.05
# Soft gate: at least this fraction of reference proposals in the slice
# should find a ported counterpart with matching key + conviction.
MIN_MATCH_RATE = 0.40


def _cache_available() -> bool:
    return (RESEARCH_CACHE / "proposals_all.jsonl").is_file()


def _load_ref_proposals():
    rows = []
    with (RESEARCH_CACHE / "proposals_all.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            ts = datetime.fromisoformat(row["timestamp"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if not (SLICE_START <= ts < SLICE_END):
                continue
            rows.append(row)
    return rows


def _key(row: dict) -> tuple:
    return (
        row["timestamp"][:19],  # drop tz suffix variance
        row["symbol"],
        row["agent_id"],
        row["direction"],
    )


@pytest.mark.skipif(not _cache_available(), reason="g7retry1-phi41 cache absent")
def test_parity_early_slice_against_g7retry1(tmp_path: Path):
    cfg = load_config()
    loader = BarLoader(cache_root=cfg.data_dir)
    # Load a panel that covers warmup before the slice + the slice itself.
    warmup_start = SLICE_START - timedelta(days=120)
    bars_by_symbol = {}
    for sym in ("EURUSD", "GBPUSD", "USDCAD"):
        bars = loader.get_bars(sym, Timeframe.H4, warmup_start, SLICE_END)
        if len(bars) < 250:
            pytest.skip(f"insufficient parquet history for {sym}: {len(bars)}")
        bars_by_symbol[sym] = bars

    out = tmp_path / "parity"
    roster = build_roster(barou_v12=False, barou_v13=False)  # sealed v1
    engine = SquadEngine(
        roster, out, aggregator_arm="phi41", source_label="parity_harness",
    )
    # Bound the batch: only process bars up to SLICE_END (already in load).
    # Cap max_bars so this stays a unit-test-scale run (~few thousand).
    stats = engine.run_batch(bars_by_symbol, max_bars=3500)
    assert stats["bars_processed"] > 0

    # Collect ported proposals in the slice window.
    ported = []
    prop_path = out / "proposals_all.jsonl"
    if prop_path.exists():
        with prop_path.open(encoding="utf-8") as fh:
            for line in fh:
                row = json.loads(line)
                ts = datetime.fromisoformat(row["timestamp"])
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if SLICE_START <= ts < SLICE_END:
                    ported.append(row)

    ref = _load_ref_proposals()
    if not ref:
        pytest.skip("no reference proposals in early slice")

    ported_by_key: dict[tuple, list[dict]] = {}
    for r in ported:
        ported_by_key.setdefault(_key(r), []).append(r)

    matched = 0
    conviction_hits = 0
    missing_agents = Counter()
    for r in ref:
        k = _key(r)
        cands = ported_by_key.get(k) or []
        if not cands:
            missing_agents[r["agent_id"]] += 1
            continue
        matched += 1
        # Conviction within tolerance against any duplicate key.
        if any(
            abs(float(c["conviction"]) - float(r["conviction"])) <= CONV_TOL
            for c in cands
        ):
            conviction_hits += 1

    match_rate = matched / len(ref)
    conv_rate = conviction_hits / len(ref)

    report = {
        "slice": [SLICE_START.isoformat(), SLICE_END.isoformat()],
        "n_ref": len(ref),
        "n_ported": len(ported),
        "matched_key": matched,
        "match_rate": round(match_rate, 4),
        "conviction_hits": conviction_hits,
        "conviction_rate": round(conv_rate, 4),
        "missing_by_agent": dict(missing_agents),
        "engine_stats": stats,
        "parity_level": (
            "proposal-key+conviction@tol"
            if conv_rate >= MIN_MATCH_RATE
            else "partial/proposal-key-only-or-low"
        ),
    }
    # Always write the report next to the tmp out for human inspection;
    # also print so pytest -s shows it.
    (out / "parity_report.json").write_text(json.dumps(report, indent=2))
    print("PARITY_REPORT", json.dumps(report))

    assert match_rate >= MIN_MATCH_RATE, (
        f"parity match_rate {match_rate:.2%} < {MIN_MATCH_RATE:.0%}; "
        f"report={report}"
    )
