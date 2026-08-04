"""Neo Egoist League table -- per-agent HP scoreboard (observe-only).

Scores any squad tape directory (the live ``squad_live/`` dir or a
batch-replay cell containing ``trades.jsonl`` + ``events.jsonl``)
under the v1 scoring rules of D145
(``company/strategy/neo-egoist-league-charter.md``):

  * every player starts the match window at 100 HP
  * each closed trade: dHP = 10 x realized R
  * overtime (bars_held > 30): additional -3
  * proposer with ZERO trades: -1 HP per 250 bars observed (cap -25)
  * HP <= 0 -> RELEGATION REVIEW flag (a decision for the user at the
    weekly review -- this script never benches anyone)

Score, flag, publish -- nothing else. No mutation of squad state,
roster, or parameters.

Usage:
    python scripts/league_table.py                       # live tape
    python scripts/league_table.py --live-dir <replay cell dir>
    python scripts/league_table.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

STARTING_HP = 100.0
HP_PER_R = 10.0
OVERTIME_BARS = 30          # ~1 trading week of H4 bars
OVERTIME_PENALTY = 3.0
DRAIN_PER_BARS = 250        # zero-conversion drain granularity
DRAIN_CAP = 25.0

# Non-proposers (advisors / side channels) are exempt from the
# zero-conversion drain: their job is not to shoot.
NON_PROPOSERS = ("karasu_tabito", "kunigami_rensuke", "itoshi_sae")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def score_tape(live_dir: Path) -> dict:
    """Compute the league table for one tape directory. Pure read."""
    trades = _read_jsonl(live_dir / "trades.jsonl")
    ticks = [r for r in _read_jsonl(live_dir / "events.jsonl")
             if r.get("type") == "tick_summary"]

    # Bars observed per agent: ticks where the agent was evaluated.
    bars_observed: dict[str, int] = {}
    players: set[str] = set()
    for t in ticks:
        for aid in t.get("players_evaluated") or []:
            bars_observed[aid] = bars_observed.get(aid, 0) + 1
            players.add(aid)
    players.update(t.get("agent_id") for t in trades if t.get("agent_id"))

    table: list[dict] = []
    for aid in sorted(players):
        own = [t for t in trades if t.get("agent_id") == aid]
        total_r = sum(float(t.get("r_multiple") or 0.0) for t in own)
        pips = sum(float(t.get("pnl_pips") or 0.0) for t in own)
        wins = sum(1 for t in own if float(t.get("r_multiple") or 0.0) > 0)
        overtime = sum(1 for t in own
                       if float(t.get("bars_held") or 0) > OVERTIME_BARS)

        hp = STARTING_HP + HP_PER_R * total_r - OVERTIME_PENALTY * overtime
        drain = 0.0
        if not own and aid not in NON_PROPOSERS:
            drain = min(DRAIN_CAP,
                        bars_observed.get(aid, 0) / DRAIN_PER_BARS)
            hp -= drain

        table.append({
            "agent_id": aid,
            "hp": round(hp, 1),
            "trades": len(own),
            "wins": wins,
            "win_rate": round(wins / len(own), 3) if own else None,
            "total_r": round(total_r, 2),
            "pips": round(pips, 1),
            "overtime_trades": overtime,
            "zero_conversion_drain": round(drain, 1),
            "bars_observed": bars_observed.get(aid, 0),
            "relegation_review": hp <= 0.0,
        })
    table.sort(key=lambda r: -r["hp"])
    return {"live_dir": str(live_dir), "rules": {
        "starting_hp": STARTING_HP, "hp_per_r": HP_PER_R,
        "overtime_bars": OVERTIME_BARS,
        "overtime_penalty": OVERTIME_PENALTY,
        "drain_per_bars": DRAIN_PER_BARS, "drain_cap": DRAIN_CAP,
    }, "table": table}


def render(result: dict) -> str:
    lines = [
        "NEO EGOIST LEAGUE — match window scoreboard (observe-only, D145)",
        f"tape: {result['live_dir']}",
        "",
        f"{'#':>2} {'player':<18} {'HP':>7} {'trades':>6} {'win%':>6} "
        f"{'totalR':>7} {'pips':>9} {'OT':>3} {'flag':<18}",
    ]
    for i, r in enumerate(result["table"], 1):
        win = f"{r['win_rate'] * 100:.0f}%" if r["win_rate"] is not None else "—"
        flag = "RELEGATION REVIEW" if r["relegation_review"] else ""
        if r["zero_conversion_drain"]:
            flag = (flag + " zero-conversion").strip()
        lines.append(
            f"{i:>2} {r['agent_id']:<18} {r['hp']:>7.1f} {r['trades']:>6} "
            f"{win:>6} {r['total_r']:>7.2f} {r['pips']:>9.1f} "
            f"{r['overtime_trades']:>3} {flag:<18}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    from agent.platform.config import load_config
    cfg = load_config(REPO_ROOT)
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--live-dir", type=Path, default=cfg["live_dir"])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    result = score_tape(Path(args.live_dir))
    print(json.dumps(result, indent=2) if args.json else render(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
