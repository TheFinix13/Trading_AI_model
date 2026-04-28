"""Live/paper agent loop. Connects to MT5, polls bars, evaluates rules+ML, places orders.

Modes (set in .env):
  paper - connects to a demo account
  live  - connects to a real account
Both use the same code path; only the MT5 account differs.

Run with:
  AGENT_MODE=paper python scripts/run_live.py
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent.config import load_config
from agent.data.loader import BarLoader, df_to_bars
from agent.execution.executor import make_executor
from agent.features.extractor import extract_features
from agent.journal.db import Journal
from agent.model.scorer import SetupScorer
from agent.risk.manager import RiskDecision, RiskManager
from agent.rules.engine import RuleEngine
from agent.types import Timeframe
from agent.utils import kill_switch_active

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("run_live")


def load_active_scorer(cfg, journal: Journal) -> SetupScorer | None:
    active = journal.active_model()
    if not active:
        log.info("No active model registered; running rules-only")
        return None
    path = Path(active["file_path"])
    if not path.exists():
        log.warning("Active model file missing: %s", path)
        return None
    try:
        scorer = SetupScorer.load(path)
        log.info("Loaded active scorer version=%s", active["version"])
        return scorer
    except Exception as e:
        log.warning("Failed to load scorer: %s", e)
        return None


def main():
    cfg = load_config()
    if cfg.mode not in ("paper", "live"):
        log.error("AGENT_MODE must be 'paper' or 'live' for this script (got %s)", cfg.mode)
        return

    if cfg.mode == "live":
        log.warning("=" * 60)
        log.warning("LIVE MODE - REAL MONEY. Verify guardrails before continuing.")
        log.warning("Daily DD halt: %.1f%%", cfg.risk.daily_dd_halt_pct * 100)
        log.warning("Lot hard cap (under $300): %.2f", cfg.risk.lot_hard_cap_under_300)
        log.warning("=" * 60)

    journal = Journal(cfg.journal_db)
    loader = BarLoader(cache_root=cfg.data_dir)
    engine = RuleEngine(cfg)
    risk = RiskManager(cfg)
    executor = make_executor(cfg.mode)
    scorer = load_active_scorer(cfg, journal)

    tf = Timeframe(cfg.primary_timeframe)
    poll_seconds = max(60, tf.minutes * 60 // 4)  # poll 4x per bar
    last_processed_bar_time: datetime | None = None

    log.info("Starting %s loop on %s %s, polling every %ds", cfg.mode, cfg.symbol, tf.value, poll_seconds)

    while True:
        try:
            if kill_switch_active(cfg.kill_switch_file):
                log.warning("Kill switch active - sleeping")
                time.sleep(30)
                continue

            end = datetime.now(tz=timezone.utc)
            start = end - timedelta(days=120)
            df = loader.get(cfg.symbol, tf, start, end, refresh=True)
            bars = df_to_bars(df, tf)
            if len(bars) < 100:
                log.warning("Insufficient bars (%d), waiting", len(bars))
                time.sleep(poll_seconds)
                continue

            cur = bars[-2] if len(bars) >= 2 else bars[-1]  # most recently CLOSED bar
            if last_processed_bar_time == cur.time:
                time.sleep(poll_seconds)
                continue

            balance = executor.account_balance() or cfg.demo.start_balance
            open_pos = executor.open_positions(cfg.symbol)
            n_open = len(open_pos)

            journal.log_equity(end, balance, balance, n_open, mode=cfg.mode)

            setup = engine.evaluate(bars[:-1], len(bars) - 2)
            if setup is not None:
                setup.features = extract_features(setup, bars[:-1], len(bars) - 2)
                ml_score = None
                if scorer is not None:
                    ml_score = scorer(setup.features)
                    setup.ml_score = ml_score
                    if ml_score < cfg.ml.prob_threshold:
                        journal.log_signal(setup, cfg.symbol, "skip_ml", f"score {ml_score:.3f} < {cfg.ml.prob_threshold}", ml_score=ml_score)
                        last_processed_bar_time = cur.time
                        time.sleep(poll_seconds)
                        continue

                decision = risk.evaluate(setup=setup, account_balance=balance, open_positions=n_open, now=end)

                if decision.decision != RiskDecision.APPROVED:
                    journal.log_signal(setup, cfg.symbol, decision.decision, decision.reason,
                                       lot_size=decision.lot_size, actual_risk_pct=decision.actual_risk_pct,
                                       ml_score=ml_score)
                    log.info("Setup rejected: %s (%s)", decision.decision, decision.reason)
                else:
                    sig_id = journal.log_signal(setup, cfg.symbol, decision.decision, "",
                                                lot_size=decision.lot_size, actual_risk_pct=decision.actual_risk_pct,
                                                ml_score=ml_score)
                    log.info("Placing order: dir=%s lot=%s entry=%.5f sl=%.5f tp=%.5f",
                             setup.direction.value, decision.lot_size, setup.entry, setup.stop, setup.take_profit)
                    res = executor.place_market_order(setup, decision.lot_size, cfg.symbol)
                    if not res.accepted:
                        log.error("Order rejected: %s", res.message)
                    else:
                        log.info("Order accepted: ticket=%s fill=%.5f", res.ticket, res.fill_price)

            last_processed_bar_time = cur.time
            time.sleep(poll_seconds)

        except KeyboardInterrupt:
            log.info("Interrupted, shutting down")
            break
        except Exception as e:
            log.exception("Loop error: %s", e)
            time.sleep(60)


if __name__ == "__main__":
    main()
