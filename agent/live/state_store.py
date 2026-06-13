"""Crash-resilient atomic JSON sidecar for live-agent state persistence.

Each live process writes a single file:

    {log_dir}/{SYMBOL}/state.json

This is the same directory that holds the daily log files, so the sidecar
travels with the logs. One file per symbol; only ever one process per symbol
(per the live runbook), so no multi-process locking is needed.

Schema versioned at 1. The file is written atomically via a tmp file +
``os.replace`` — a crash during the write leaves the previous file intact.
Errors during save are caught and logged; errors during load fall back to
"no prior state" so the live loop always starts cleanly.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

_SCHEMA_VERSION = 1


class StateStore:
    """Atomic JSON sidecar — load once at startup, save on every state change.

    Parameters
    ----------
    path:
        Absolute path to the ``state.json`` file.  The parent directory is
        created on first save.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> dict | None:
        """Read and return the persisted state dict.

        Returns ``None`` (with a WARNING log) when the file is missing,
        corrupt, or carries an unexpected schema version — all callers
        treat ``None`` as "no prior state / start fresh".
        """
        if not self.path.exists():
            return None
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            log.warning(
                "[STATE LOADED] corrupt state file %s (%s) — starting fresh",
                self.path, exc,
            )
            return None
        if not isinstance(data, dict):
            log.warning(
                "[STATE LOADED] state file is not a JSON object — starting fresh"
            )
            return None
        if data.get("schema") != _SCHEMA_VERSION:
            log.warning(
                "[STATE LOADED] schema mismatch (got %r, want %d) in %s — starting fresh",
                data.get("schema"), _SCHEMA_VERSION, self.path,
            )
            return None
        log.info(
            "[STATE LOADED] restored from %s (saved_at=%s)",
            self.path, data.get("saved_at", "?"),
        )
        return data

    def save(self, data: dict) -> None:
        """Write *data* atomically.

        Creates parent directories if they do not exist.  Writes to a
        ``.tmp`` sibling first, then ``os.replace``-s it into place — a
        crash mid-write leaves the previous good file intact.  Any
        exception is caught and logged; the live loop must never crash on
        a disk hiccup.
        """
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            os.replace(tmp, self.path)
        except Exception as exc:
            log.warning("[STATE SAVE FAILED] %s: %s", self.path, exc)
