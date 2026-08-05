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
import json
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


def parse_field_assignments(
    raw: list[str] | dict | None,
) -> dict[str, tuple[str, ...]] | None:
    """Parse ``agent_id:SYM[,SYM…]`` CLI tokens or a toml mapping.

    Returns ``None`` when empty (byte-identical roster path). Raises
    ``ValueError`` on malformed tokens so misconfig fails loud at boot.
    """
    if not raw:
        return None
    out: dict[str, list[str]] = {}
    if isinstance(raw, dict):
        for agent_id, syms in raw.items():
            if isinstance(syms, str):
                syms = [syms]
            out.setdefault(str(agent_id), []).extend(str(s).upper() for s in syms)
    else:
        for token in raw:
            if ":" not in token:
                raise ValueError(
                    f"field assignment {token!r} must be agent_id:SYMBOL[,SYMBOL…]"
                )
            agent_id, syms = token.split(":", 1)
            added = [s.strip().upper() for s in syms.split(",") if s.strip()]
            if not agent_id.strip() or not added:
                raise ValueError(f"field assignment {token!r} is empty")
            out.setdefault(agent_id.strip(), []).extend(added)
    return {k: tuple(dict.fromkeys(v)) for k, v in out.items()} or None


def build_live_roster(
    symbols,
    *,
    parity_mode: bool = False,
    enable_sae: bool = False,
    field_assignments: dict[str, tuple[str, ...]] | None = None,
) -> SquadRoster:
    """Roster for the live runtime.

    Sae stays DISABLED unless ``enable_sae`` (the ``--enable-sae``
    flag). The Phase AE research pre-registration gate is the default;
    the flag only makes enabling operational without code edits.

    ``field_assignments`` widens a proposer's symbol whitelist beyond its
    natural home fields (D148). First live use: chigiri_hyoma → XAGUSD
    after Phase AN-3 sealed pass.
    """
    return build_roster(
        symbols=tuple(symbols),
        barou_v12=False,
        barou_v13=not parity_mode,
        sae_config=SaeConfig(sae_enabled=True) if enable_sae else None,
        field_assignments=field_assignments,
    )


def make_calendar_status_sink(out_dir: Path, notifier=None):
    """Sink for NewsFeedRefresher ``system_status`` rows (F5/F6).

    Every row is appended to ``events.jsonl`` (structured, greppable,
    dashboard-readable). The Telegram page is rate-limited to once per
    failure STREAK (streak==1 only, same pattern as the halt one-offs)
    -- never once per poll.
    """
    out_dir = Path(out_dir)

    def sink(row: dict) -> None:
        try:
            with (out_dir / "events.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, default=str) + "\n")
        except OSError as exc:
            log.warning("calendar status event write failed: %s", exc)
        if notifier is not None and int(row.get("failure_streak") or 0) == 1:
            age = row.get("cache_age_seconds")
            age_txt = f"{age:.0f}s old" if isinstance(age, (int, float)) else "absent"
            notifier.notify_system(
                f"news calendar cache {row.get('status', '?')} "
                f"({age_txt}) — Karasu/Sae advisories may be blind. "
                f"Check the feed / VM network."
            )

    return sink


def _emit_system_status(
    out_dir: Path, row: dict, notifier=None, notify_text: str | None = None,
) -> None:
    """Append a ``system_status`` row to events.jsonl (+ optional page).

    Same schema family as the news-calendar sink so the /v2 page, the
    weekly report's "system health" section and grep all see one shape.
    Failures here must never take down the trading loop.
    """
    row.setdefault("type", "system_status")
    row.setdefault(
        "timestamp", datetime.now(tz=timezone.utc).isoformat(),
    )
    try:
        with (Path(out_dir) / "events.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
    except OSError as exc:
        log.warning("system status event write failed: %s", exc)
    if notifier is not None and notify_text:
        try:
            notifier.notify_system(notify_text)
        except Exception as exc:  # noqa: BLE001
            log.warning("system status notify failed: %s", exc)


def _in_weekend_gap(now: datetime) -> bool:
    """True inside the FX weekend close (no H4 closes are expected).

    Friday 20:00 UTC through Sunday 22:00 UTC, generous on both edges so
    DST shifts don't cause false staleness pages. Outside this window a
    silent feed is a real problem.
    """
    wd = now.weekday()  # Mon=0 .. Sun=6
    if wd == 5:  # Saturday
        return True
    if wd == 4 and now.hour >= 20:  # late Friday
        return True
    if wd == 6 and now.hour < 22:  # Sunday before the open
        return True
    return False


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
    """Connect the existing MT5 broker read-only. Never places orders.

    I019: a bare ``LiveConfig()`` defaults to ``broker_type="paper"``,
    whose PaperBroker memoizes the parquet cache once at boot — the
    "live" feed then silently freezes at the newest cached bar. When
    the caller asked for ``--feed mt5`` we must attach to a real MT5
    terminal (credentials from .env, same as run_live.py) and fail
    loudly if that isn't possible, never degrade to a frozen snapshot.
    """
    from agent.live.broker import create_broker
    from agent.live.config import LiveConfig
    from agent.config import load_config as load_agent_config

    agent_cfg = load_agent_config()
    live = cfg_live or LiveConfig(
        broker_type="mt5",
        mt5_login=int(agent_cfg.mt5_login) if agent_cfg.mt5_login else 0,
        mt5_password=agent_cfg.mt5_password,
        mt5_server=agent_cfg.mt5_server,
        mt5_path=agent_cfg.mt5_path,
    )
    if live.broker_type == "paper":
        raise RuntimeError(
            "--feed mt5 cannot run on the paper broker: PaperBroker "
            "serves a frozen parquet snapshot, not a live tape (I019)."
        )
    if not live.mt5_login or not live.mt5_password:
        raise RuntimeError(
            "--feed mt5 needs MT5 credentials (MT5_LOGIN / MT5_PASSWORD "
            "/ MT5_SERVER in .env). Refusing to fall back to the frozen "
            "paper snapshot (I019)."
        )
    log.info(
        "squad feed broker: %s login=%s server=%s (read-only)",
        live.broker_type, live.mt5_login, live.mt5_server,
    )
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

    field_assignments = parse_field_assignments(
        getattr(args, "field_assign", None),
    )
    roster = build_live_roster(
        symbols,
        parity_mode=args.parity_mode,
        enable_sae=bool(getattr(args, "enable_sae", False)),
        field_assignments=field_assignments,
    )
    source_label = (
        f"live_market:{args.feed}" if args.feed != "cache"
        else "cache_replay"
    )
    # Tier-2 / field-card studies (AN-3 XAGUSD) require equity=500 = the
    # real v2 demo account. Default stays the historic $100 sandbox so
    # majors-only boots are unchanged unless the operator opts in.
    equity = float(getattr(args, "equity", 100.0) or 100.0)
    if field_assignments and equity < 500.0:
        log.warning(
            "field_assignments set but equity=%.0f < 500 — R1 will likely "
            "block Tier-2 min-lot risk (field card). Prefer --equity 500.",
            equity,
        )
    engine = SquadEngine(
        roster,
        out_dir,
        aggregator_arm=args.aggregator,
        notifier=notify_fn,
        source_label=source_label,
        equity=equity,
    )
    if field_assignments:
        log.info(
            "field assignments active: %s (equity=$%.0f)",
            {k: list(v) for k, v in field_assignments.items()},
            equity,
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

    # Resume the mt5 feed cursor from persisted state so the first
    # poll emits every closed bar SINCE the last processed one (bounded
    # by the feed's cache window) instead of only the newest -- H4
    # closes missed across a restart used to be silently skipped.
    if feed_name == "mt5":
        for sym, iso in engine.last_bar_times.items():
            try:
                feed.mark_seen(sym, datetime.fromisoformat(iso))
            except ValueError:
                log.warning("unparseable last_bar_time %s=%r", sym, iso)

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
            status_sink=make_calendar_status_sink(out_dir, notifier),
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
            n_rows=None,  # live feed: no row queue exists (I022)
            out_dir=str(out_dir),
        )

    steps = 0
    # I022: default to "crashed" so an unhandled exception escaping the
    # loop pages honestly instead of masquerading as a clean completion
    # ("done" used to be the default). Every deliberate exit path below
    # overwrites this.
    outcome = "crashed"

    # Feed-outage resilience (I027-era hardening, 2026-08-04): a
    # transient MT5 read error used to escape run_loop and kill the
    # process (the ops watchdog then restart-churned it). Now: bounded
    # exponential backoff, a system_status row on the tape, one page per
    # failure STREAK, and a recovery row when the feed comes back.
    feed_error_streak = 0
    # Staleness latch: if the feed "succeeds" but no closed bar has been
    # seen for > --feed-stale-hours outside the weekend gap (the Aug 3
    # shape: terminal disconnected, cache frozen, loop idling happily),
    # put it on the tape and page once per episode.
    newest_bar_seen: datetime | None = max(
        (b[-1].time for b in warmup.values() if b), default=None,
    )
    for iso in engine.last_bar_times.values():
        try:
            t = datetime.fromisoformat(iso)
            if newest_bar_seen is None or t > newest_bar_seen:
                newest_bar_seen = t
        except ValueError:
            pass
    stale_after_s = float(args.feed_stale_hours) * 3600.0
    feed_stale_alerted = False

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
                try:
                    asyncio.run(feed.refresh())
                except Exception as exc:  # noqa: BLE001 — transient I/O
                    feed_error_streak += 1
                    backoff = min(60.0 * (2 ** min(feed_error_streak - 1, 4)), 900.0)
                    log.warning(
                        "mt5 feed refresh failed (streak=%d, retry in %.0fs): %s",
                        feed_error_streak, backoff, exc,
                    )
                    _emit_system_status(
                        out_dir,
                        {
                            "component": "market_feed",
                            "status": "refresh_error",
                            "failure_streak": feed_error_streak,
                            "retry_in_seconds": backoff,
                            "message": f"mt5 refresh failed: {exc}",
                        },
                        notifier=notifier if feed_error_streak == 1 else None,
                        notify_text=(
                            f"market feed refresh failed ({exc}) — "
                            "retrying with backoff; squad is NOT reading "
                            "new bars until this recovers."
                        ),
                    )
                    engine.write_heartbeat(
                        f"feed_error streak={feed_error_streak}"
                    )
                    time.sleep(backoff)
                    continue
                if feed_error_streak:
                    _emit_system_status(
                        out_dir,
                        {
                            "component": "market_feed",
                            "status": "recovered",
                            "failure_streak": feed_error_streak,
                            "message": "mt5 refresh recovered",
                        },
                        notifier=notifier,
                        notify_text=(
                            f"market feed recovered after "
                            f"{feed_error_streak} failed refresh(es); any "
                            "missed H4 closes will be caught up this poll."
                        ),
                    )
                    feed_error_streak = 0

            new_bars = feed.poll_new_closed()
            if not new_bars:
                engine.write_heartbeat("idle")
                now = datetime.now(tz=timezone.utc)
                if (
                    feed_name == "mt5"
                    and not feed_stale_alerted
                    and newest_bar_seen is not None
                    and stale_after_s > 0
                    and (now - newest_bar_seen).total_seconds() > stale_after_s
                    and not _in_weekend_gap(now)
                ):
                    feed_stale_alerted = True
                    age_h = (now - newest_bar_seen).total_seconds() / 3600.0
                    _emit_system_status(
                        out_dir,
                        {
                            "component": "market_feed",
                            "status": "stale",
                            "newest_bar_time": newest_bar_seen.isoformat(),
                            "age_hours": round(age_h, 2),
                            "threshold_hours": float(args.feed_stale_hours),
                            "message": (
                                f"no closed bar for {age_h:.1f}h outside "
                                "the weekend gap — feed is starving"
                            ),
                        },
                        notifier=notifier,
                        notify_text=(
                            f"squad feed STALE: newest closed bar is "
                            f"{age_h:.1f}h old (threshold "
                            f"{args.feed_stale_hours:.0f}h) and it isn't "
                            "the weekend. Check the MT5 terminal / VM "
                            "network."
                        ),
                    )
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

            batch_newest = max(fb.bar.time for fb in new_bars)
            if newest_bar_seen is None or batch_newest > newest_bar_seen:
                newest_bar_seen = batch_newest
            if feed_stale_alerted:
                feed_stale_alerted = False
                _emit_system_status(
                    out_dir,
                    {
                        "component": "market_feed",
                        "status": "recovered",
                        "newest_bar_time": batch_newest.isoformat(),
                        "message": "closed bars flowing again after staleness",
                    },
                    notifier=notifier,
                    notify_text=(
                        "squad feed recovered — closed bars are flowing "
                        "again (missed closes caught up this poll)."
                    ),
                )

            for pos, fb in enumerate(new_bars):
                # Skip bars already processed (resume).
                last = engine.last_bar_times.get(fb.symbol)
                if last is not None:
                    try:
                        last_dt = datetime.fromisoformat(last)
                        if fb.bar.time <= last_dt:
                            continue
                    except ValueError:
                        pass
                if feed_name == "mt5":
                    # Index-space fix (2026-08-04): fb.bar_index lives
                    # in the mt5 feed's SLIDING lookback window; the
                    # engine's history is append-only. Passing the feed
                    # index into on_bar overwrote historical bars and
                    # picked wrong fill bars once the two spaces
                    # diverged (i.e. from the first live bar onward).
                    # Live path: let the engine assign its own index.
                    # Fill bar: the next newer closed bar for this
                    # symbol in the same poll batch (catch-up case),
                    # else the currently-forming bar's open.
                    next_bar = next(
                        (
                            nb.bar for nb in new_bars[pos + 1:]
                            if nb.symbol == fb.symbol
                        ),
                        None,
                    )
                    if next_bar is None and hasattr(feed, "forming_bar"):
                        next_bar = feed.forming_bar(fb.symbol)
                    tr = engine.on_bar(fb.symbol, fb.bar, next_bar=next_bar)
                else:
                    # cache/fake feeds: indices ARE engine-aligned (the
                    # engine was prepared on the feed's full series).
                    next_bar = None
                    engine._extend_history(fb.symbol, fb.bar)
                    series = engine.bars_by_symbol[fb.symbol]
                    if fb.bar_index + 1 < len(series):
                        next_bar = series[fb.bar_index + 1]
                    tr = engine.on_bar(
                        fb.symbol, fb.bar,
                        bar_index=(
                            fb.bar_index if fb.bar_index < len(series) else None
                        ),
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
            # I022: report the true outcome — the formatter knows
            # "interrupted" and "crashed" now; no more disguising a
            # Ctrl+C as "step budget reached".
            notifier.notify_stop(outcome)
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
        "--field-assign", nargs="+", default=None, metavar="AGENT:SYM",
        help=(
            "widen a proposer's whitelist: agent_id:SYMBOL[,SYMBOL…]. "
            "Example: --field-assign chigiri_hyoma:XAGUSD. Requires the "
            "symbol also in --symbols. Default None = natural homes only."
        ),
    )
    ap.add_argument(
        "--equity", type=float, default=None,
        help=(
            "sandbox equity for Sentinel R1 (default 100; use 500 for "
            "Tier-2 / v2 demo account per field cards)"
        ),
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
        "--feed-stale-hours", type=float,
        default=float(sl.get("feed_stale_hours") or 9.0),
        help=(
            "mt5 feed: page + tape a system_status row when no closed "
            "bar has been seen for this many hours outside the weekend "
            "gap (matches the external tape-freshness watchdog's warn "
            "threshold; 0 disables). Default 9."
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
    if args.field_assign is None and sl.get("field_assignments"):
        # toml table → flatten to CLI-shaped tokens for one parser path
        args.field_assign = [
            f"{aid}:{','.join(syms) if isinstance(syms, (list, tuple)) else syms}"
            for aid, syms in dict(sl["field_assignments"]).items()
        ]
    if args.equity is None:
        args.equity = float(sl["equity"]) if sl.get("equity") is not None else 100.0

    _configure_logging(args.verbose)
    outcome = run_loop(args, cfg)
    print(f"[squad-live] finished: {outcome}")


if __name__ == "__main__":
    main()
