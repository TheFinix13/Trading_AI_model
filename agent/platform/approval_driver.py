"""Background clock for the approval refusal window (F025 B1).

`approval_queue.timeout_reap` is invoked lazily -- by `can_send_order`,
`list_entries` and `_resolve`. That is sufficient when operator inaction
means "discard", because a discarded proposal needs no timely action:
whenever the reap eventually runs, the outcome is the same.

It is NOT sufficient once inaction means "execute". With nothing polling,
a 30-minute refusal window would not resolve at 30 minutes; it would
resolve the next time an HTTP request happened to touch the queue -- so
proposals would fire *when the operator opened the dashboard* and never
while the machine was unattended. That is the exact inverse of the
intended behaviour, and it is why this module exists.

The driver owns two responsibilities and nothing else:

1. Give `timeout_reap` a real clock.
2. Hand every entry that reached `auto_approved` to the executor.

It deliberately does NOT re-implement any gate. `execute_approved`
re-runs the full four-gate stack fresh immediately before send, so a
kill-switch trip, a live-mode flip, or an exhausted risk budget between
reap and send still refuses. The driver's job is to *offer* the entry,
not to decide it is safe.
"""

from __future__ import annotations

import logging
import threading

from agent.platform import approval_queue

LOGGER = logging.getLogger(__name__)

DEFAULT_TICK_SECONDS: float = 15.0

_THREAD: threading.Thread | None = None
_STOP = threading.Event()
_LOCK = threading.RLock()
_TICK_SECONDS: float = DEFAULT_TICK_SECONDS
_ADAPTER_FACTORY = None


def _default_adapter_factory():
    # Imported lazily: the executor pulls in the MT5 bindings, which are
    # absent on the research/dev boxes where this module is imported for
    # tests.
    from agent.platform import live_executor
    return live_executor.RealMt5OrderAdapter()


def tick(adapter_factory=None) -> list[dict]:
    """Resolve elapsed windows and execute whatever auto-approved.

    Returns one result dict per execution attempt. Safe to call directly
    (the tests drive it this way rather than waiting on wall-clock).
    """
    resolved = approval_queue.timeout_reap()
    if not resolved:
        return []

    # Only entries the reap moved to `auto_approved` are ours to send. A
    # `timed_out` or `approval_expired` id in this list is a discard.
    to_send = []
    for approval_id in resolved:
        entry = approval_queue.get_entry(approval_id)
        if entry is not None and entry.get("status") == "auto_approved":
            to_send.append(approval_id)
    if not to_send:
        return []

    factory = adapter_factory or _ADAPTER_FACTORY or _default_adapter_factory
    results: list[dict] = []
    for approval_id in to_send:
        try:
            from agent.platform import live_executor
            result = live_executor.execute_approved(approval_id,
                                                    factory())
        except Exception:
            # One bad entry must never take the driver thread down --
            # that would silently strand every later proposal in
            # `pending` with no clock.
            LOGGER.exception(
                "auto-execution raised for %s; driver continuing",
                approval_id)
            results.append({"ok": False, "approval_id": approval_id,
                            "status": "driver_error"})
            continue
        LOGGER.info("auto-executed %s -> %s (%s)", approval_id,
                    result.get("status"), result.get("reason"))
        results.append(result)
    return results


def _run() -> None:
    while not _STOP.wait(_TICK_SECONDS):
        try:
            tick()
        except Exception:
            LOGGER.exception("approval driver tick failed; continuing")


def start(tick_seconds: float | None = None,
          adapter_factory=None) -> bool:
    """Start the driver thread. Idempotent -- returns False if already
    running."""
    global _THREAD, _TICK_SECONDS, _ADAPTER_FACTORY
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return False
        if tick_seconds is not None:
            _TICK_SECONDS = max(1.0, float(tick_seconds))
        _ADAPTER_FACTORY = adapter_factory
        _STOP.clear()
        _THREAD = threading.Thread(target=_run, name="approval-driver",
                                   daemon=True)
        _THREAD.start()
    LOGGER.info("approval driver started (tick=%.1fs, auto_execute=%s)",
                _TICK_SECONDS, approval_queue.get_auto_execute_on_timeout())
    return True


def stop(timeout: float = 5.0) -> None:
    global _THREAD
    with _LOCK:
        thread = _THREAD
        _THREAD = None
    _STOP.set()
    if thread is not None and thread.is_alive():
        thread.join(timeout=timeout)


def is_running() -> bool:
    with _LOCK:
        return _THREAD is not None and _THREAD.is_alive()
