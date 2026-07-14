"""Run the squad paper loop (STUB team — shadow-only, no broker orders).

Replays an existing M001 replay cache into a live output directory in
accelerated wall-clock time, one row per tick, so the platform server's
/api/v2/live/* endpoints and the /v2 page's LIVE mode have a real
stream to tail. See ``agent/platform/paper_loop.py`` for the guarantees
(kill.txt honored, state.json resume, byte-parity with direct parsing)
and the cache-selection precedence (CLI flag > platform.toml > newest
``g7_replay_cache_g7retry1-*`` > newest ``g7_replay_cache_*``).

Typical usage (Mac, sibling research checkout auto-detected). With no
flags the loop picks the newest g7retry1 cache, which has all 7 v1
players active:

    .venv/bin/python scripts/run_squad_paper.py

Pin a specific G7 second-attempt aggregator arm:

    .venv/bin/python scripts/run_squad_paper.py --aggregator phi41

Or point at any cache by id / path:

    .venv/bin/python scripts/run_squad_paper.py \\
        --cache g7_replay_cache_phi5-arm4-post-kunigami

Stop it with Ctrl-C or by dropping a kill.txt into the output dir:

    echo "pause for review" > ~/Documents/TradingAgentLogs/squad_live/kill.txt

Restarting resumes from state.json; pass --reset to wipe the output dir
and start the replay from the top.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

from agent.platform.config import load_config  # noqa: E402
from agent.platform.paper_loop import (  # noqa: E402
    AGGREGATORS,
    SOURCE_FILES,
    PaperLoop,
    select_source_cache,
)
from agent.platform.squad_notify import SquadNotifier  # noqa: E402

load_dotenv(REPO_ROOT / ".env", override=False)


def main() -> None:
    cfg = load_config(REPO_ROOT)
    paper_cfg = cfg.get("paper_loop") or {}
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # --source-cache kept as a legacy alias for --cache (older runbook
    # snippets pass it); both feed the same resolver.
    ap.add_argument("--cache", "--source-cache", dest="cache",
                    default=paper_cfg.get("cache") or None,
                    help="explicit replay-cache id (a g7_replay_cache_* "
                         "folder name under --research-reviews) or an "
                         "absolute path; wins over --aggregator")
    ap.add_argument("--aggregator", choices=AGGREGATORS,
                    default=paper_cfg.get("aggregator") or None,
                    help="shorthand for the g7retry1 aggregator arm to "
                         "observe (resolves to g7_replay_cache_g7retry1-"
                         "<aggregator>); ignored when --cache is set")
    ap.add_argument("--research-reviews", type=Path,
                    default=cfg["research_reviews"],
                    help="where g7_replay_cache_* dirs live")
    ap.add_argument("--out-dir", type=Path, default=None,
                    help=f"live output dir (default {cfg['live_dir']})")
    ap.add_argument("--tick-seconds", type=float, default=2.0,
                    help="wall-clock seconds between emitted rows")
    ap.add_argument("--max-steps", type=int, default=None,
                    help="stop after N rows (default: run to exhaustion)")
    ap.add_argument("--reset", action="store_true",
                    help="wipe the output JSONLs + state.json first")
    ap.add_argument("--no-telegram", action="store_true",
                    help="suppress squad Telegram messages even when the "
                         "dedicated bot is configured")
    args = ap.parse_args()

    try:
        src, reason = select_source_cache(
            args.research_reviews,
            cache=args.cache,
            aggregator=args.aggregator,
        )
    except (FileNotFoundError, ValueError) as exc:
        sys.exit(str(exc))
    print(f"[paper-loop] source cache: {src.name} ({reason})")
    print(f"[paper-loop]   path: {src}")

    out_dir = args.out_dir or cfg["live_dir"]
    if args.reset and out_dir.exists():
        for fname, _ in SOURCE_FILES:
            (out_dir / fname).unlink(missing_ok=True)
        (out_dir / "state.json").unlink(missing_ok=True)
        (out_dir / "workspace_counts.json").unlink(missing_ok=True)
        print(f"[paper-loop] reset {out_dir}")

    # Dedicated squad bot: platform.toml [telegram] wins over
    # SQUAD_TELEGRAM_* env vars; unconfigured -> silent no-op.
    notifier = None
    if not args.no_telegram:
        candidate = SquadNotifier.from_sources(cfg.get("telegram"))
        if candidate.configured:
            notifier = candidate
            print("[paper-loop] squad Telegram bot: configured "
                  "(goals/halts/summaries will page)")
        else:
            print("[paper-loop] squad Telegram bot: not configured "
                  "(set [telegram] in platform.toml or SQUAD_TELEGRAM_* "
                  "in .env)")

    loop = PaperLoop(src, out_dir, tick_seconds=args.tick_seconds,
                     notifier=notifier)
    try:
        outcome = loop.run(max_steps=args.max_steps)
    except KeyboardInterrupt:
        print("\n[paper-loop] interrupted — state saved, restart to resume")
        return
    print(f"[paper-loop] finished: {outcome}")


if __name__ == "__main__":
    main()
