"""Run the squad paper loop (STUB team — shadow-only, no broker orders).

Replays an existing M001 replay cache into a live output directory in
accelerated wall-clock time, one row per tick, so the platform server's
/api/v2/live/* endpoints and the /v2 page's LIVE mode have a real
stream to tail. See ``agent/platform/paper_loop.py`` for the guarantees
(kill.txt honored, state.json resume, byte-parity with direct parsing).

Typical usage (Mac, sibling research checkout):

    .venv/bin/python scripts/run_squad_paper.py \
        --source-cache g7_replay_cache_phi5-arm4-post-kunigami \
        --tick-seconds 2

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
from agent.platform.paper_loop import SOURCE_FILES, PaperLoop  # noqa: E402
from agent.platform.squad_notify import SquadNotifier  # noqa: E402

load_dotenv(REPO_ROOT / ".env", override=False)


def main() -> None:
    cfg = load_config(REPO_ROOT)
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source-cache", required=True,
                    help="replay cache to replay: a g7_replay_cache_* name "
                         "under the research reviews dir, or an absolute path")
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

    src = Path(args.source_cache)
    if not src.is_absolute():
        src = args.research_reviews / args.source_cache
    if not src.is_dir():
        sys.exit(f"source cache not found: {src}")

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
