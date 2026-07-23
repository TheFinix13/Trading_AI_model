"""Run the squad on the live market (paper) — shadow-only, no broker orders.

Ported v1 (unvalidated port) of the Blue Lock squad reacts to newly
closed H4 bars on EURUSD / GBPUSD / USDCAD. Agent logic lives under
``agent/squad/`` (reimplemented from the research sim; never imported).
Fills use the production paper fill model. Events land in the same
three-JSONL schema the /v2 LIVE page and squad Telegram bot already
tail, under ``<log_root>/squad_live/``.

Hard guarantees:

* Shadow-only. Never places broker orders (MT5 is used read-only for
  bars when ``--feed mt5``).
* Honours ``kill.txt`` in the output dir; writes daily heartbeat logs.
* ``state.json`` resumes open shadow positions + per-symbol cursor.
* Default feed: ``mt5`` on Windows, ``cache`` elsewhere.

Typical Mac (cache replay, accelerated):

    .venv/bin/python scripts/run_squad_live.py --feed cache --poll 1

Typical VM (MT5 live bars):

    .venv/bin/python scripts/run_squad_live.py --feed mt5 --poll 45

Stop:

    echo "pause" > ~/Documents/TradingAgentLogs/squad_live/kill.txt
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

from agent.platform.config import load_config  # noqa: E402
from agent.platform.squad_notify import SquadNotifier  # noqa: E402
from agent.squad import PORT_LABEL  # noqa: E402
from agent.squad.engine import SquadEngine  # noqa: E402
from agent.squad.feed import (  # noqa: E402
    DEFAULT_SYMBOLS,
    CacheFeed,
    Mt5Feed,
    default_feed_name,
    make_feed,
)
from agent.squad.news_config import DEFAULT_NEWS_CONFIG  # noqa: E402
from agent.squad.news_refresher import NewsFeedRefresher  # noqa: E402
from agent.squad.roster import SquadRoster, build_roster  # noqa: E402
from agent.squad.sae_config import SaeConfig  # noqa: E402
from agent.live.signal_loop import next_h4_close_utc  # noqa: E402

load_dotenv(REPO_ROOT / ".env", override=False)

log = logging.getLogger("squad_live")


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s -- %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def build_live_roster(
    symbols,
    *,
    parity_mode: bool = False,
    enable_sae: bool = False,
) -> SquadRoster:
    """Roster for the live runtime.

    Sae stays DISABLED unless ``enable_sae`` (the ``--enable-sae``
    flag). The Phase AE research pre-registration gate is the default;
    the flag only makes enabling operational without code edits.
    """
    return build_roster(
        symbols=tuple(symbols),
        barou_v12=False,
        barou_v13=not parity_mode,
        sae_config=SaeConfig(sae_enabled=True) if enable_sae else None,
    )


def _build_notifier(cfg: dict, *, no_telegram: bool):
    if no_telegram:
        return None
    candidate = SquadNotifier.from_sources(cfg.get("telegram"))
    if candidate.configured:
        log.info("squad Telegram bot: configured")
        return candidate
    log.info("squad Telegram bot: not configured (silent)")
    return None


async def _connect_mt5(cfg_live=None):
    """Connect the existing MT5 broker read-only. Never places orders."""
    from agent.live.broker import create_broker
    from agent.live.config import LiveConfig
    from agent.config import load_config as load_agent_config

    live = cfg_live or LiveConfig()
    agent_cfg = load_agent_config()
    broker = create_broker(
        broker_type=live.broker_type,
        login=live.mt5_login,
        password=live.mt5_password,
        server=live.mt5_server,
        path=live.mt5_path,
        initial_balance=live.paper_initial_balance,
        data_dir=agent_cfg.data_dir,
    )
    ok = await broker.connect()
    if not ok:
        raise RuntimeError("MT5 broker connect failed")
    return broker


def _seconds_until_next_h4_poll(poll: float) -> float:
    """Sleep until shortly after the next H4 close, then poll every ``poll`` s."""
    now = datetime.now(tz=timezone.utc)
    nxt = next_h4_close_utc(now)
    wait = (nxt - now).total_seconds() + 5.0  # 5s grace after close
    return max(poll, wait) if wait > poll else poll


def _write_poll_heartbeat(out_dir: Path, tick_id: int) -> None:
    """Atomically rewrite ``poll_heartbeat.txt`` on every poll iteration.

    The /v2 dashboard's ``paper_loop.live_status`` treats this file's
    mtime as a running-signal. Written every outer-loop iteration
    (~poll cadence) so the badge stays alive between H4 bar closes.
    Uses tmp + ``os.replace`` for atomicity: readers never observe a
    torn/partial line.
    """
    path = out_dir / "poll_heartbeat.txt"
    tmp = path.with_suffix(".tmp")
    line = (
        f"{datetime.now(tz=timezone.utc).isoformat()} tick={tick_id}\n"
    )
    try:
        tmp.write_text(line, encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        log.warning("poll heartbeat write failed: %s", exc)


def run_loop(args, cfg: dict) -> str:
    symbols = tuple(args.symbols) if args.symbols else DEFAULT_SYMBOLS
    out_dir = Path(args.out_dir) if args.out_dir else Path(cfg["live_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.reset and out_dir.exists():
        for fname in (
            "proposals_all.jsonl", "proposals_rejected.jsonl",
            "trades.jsonl", "events.jsonl", "state.json",
            "workspace_counts.json", "workspace_snapshot.json",
            "poll_heartbeat.txt",
        ):
            (out_dir / fname).unlink(missing_ok=True)
        log.info("reset %s", out_dir)

    notifier = _build_notifier(cfg, no_telegram=args.no_telegram)
    notify_fn = None
    if notifier is not None:
        notify_fn = notifier.notify_row

    roster = build_live_roster(
        symbols,
        parity_mode=args.parity_mode,
        enable_sae=bool(getattr(args, "enable_sae", False)),
    )
    source_label = (
        f"live_market:{args.feed}" if args.feed != "cache"
        else "cache_replay"
    )
    engine = SquadEngine(
        roster,
        out_dir,
        aggregator_arm=args.aggregator,
        notifier=notify_fn,
        source_label=source_label,
    )

    broker = None
    feed_name = args.feed or default_feed_name()

    if feed_name == "mt5":
        broker = asyncio.run(_connect_mt5())
        feed = Mt5Feed(
            broker, symbols=symbols,
            # Read-only M15 window for Sae's event mechanics (fade /
            # ride need intra-H4 bars around the release). Cheap and
            # harmless when Sae is disabled.
            m15_symbols=tuple(
                s for s in getattr(roster.sae, "symbols", ()) if s in symbols
            ),
        )
        asyncio.run(feed.refresh())
        warmup = feed.warmup_bars()
        # Late-bind Sae's M15 provider to the live feed's cache. On
        # non-MT5 feeds the provider stays unset and Sae fails open.
        roster.sae.set_bars_provider(feed.m15_bars)
    elif feed_name == "cache":
        feed = CacheFeed(
            symbols=symbols,
            bars_per_poll=args.cache_bars_per_poll,
        )
        # Resume cache cursor from state if present.
        if engine.last_bar_times and isinstance(feed, CacheFeed):
            # Best-effort: leave cursor at 0; engine skips already-seen
            # bars via last_bar_times gate below.
            pass
        warmup = feed.warmup_bars()
    else:
        feed = make_feed(feed_name, symbols=symbols)
        warmup = feed.warmup_bars()

    engine.prepare(warmup)

    # F4 fix: on the live-market path, credit the feed's historical
    # closed bars toward the warm-up gate so a fresh runtime doesn't
    # sit silent for 200 live H4 bars (~33 days). A small live burn-in
    # (default 2 bars) still applies after seeding. Cache replays and
    # --parity-mode never seed (byte-identical replay behavior).
    if feed_name == "mt5" and not args.parity_mode:
        seeded_any = False
        for sym, bars in warmup.items():
            seeded_any = engine.seed_warmup(
                sym, len(bars), burn_in_bars=args.burn_in_bars,
            ) or seeded_any
        if seeded_any:
            # Persist immediately so the dashboard shows the seeded
            # warm-up state before the first live bar closes.
            engine.save_state()

    news_cfg = DEFAULT_NEWS_CONFIG
    news_refresher: NewsFeedRefresher | None = None
    if not args.no_news_refresh:
        news_refresher = NewsFeedRefresher(
            karasu=roster.karasu,
            sae=roster.sae,
            cache_path=news_cfg.cache_path,
            feed_url=news_cfg.feed_url,
            ttl_seconds=news_cfg.cache_ttl_seconds,
            interval_seconds=float(args.news_refresh_seconds),
        )
        if args.refresh_news:
            n = news_refresher.kickoff()
            log.info("Karasu+Sae calendar kickoff: %d events cached", n)
        else:
            # Read whatever is already on disk without touching the
            # network; refresher will attempt a fetch after one
            # interval elapses.
            try:
                n = roster.karasu.load_calendar()
                log.info("Karasu cache-only load: %d events", n)
            except Exception as exc:   # noqa: BLE001
                log.warning("Karasu cache load failed: %s", exc)
            try:
                n_sae = roster.sae.load_calendar(
                    cache_path=news_cfg.cache_path,
                )
                log.info("Sae cache-only load: %d events", n_sae)
            except Exception as exc:   # noqa: BLE001
                log.warning("Sae cache load failed: %s", exc)
        news_refresher.start()
    else:
        # No refresher at all: still hydrate both news consumers once
        # from the on-disk cache (matching the --no-news-refresh help
        # text; both stay fail-open on a missing/empty cache).
        try:
            roster.karasu.load_calendar()
        except Exception as exc:   # noqa: BLE001
            log.warning("Karasu cache load failed: %s", exc)
        try:
            roster.sae.load_calendar(cache_path=news_cfg.cache_path)
        except Exception as exc:   # noqa: BLE001
            log.warning("Sae cache load failed: %s", exc)

    log.info(
        "squad live starting (%s) feed=%s arm=%s symbols=%s out=%s",
        PORT_LABEL, feed_name, args.aggregator, symbols, out_dir,
    )

    if notifier is not None:
        notifier.notify_kickoff(
            source_label=source_label,
            n_rows=0,
            out_dir=str(out_dir),
        )

    steps = 0
    outcome = "done"
    try:
        while True:
            # Proof-of-life for the /v2 dashboard between H4 bar closes:
            # state.json is only rewritten on bar closes (via save_state
            # in engine.on_bar), which leaves ~99% of clock time with a
            # stale mtime even though this loop is polling healthily.
            # See agent/platform/paper_loop.live_status.
            _write_poll_heartbeat(out_dir, engine.tick_id)
            reason = engine.kill_active()
            if reason is not None:
                log.warning("kill.txt active: %s", reason)
                outcome = "killed"
                if notifier is not None:
                    notifier.notify_stop("killed", reason=reason)
                break

            if feed_name == "mt5":
                asyncio.run(feed.refresh())

            new_bars = feed.poll_new_closed()
            if not new_bars:
                engine.write_heartbeat("idle")
                if feed_name == "cache" and getattr(feed, "remaining", 1) == 0:
                    log.info("cache feed exhausted")
                    outcome = "done"
                    break
                sleep_s = (
                    args.poll if feed_name == "cache"
                    else _seconds_until_next_h4_poll(args.poll)
                )
                # Cap idle sleep so kill.txt is checked reasonably often.
                sleep_s = min(sleep_s, max(args.poll, 60.0))
                time.sleep(sleep_s)
                continue

            for fb in new_bars:
                # Skip bars already processed (resume).
                last = engine.last_bar_times.get(fb.symbol)
                if last is not None:
                    try:
                        last_dt = datetime.fromisoformat(last)
                        if fb.bar.time <= last_dt:
                            continue
                    except ValueError:
                        pass
                # Need a next bar for fills — for cache/mt5 history look ahead.
                series = engine.bars_by_symbol.get(fb.symbol) or []
                next_bar = None
                # Extend history with this closed bar first.
                engine._extend_history(fb.symbol, fb.bar)
                series = engine.bars_by_symbol[fb.symbol]
                if fb.bar_index + 1 < len(series):
                    next_bar = series[fb.bar_index + 1]
                elif feed_name == "mt5" and hasattr(feed, "forming_bar"):
                    # Live: fill at the newly-opening (forming) bar's open.
                    next_bar = feed.forming_bar(fb.symbol)

                tr = engine.on_bar(
                    fb.symbol, fb.bar,
                    bar_index=fb.bar_index if fb.bar_index < len(series) else None,
                    next_bar=next_bar,
                )
                steps += 1
                log.info(
                    "tick symbol=%s time=%s proposals=%d closed=%d rejected=%d",
                    fb.symbol, fb.bar.time.isoformat(),
                    len(tr.proposals), len(tr.closed_trades), len(tr.rejected),
                )
                engine.write_heartbeat(
                    f"bar={fb.symbol}@{fb.bar.time.isoformat()}"
                )
                if args.max_steps and steps >= args.max_steps:
                    outcome = "max_steps"
                    break
            if args.max_steps and steps >= args.max_steps:
                break

            # Between H4 closes, poll at --poll cadence.
            if feed_name == "cache":
                time.sleep(max(0.0, args.poll))
            else:
                time.sleep(min(args.poll, 60.0))

    except KeyboardInterrupt:
        log.info("interrupted — state saved")
        outcome = "interrupted"
    finally:
        engine.save_state()
        if news_refresher is not None:
            news_refresher.stop()
        if notifier is not None and outcome not in ("killed",):
            notifier.notify_stop(outcome if outcome != "interrupted" else "max_steps")
        if broker is not None:
            try:
                asyncio.run(broker.disconnect())
            except Exception:  # noqa: BLE001
                pass
    return outcome


def build_arg_parser(sl: dict | None = None) -> argparse.ArgumentParser:
    """CLI surface for the squad live runner (extracted for tests)."""
    sl = sl or {}
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--feed", choices=("mt5", "cache", "fake"),
        default=sl.get("feed") or default_feed_name(),
        help="market feed (default: mt5 on Windows, cache elsewhere)",
    )
    ap.add_argument(
        "--aggregator", choices=("phi41", "arm4", "arm3"),
        default=sl.get("aggregator") or "phi41",
        help="aggregator arm (phi41 sealed default; arm4 multi-position)",
    )
    ap.add_argument(
        "--symbols", nargs="+",
        default=None,
        help="symbols to trade (default EURUSD GBPUSD USDCAD)",
    )
    ap.add_argument(
        "--poll", type=float,
        default=float(sl.get("poll_seconds") or 45),
        help="seconds between polls (cache: sleep between bars; mt5: idle poll)",
    )
    ap.add_argument(
        "--cache-bars-per-poll", type=int, default=1,
        help="cache feed: interleaved bars emitted per poll",
    )
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--max-steps", type=int, default=None)
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--no-telegram", action="store_true")
    ap.add_argument(
        "--parity-mode", action="store_true",
        help=(
            "disable Barou v1.3 weapon (use sealed v1) for cache parity "
            "work; also disables warm-up seeding on the mt5 feed"
        ),
    )
    ap.add_argument(
        "--enable-sae", action="store_true",
        help=(
            "add Sae (event-specialist striker) to the proposing roster. "
            "DEFAULT OFF -- the Phase AE research pre-registration gate "
            "stays; this flag only makes enabling operational without "
            "code edits"
        ),
    )
    ap.add_argument(
        "--burn-in-bars", type=int,
        default=int(sl.get("burn_in_bars") or 2),
        help=(
            "live bars withheld from proposing after warm-up seeding "
            "(mt5 feed only; feed-sanity confirmation window; default 2)"
        ),
    )
    ap.add_argument(
        "--refresh-news", action="store_true",
        help=(
            "kickoff a synchronous news-calendar refresh at startup "
            "(one fetch before the tick loop starts); the background "
            "refresher runs regardless unless --no-news-refresh"
        ),
    )
    ap.add_argument(
        "--no-news-refresh", action="store_true",
        help=(
            "disable Karasu's background news refresher entirely; "
            "Karasu will still read any pre-existing on-disk cache"
        ),
    )
    ap.add_argument(
        "--news-refresh-seconds", type=int, default=3600,
        help="background news-refresh interval (seconds); default 3600 (1 h)",
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    return ap


def main() -> None:
    cfg = load_config(REPO_ROOT)
    sl = cfg.get("squad_live") or {}
    args = build_arg_parser(sl).parse_args()
    if args.symbols is None and sl.get("symbols"):
        args.symbols = list(sl["symbols"])

    _configure_logging(args.verbose)
    outcome = run_loop(args, cfg)
    print(f"[squad-live] finished: {outcome}")


if __name__ == "__main__":
    main()
