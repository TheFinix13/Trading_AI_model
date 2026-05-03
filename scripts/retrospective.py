"""Generate the weekly retrospective for the human + agent journals.

Run every Friday after the close (or any time, against any week):

    python scripts/retrospective.py                      # this week (default)
    python scripts/retrospective.py --week 2026-04-27    # the week containing this date

The script:

  1. Pulls all human_lessons + agent_disagreements for the requested week.
  2. Clusters losing lessons by failure mode (no_signal, agent_disagree,
     agent_partial_agree, etc.).
  3. Asks the local LLM for a 5-bullet summary IF Ollama is available;
     otherwise emits a deterministic template.
  4. Persists the report into ``weekly_retrospectives``.
  5. Prints the report to stdout for immediate review.

The point: by Sunday night you have a written record of which discretionary
patterns worked, which cost you, and where the agent agreed or disagreed.
That feeds Monday's chart prep AND the next ML retrain.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent.config import load_config
from agent.journal.db import Journal
from agent.llm.chat import ChatService
from agent.llm.ollama import OllamaUnavailable

log = logging.getLogger(__name__)


def _week_bounds(anchor: date) -> tuple[date, date]:
    """Return (Monday, Sunday) for the ISO week containing `anchor`."""
    monday = anchor - timedelta(days=anchor.weekday())
    return monday, monday + timedelta(days=6)


def _cluster_failures(lessons: list[dict],
                       diffs: dict[int, list[dict]]) -> list[dict]:
    """Group losses by qualitative failure mode. Returns a list of
    {label, count, example_lesson_ids}."""
    buckets: dict[str, list[int]] = defaultdict(list)
    for L in lessons:
        if L.get("outcome") != "loss":
            continue
        d_list = diffs.get(L["id"], [])
        if not d_list:
            buckets["no_replay_diff"].append(L["id"])
            continue
        d = d_list[-1]
        agreement = d.get("agreement", "no_signal")
        if agreement == "agree":
            buckets["both_wrong"].append(L["id"])
        elif agreement == "partial":
            buckets["agent_weak_agree"].append(L["id"])
        elif agreement == "disagree":
            buckets["agent_disagreed"].append(L["id"])
        else:
            buckets["no_setup_at_all"].append(L["id"])
    out = [
        {"label": k, "count": len(v), "example_lesson_ids": v[:5]}
        for k, v in sorted(buckets.items(), key=lambda kv: -len(kv[1]))
    ]
    return out


def _llm_summary(chat: ChatService, week_start: date, week_end: date,
                  lessons: list[dict], clusters: list[dict]) -> str:
    """Ask the local LLM for a tight 5-bullet retrospective."""
    if not chat.is_available():
        raise OllamaUnavailable("LLM offline")

    payload = {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "n_lessons": len(lessons),
        "n_wins": sum(1 for L in lessons if L.get("outcome") == "win"),
        "n_losses": sum(1 for L in lessons if L.get("outcome") == "loss"),
        "total_pips": round(sum(L.get("pnl_pips") or 0 for L in lessons), 1),
        "failure_clusters": clusters,
        "lessons_summary": [
            {
                "date": L["trade_date"],
                "dir": L["direction"],
                "outcome": L["outcome"],
                "pips": L.get("pnl_pips"),
                "bias": L.get("daily_bias"),
                "session": L.get("session"),
                "emotion": L.get("emotion"),
                "confluences": L.get("confluences_parsed", []),
            }
            for L in lessons[:25]
        ],
    }
    sys_prompt = (
        "You are the trader's retrospective coach. Given JSON about the week's "
        "trades, write a tight 5-bullet review. Each bullet starts with one of: "
        "WIN PATTERN, LOSS PATTERN, AGENT GAP, NEXT WEEK FOCUS, or RISK NOTE. "
        "Be concrete, name confluences, name sessions, name dates. No fluff."
    )
    user = "Here is the week's data:\n\n" + json.dumps(payload, default=str, indent=2)
    return chat.ask(user, context=sys_prompt)


def _template_summary(lessons: list[dict], clusters: list[dict],
                       week_start: date, week_end: date,
                       n_wins: int, n_losses: int, total_pips: float) -> str:
    """Deterministic fallback when no LLM is available."""
    lines = [
        f"WEEKLY RETROSPECTIVE  {week_start} -> {week_end}",
        f"  trades: {len(lessons)}   wins: {n_wins}   losses: {n_losses}   "
        f"pips: {total_pips:+.1f}",
        "",
        "FAILURE CLUSTERS:",
    ]
    if not clusters:
        lines.append("  (no losses logged this week)")
    for c in clusters:
        ids = ", ".join(f"#{i}" for i in c["example_lesson_ids"])
        lines.append(f"  - {c['label']:<22s} count={c['count']:<3d} eg: {ids}")
    lines += ["", "NEXT WEEK FOCUS:",
              "  Run scripts/teach.py to add LLM-driven analysis."]
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description="Weekly trading retrospective.")
    p.add_argument("--week", type=str, default=None,
                    help="Any date in the target week (YYYY-MM-DD). Default: today.")
    p.add_argument("--no-llm", action="store_true", help="Skip LLM, use template only.")
    p.add_argument("--no-save", action="store_true", help="Don't persist into journal.")
    args = p.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    cfg = load_config()
    journal = Journal(cfg.journal_db)

    anchor = date.fromisoformat(args.week) if args.week else date.today()
    week_start, week_end = _week_bounds(anchor)

    lessons = journal.all_lessons(start_date=week_start.isoformat(),
                                   end_date=week_end.isoformat())
    for L in lessons:
        try:
            L["confluences_parsed"] = json.loads(L.get("confluences_json") or "[]")
        except Exception:
            L["confluences_parsed"] = []

    diffs_by_lesson: dict[int, list[dict]] = {
        L["id"]: journal.disagreements_for_lesson(L["id"]) for L in lessons
    }
    clusters = _cluster_failures(lessons, diffs_by_lesson)

    n_wins = sum(1 for L in lessons if L.get("outcome") == "win")
    n_losses = sum(1 for L in lessons if L.get("outcome") == "loss")
    total_pips = sum(L.get("pnl_pips") or 0 for L in lessons)
    total_usd = sum(L.get("pnl_usd") or 0 for L in lessons)

    summary_text: str
    if args.no_llm or not lessons:
        summary_text = _template_summary(lessons, clusters, week_start, week_end,
                                          n_wins, n_losses, total_pips)
    else:
        try:
            chat = ChatService()
            summary_text = _llm_summary(chat, week_start, week_end, lessons, clusters)
        except OllamaUnavailable:
            summary_text = _template_summary(lessons, clusters, week_start, week_end,
                                              n_wins, n_losses, total_pips)

    print("\n" + "=" * 78)
    print(f"  WEEKLY RETROSPECTIVE  {week_start}  →  {week_end}")
    print("=" * 78)
    print(f"  Lessons logged: {len(lessons):>3d}     Wins: {n_wins:>3d}     "
          f"Losses: {n_losses:>3d}     Pips: {total_pips:+.1f}     "
          f"USD: ${total_usd:+.2f}")
    print("-" * 78)
    print(summary_text)
    print("=" * 78 + "\n")

    if not args.no_save:
        retro_id = journal.log_retrospective(
            week_start=week_start.isoformat(),
            week_end=week_end.isoformat(),
            n_trades=len(lessons),
            n_wins=n_wins,
            n_losses=n_losses,
            total_pips=total_pips,
            total_usd=total_usd,
            failure_clusters=clusters,
            lessons_learned=summary_text,
        )
        print(f"  Saved as retrospective#{retro_id}.")
    journal.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
