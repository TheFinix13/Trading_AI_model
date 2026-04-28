"""Weekly retraining job: refit scorer on rolling window incl. live trades, validate, deploy or rollback."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from agent.config import Config, load_config
from agent.journal.db import Journal
from agent.model.scorer import SetupScorer, train_scorer

log = logging.getLogger(__name__)


def _load_trades_from_journal(journal: Journal, since: datetime | None = None) -> list:
    rows = journal.all_trades()
    return rows  # NOTE: returns dict rows; production trainer reconstructs from features json


def retrain(cfg: Config | None = None) -> dict:
    """Retrain on the last N months of trades. Validate against the previous active model.
    Activate the new model if validation log-loss is better; otherwise rollback (keep old)."""
    cfg = cfg or load_config()
    journal = Journal(cfg.journal_db)

    rows = journal.all_trades()
    closed = [r for r in rows if r.get("exit_price") is not None]
    if len(closed) < 50:
        log.info("Not enough closed trades to retrain (n=%d)", len(closed))
        return {"status": "skipped", "reason": "insufficient_data", "n_trades": len(closed)}

    log.info("Retraining on %d trades", len(closed))

    from agent.types import Trade as _T  # for type hint only
    raise NotImplementedError(
        "Retrainer needs feature-vector reconstruction from journal rows. "
        "See scripts/weekly_retrain.py for the full pipeline that pairs trades with their feature vectors."
    )
