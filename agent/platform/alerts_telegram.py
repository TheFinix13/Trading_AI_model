"""F014 -- Telegram bridge for the alerts bus.

Sends a Telegram message on each event whose type is enabled in the
`[alerts.telegram]` config block. Reuses the existing `[telegram]`
`bot_token` / `chat_id` from `platform.toml` -- F014 does NOT add a
new secret.

Ops split (CEO requirement 2026-07-24): company/ops alerts route to a
SEPARATE Telegram destination configured via `[alerts.telegram.ops]`
(its own bot_token + chat_id). Routing matrix:

- `OPS_EVENTS` (watchdog_alert) -> ops destination; falls back to
  the primary destination when the ops block is absent/disabled
  (better a mis-channeled alert than a dropped one).
- `DUAL_ROUTE_EVENTS` (kill_switch_trip, platform_down) -> BOTH
  destinations (safety events deserve redundancy).
- All other trading events -> primary destination only.

Fail-closed: any missing bot_token / chat_id, or a disabled config
block, short-circuits `send()` and returns False. The ops destination
has identical semantics via `ops_is_enabled()`. Real Telegram calls
are gated on those checks; tests mock `httpx.post`.
"""
from __future__ import annotations

import logging
import threading
from copy import deepcopy

from agent.platform import alerts

TELEGRAM_API_BASE: str = "https://api.telegram.org/bot"

# Ops-class events -- route to the [alerts.telegram.ops] destination.
# Future company/ops event types get added HERE (and only here) so the
# routing decision stays a one-line diff.
OPS_EVENTS: frozenset[str] = frozenset({
    "watchdog_alert",
})

# Safety-class events -- routed to BOTH destinations (redundancy over
# deduplication; a kill-switch trip or platform outage must reach the
# operator wherever they are looking).
DUAL_ROUTE_EVENTS: frozenset[str] = frozenset({
    "kill_switch_trip",
    "platform_down",
})

_DEFAULT_PER_EVENT: dict[str, bool] = {
    "trade_fill": True,
    "stop_hit": True,
    "kill_switch_trip": True,
    "risk_budget_breach": True,
    "approval_submitted": False,
    "platform_down": True,
    # F017 -- an ops alarm is exactly what Telegram is for.
    "watchdog_alert": True,
}

_LOG = logging.getLogger(__name__)

_LOCK = threading.RLock()
_STATE: dict = {
    "enabled": False,
    "bot_token": "",
    "chat_id": "",
    "per_event": dict(_DEFAULT_PER_EVENT),
    "subscription_id": None,
    # [alerts.telegram.ops] -- separate destination for ops alerts.
    "ops_enabled": False,
    "ops_bot_token": "",
    "ops_chat_id": "",
}


def configure(bot_token: str, chat_id: str,
              per_event: dict[str, bool] | None = None,
              enabled: bool = True) -> None:
    """Set the bridge config in-place. Idempotent."""
    with _LOCK:
        _STATE["bot_token"] = str(bot_token or "")
        _STATE["chat_id"] = str(chat_id or "")
        # Merge over defaults so an override for a subset is fine.
        merged = dict(_DEFAULT_PER_EVENT)
        for k, v in (per_event or {}).items():
            if k in _DEFAULT_PER_EVENT:
                merged[k] = bool(v)
        _STATE["per_event"] = merged
        _STATE["enabled"] = bool(enabled)


def configure_ops(bot_token: str, chat_id: str,
                  enabled: bool = True) -> None:
    """Set the ops-destination config in-place. Idempotent.

    Mirrors `configure()` fail-closed semantics: the ops destination
    only fires when enabled AND bot_token AND chat_id are all set."""
    with _LOCK:
        _STATE["ops_bot_token"] = str(bot_token or "")
        _STATE["ops_chat_id"] = str(chat_id or "")
        _STATE["ops_enabled"] = bool(enabled)


def load_config() -> dict:
    """Snapshot the current config (shape mirrors [alerts.telegram]).

    NEVER echoes raw bot_token / chat_id values -- boolean
    `*_configured` flags only (pinned Legal rolling constraint; the
    pin covers the ops block too)."""
    with _LOCK:
        return {
            "enabled": bool(_STATE["enabled"]),
            "bot_token_configured": bool(_STATE["bot_token"]),
            "chat_id_configured": bool(_STATE["chat_id"]),
            "per_event": dict(_STATE["per_event"]),
            "ops": {
                "enabled": bool(_STATE["ops_enabled"]),
                "bot_token_configured": bool(_STATE["ops_bot_token"]),
                "chat_id_configured": bool(_STATE["ops_chat_id"]),
            },
        }


def is_enabled() -> bool:
    """True iff the config block is enabled AND we have both a
    bot_token and a chat_id."""
    with _LOCK:
        return bool(
            _STATE["enabled"]
            and _STATE["bot_token"]
            and _STATE["chat_id"]
        )


def ops_is_enabled() -> bool:
    """True iff the ops block is enabled AND has both its own
    bot_token and chat_id (fail-closed, same as `is_enabled`)."""
    with _LOCK:
        return bool(
            _STATE["ops_enabled"]
            and _STATE["ops_bot_token"]
            and _STATE["ops_chat_id"]
        )


def _format_message(event: dict) -> str:
    ev_type = event.get("type", "unknown")
    payload = event.get("payload", {})
    lines = [f"[{ev_type}] {event.get('ts', '')}"]
    for k, v in payload.items():
        lines.append(f"  {k}: {v}")
    return "\n".join(lines)


def _destinations(ev_type: str) -> list[tuple[str, str]]:
    """Resolve the `(bot_token, chat_id)` destinations for an event
    type per the routing matrix. Only enabled destinations are
    returned (fail-closed); an empty list means drop the event.

    - OPS_EVENTS -> ops destination; primary FALLBACK when the ops
      block is absent/disabled (never silently dropped just because
      the second bot isn't set up yet).
    - DUAL_ROUTE_EVENTS -> every enabled destination.
    - everything else (trading events) -> primary only.
    """
    with _LOCK:
        primary = ((_STATE["bot_token"], _STATE["chat_id"])
                   if is_enabled() else None)
        ops = ((_STATE["ops_bot_token"], _STATE["ops_chat_id"])
               if ops_is_enabled() else None)
    if ev_type in OPS_EVENTS:
        if ops is not None:
            return [ops]
        return [primary] if primary is not None else []
    if ev_type in DUAL_ROUTE_EVENTS:
        return [d for d in (primary, ops) if d is not None]
    return [primary] if primary is not None else []


def _post_message(bot_token: str, chat_id: str, text: str,
                  client=None) -> bool:
    payload = {"chat_id": chat_id, "text": text}
    url = f"{TELEGRAM_API_BASE}{bot_token}/sendMessage"
    try:
        if client is None:
            import httpx  # local import so the module loads without httpx
            client = httpx
        resp = client.post(url, json=payload, timeout=5.0)
        return getattr(resp, "status_code", 500) == 200
    except Exception:
        _LOG.exception("alerts_telegram: failed to post event")
        return False


def send(event: dict, client=None) -> bool:
    """Send a single event via Telegram, routed per the module-level
    matrix (OPS_EVENTS / DUAL_ROUTE_EVENTS / trading default).
    Returns True when at least one destination accepted the message."""
    ev_type = event.get("type", "")
    with _LOCK:
        per_event = dict(_STATE["per_event"])
    if not per_event.get(ev_type, False):
        return False
    destinations = _destinations(ev_type)
    if not destinations:
        return False
    text = _format_message(event)
    delivered = False
    for bot_token, chat_id in destinations:
        if _post_message(bot_token, chat_id, text, client=client):
            delivered = True
    return delivered


def start(client=None) -> str | None:
    """Attach a subscription that routes bus events to Telegram.

    Returns the subscription id (or None if no destination is
    enabled). Idempotent -- calling twice replaces the previous
    subscription."""
    stop()
    if not (is_enabled() or ops_is_enabled()):
        return None

    def _on_event(ev: dict) -> None:
        send(ev, client=client)

    sub_id = alerts.subscribe(_on_event)
    with _LOCK:
        _STATE["subscription_id"] = sub_id
    return sub_id


def stop() -> None:
    with _LOCK:
        sub_id = _STATE.get("subscription_id")
        _STATE["subscription_id"] = None
    if sub_id:
        alerts.unsubscribe(sub_id)


def reset() -> None:  # claim-exempt: test-only
    stop()
    with _LOCK:
        _STATE["enabled"] = False
        _STATE["bot_token"] = ""
        _STATE["chat_id"] = ""
        _STATE["per_event"] = dict(_DEFAULT_PER_EVENT)
        _STATE["ops_enabled"] = False
        _STATE["ops_bot_token"] = ""
        _STATE["ops_chat_id"] = ""


def snapshot() -> dict:  # claim-exempt: test-only internal state
    with _LOCK:
        return deepcopy(_STATE)


__all__ = [
    "TELEGRAM_API_BASE",
    "OPS_EVENTS",
    "DUAL_ROUTE_EVENTS",
    "configure",
    "configure_ops",
    "load_config",
    "is_enabled",
    "ops_is_enabled",
    "send",
    "start",
    "stop",
    "reset",
]
