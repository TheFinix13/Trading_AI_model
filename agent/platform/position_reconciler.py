"""Position-lifecycle reconciliation (F025 B6 + B8).

Two blockers turn out to be one problem. B6 says the risk budget is
inert: ``record_fill`` is called with ``pnl=0.0`` at fill time, which is
locally correct -- nothing is realised at the moment of the fill -- but
nothing ever records the loss when the position CLOSES, so
``_today_losses`` sums to zero forever and all three caps report full
headroom permanently. B8 says there is no aggregate exposure cap.

Neither is fixable by arithmetic, because the platform cannot currently
observe that a position ended. A stop-out executes at the broker; MT5
closes the position server-side and never calls back into this code.
The only closes this platform knows about are the ones it performed
itself through ``close_executed_position``, and those are the minority
that matter least -- a voluntary close is usually a small loss or a
win, while the stop-out is the full worst-case loss the daily cap exists
to limit.

So the fix for both is the same: ask the broker which of our tickets are
still open, and charge the ones that are not against the budget. That
makes B6's cap real and simultaneously supplies the true open-risk total
B8 needs, since anything still open is still at risk.

Scope discipline: only tickets recorded ``filled`` in this executor's
own ``executions.jsonl`` are ever considered, and ``open_tickets``
filters by magic number. The v1 zones agent trades the same account on
the same terminal, and its positions must be invisible here -- the same
reason ``_closable_fill`` refuses tickets absent from the audit log.
"""

from __future__ import annotations

import logging

from agent.platform import live_executor, risk_budget

LOGGER = logging.getLogger(__name__)


def _open_fills() -> dict[int, dict]:
    """Tickets this executor filled and has NOT recorded as closed.

    Later rows win, so a `closed` row retires the ticket. Rows without a
    usable ticket are skipped rather than raising.
    """
    fills: dict[int, dict] = {}
    for row in live_executor._execution_rows():
        try:
            ticket = int(row["ticket"])
        except (KeyError, TypeError, ValueError):
            continue
        status = row.get("status")
        if status == "filled":
            fills[ticket] = row
        elif status in ("closed", "reconciled_closed"):
            fills.pop(ticket, None)
    return fills


def open_risk() -> float:
    """Total worst-case loss committed to positions still believed open.

    This is the figure B8's aggregate cap consumes. It is only as fresh
    as the last ``reconcile`` call: without reconciliation it never
    decreases, so the cap would jam shut after a couple of trades rather
    than fail open. Jamming shut is the safe direction, but it is a
    malfunction, not the design -- see the module docstring.

    Rows predating F025 B6 carry no ``worst_case_loss`` and contribute
    0.0, which understates exposure. That is accepted only because such
    rows can exist solely on a book that never had a working cap anyway.
    """
    total = 0.0
    for row in _open_fills().values():
        try:
            wcl = float(row.get("worst_case_loss") or 0.0)
        except (TypeError, ValueError):
            continue
        if wcl > 0:
            total += wcl
    return total


def reconcile(adapter, magic: int = live_executor.DEFAULT_MAGIC) -> dict:
    """Charge every externally-closed position against the risk budget.

    Returns ``{ok, checked, closed, recorded, skipped, errors}``.

    Fail-quiet by design: if the broker cannot be reached, this returns
    ``ok=False`` and changes nothing. It must never guess that a
    position closed, because recording a phantom loss would consume
    budget that is still available, and recording a phantom close would
    drop a live position out of ``open_risk`` and let the aggregate cap
    over-admit.
    """
    result = {"ok": False, "checked": 0, "closed": 0, "recorded": 0,
              "skipped": 0, "errors": []}
    fills = _open_fills()
    result["checked"] = len(fills)
    if not fills:
        result["ok"] = True
        return result

    try:
        still_open = adapter.open_tickets(magic)
    except Exception as exc:
        result["errors"].append(f"open_tickets failed: {exc!s:.120}")
        return result
    if still_open is None:
        result["errors"].append("open_tickets returned None")
        return result

    result["ok"] = True
    for ticket, row in fills.items():
        if ticket in still_open:
            continue
        result["closed"] += 1
        try:
            profit = adapter.closed_deal_profit(ticket)
        except Exception as exc:
            result["errors"].append(
                f"closed_deal_profit({ticket}) failed: {exc!s:.120}")
            result["skipped"] += 1
            continue
        if profit is None:
            # "No history" is not "no loss". Leaving the ticket in
            # `filled` means it is retried next pass and keeps counting
            # toward open risk meanwhile -- conservative in both
            # directions.
            result["skipped"] += 1
            LOGGER.warning(
                "ticket %s is closed at the broker but has no deal "
                "history; leaving it open for the next pass", ticket)
            continue

        # SIGNED pnl, not a pre-converted loss: `_scan_today_losses`
        # keeps only negative rows and negates them itself, so passing a
        # positive "loss" here would read as a win and charge nothing.
        # That also means wins need no special handling -- the scanner
        # skips them, so they cannot mint budget.
        risk_budget.record_fill(str(row.get("symbol") or ""),
                                str(row.get("source_agent") or "unknown"),
                                float(profit))
        live_executor._append_execution({
            "at": live_executor._iso_now(),
            "approval_id": row.get("approval_id"),
            "symbol": row.get("symbol"),
            "side": row.get("side"),
            "volume": row.get("volume"),
            "status": "reconciled_closed",
            "reason": f"closed at broker; realised {profit:+.2f}",
            "ticket": ticket,
            "magic": row.get("magic"),
            "source_agent": row.get("source_agent"),
            "worst_case_loss": row.get("worst_case_loss"),
            "realised_pnl": float(profit),
        })
        result["recorded"] += 1
        LOGGER.info("reconciled ticket %s: realised %+.2f", ticket, profit)
    return result
