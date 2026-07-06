"""External dead-man's-switch heartbeat pings (e.g. healthchecks.io).

Telegram notifications (see `agent.notifications.telegram`) can only warn
about things the agent process is still alive to report -- a real VM
freeze or hard crash leaves nothing running to send an "Agent OFFLINE"
message. The only way to catch that is an EXTERNAL watchdog: something
outside this process that expects a periodic "I'm alive" ping and raises
its own alarm when one goes missing.

This module pings such a service (any provider compatible with
healthchecks.io's simple GET-to-ping-URL contract; https://healthchecks.io
has a generous free tier and built-in Telegram/email/Slack alert
integrations) once per heartbeat. If the VM wedges, the pings stop and the
external service fires the alert on its own schedule -- no code on this
side needs to survive the freeze for that to work.

Reads `HEALTHCHECK_URL_<SYMBOL>` first (one check per symbol, so one
pair's process hanging doesn't get masked by the other two pairs' pings
against a shared check), falling back to a shared `HEALTHCHECK_URL`.

Public API:

    pinger = HealthcheckPinger.from_env(symbol="EURUSD")
    pinger.ping()                  # "still alive" heartbeat
    pinger.ping_fail("OOM error")  # optional: signal a known failure now,
                                    # instead of waiting for the grace period

Use `dry_run=True` to print instead of hitting the network (tests / local
dev without a real check URL configured).
"""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class HealthcheckConfig:
    url: str = ""
    dry_run: bool = False
    timeout_seconds: float = 5.0

    @classmethod
    def from_env(cls, *, symbol: str = "", dry_run: bool = False) -> "HealthcheckConfig":
        per_symbol = os.getenv(f"HEALTHCHECK_URL_{symbol.upper()}", "") if symbol else ""
        url = (per_symbol or os.getenv("HEALTHCHECK_URL", "")).rstrip("/")
        return cls(url=url, dry_run=dry_run)

    @property
    def configured(self) -> bool:
        return bool(self.url) or self.dry_run


# ---------------------------------------------------------------------------
# Pinger
# ---------------------------------------------------------------------------


class HealthcheckPinger:
    """Pings an external dead-man's-switch URL.

    Fails open, same contract as `TelegramNotifier`: a broken network or a
    missing URL logs (at debug, not warning -- most deployments won't have
    this configured, and that's fine) but never raises. A failed heartbeat
    ping must never be able to crash the live loop it's supposed to be
    watching.
    """

    def __init__(self, config: HealthcheckConfig | None = None, *, client=None):
        self.config = config or HealthcheckConfig()
        self._client = client

    @classmethod
    def from_env(cls, *, symbol: str = "", dry_run: bool = False) -> "HealthcheckPinger":
        return cls(HealthcheckConfig.from_env(symbol=symbol, dry_run=dry_run))

    # ---- public ------------------------------------------------------

    def ping(self) -> bool:
        """Send a plain success heartbeat."""
        return self._send()

    def ping_start(self) -> bool:
        """Optional: signal the start of a run (healthchecks.io `/start`)."""
        return self._send("start")

    def ping_fail(self, message: str = "") -> bool:
        """Signal a known failure immediately (healthchecks.io `/fail`)
        instead of waiting for the check's grace period to expire."""
        return self._send("fail", body=message)

    # ---- internals -----------------------------------------------------

    def _send(self, suffix: str = "", body: str = "") -> bool:
        label = f"ping{'/' + suffix if suffix else ''}"
        if self.config.dry_run:
            sys.stdout.write(f"[healthcheck] {label} {body}\n".rstrip() + "\n")
            sys.stdout.flush()
            return True
        if not self.config.configured:
            log.debug("Healthcheck not configured (HEALTHCHECK_URL missing); skipping %s", label)
            return False
        url = self.config.url + (f"/{suffix}" if suffix else "")
        try:
            client = self._client or self._default_client()
            if body:
                resp = client.post(url, content=body.encode(), timeout=self.config.timeout_seconds)
            else:
                resp = client.get(url, timeout=self.config.timeout_seconds)
            ok = getattr(resp, "status_code", 0) // 100 == 2
            if not ok:
                log.warning("Healthcheck %s returned %s: %s", label,
                            getattr(resp, "status_code", "?"), getattr(resp, "text", ""))
            return bool(ok)
        except Exception as e:
            # Never raise -- a watchdog ping failing must not take down the
            # thing it's watching.
            log.warning("Healthcheck %s failed: %s", label, e)
            return False

    @staticmethod
    def _default_client():
        import httpx  # type: ignore
        return httpx.Client(timeout=5.0)


__all__ = ["HealthcheckConfig", "HealthcheckPinger"]
