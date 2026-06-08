"""Online performance memory — lightweight, present-time learning.

Tracks realised expectancy / win-rate per *setup signature* and turns that into
a conviction adjustment that is fed back into sizing and the reaction/anticipation
decision. The agent therefore literally leans into the setups that have been
working since it started running and de-weights the ones that haven't — without
waiting for a heavy offline scorer retrain.

A setup signature is the tuple that meaningfully partitions edge:

    strategy | direction | session | htf_aligned | source(reaction|anticipation)

State persists to a single JSON file so learning survives restarts. The heavier
follow-on (full ML scorer retraining on the captured feature snapshots) is
documented separately; this is the always-on, day-to-day adaptation.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class SignatureStats:
    wins: int = 0
    losses: int = 0
    sum_r: float = 0.0          # sum of R-multiples (signed)
    sum_r_win: float = 0.0
    sum_r_loss: float = 0.0     # always <= 0
    last_r: float = 0.0

    @property
    def n(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> float:
        return (self.wins / self.n) if self.n else 0.0

    @property
    def expectancy_r(self) -> float:
        """Average R per trade (the core 'is it working' number)."""
        return (self.sum_r / self.n) if self.n else 0.0

    def record(self, r_multiple: float) -> None:
        self.sum_r += r_multiple
        self.last_r = r_multiple
        if r_multiple > 0:
            self.wins += 1
            self.sum_r_win += r_multiple
        else:
            self.losses += 1
            self.sum_r_loss += r_multiple


def make_signature(
    strategy: str,
    direction: str,
    session: str,
    htf_aligned: bool | None,
    source: str,
) -> str:
    """Build a stable signature key. ``source`` is 'reaction' or 'anticipation'."""
    htf = "htfNA" if htf_aligned is None else ("htfAlign" if htf_aligned else "htfMiss")
    sess = (session or "unknown").lower().replace(" ", "_")
    return f"{strategy or 'generic'}|{direction.lower()}|{sess}|{htf}|{source}"


class PerformanceMemory:
    """Per-signature expectancy with a bounded conviction feedback term."""

    def __init__(
        self,
        path: Path | str | None = None,
        *,
        min_samples: int = 4,
        max_adjustment: float = 0.20,
        autosave: bool = True,
    ):
        """``max_adjustment`` bounds the conviction delta (e.g. ±0.20). Below
        ``min_samples`` the signature contributes no adjustment (not enough
        evidence yet)."""
        self.path = Path(path) if path else None
        self.min_samples = min_samples
        self.max_adjustment = max_adjustment
        self.autosave = autosave
        self._table: dict[str, SignatureStats] = {}
        if self.path and self.path.exists():
            self.load()

    # ------------------------------------------------------------------
    def record(self, signature: str, r_multiple: float) -> SignatureStats:
        stats = self._table.setdefault(signature, SignatureStats())
        stats.record(r_multiple)
        if self.autosave and self.path:
            self.save()
        return stats

    def get(self, signature: str) -> SignatureStats:
        return self._table.get(signature, SignatureStats())

    def conviction_adjustment(self, signature: str) -> float:
        """Return a bounded conviction delta for this signature.

        Positive when the signature has been profitable (expectancy > 0),
        negative when it's been bleeding. Scaled by a sample-size confidence
        factor so a handful of trades nudge gently and a long track record
        applies the full adjustment.
        """
        stats = self._table.get(signature)
        if stats is None or stats.n < self.min_samples:
            return 0.0
        # Confidence ramps from 0 at min_samples to 1.0 by ~20 trades.
        confidence = min(1.0, stats.n / 20.0)
        # Squash expectancy (typically within ±2R) into [-1, 1].
        exp = stats.expectancy_r
        squashed = max(-1.0, min(1.0, exp / 1.0))
        return round(squashed * confidence * self.max_adjustment, 4)

    def summary_rows(self) -> list[dict]:
        rows = []
        for sig, st in sorted(
            self._table.items(), key=lambda kv: kv[1].expectancy_r, reverse=True
        ):
            rows.append(
                {
                    "signature": sig,
                    "n": st.n,
                    "win_rate": round(st.win_rate, 3),
                    "expectancy_r": round(st.expectancy_r, 3),
                    "adjustment": self.conviction_adjustment(sig),
                }
            )
        return rows

    # ------------------------------------------------------------------
    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text())
            self._table = {
                k: SignatureStats(**v) for k, v in data.get("signatures", {}).items()
            }
            log.info("Loaded performance memory: %d signatures from %s",
                     len(self._table), self.path)
        except Exception as e:  # corrupt / partial file — start fresh
            log.warning("Could not load performance memory (%s); starting fresh", e)
            self._table = {}

    def save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "signatures": {k: asdict(v) for k, v in self._table.items()},
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(self.path)

    def __len__(self) -> int:
        return len(self._table)
