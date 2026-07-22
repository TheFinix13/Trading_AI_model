"""F009 -- per-install-token rate limiter.

Token-bucket algorithm, one bucket per install-token (keyed by the
fingerprint so we never handle the raw token here). Applied on every
``/api/*`` non-localhost request as the second gate after the F006
install-token check.

Public API::

    check(token_key)               -> tuple[bool, float]
    reset(token_key=None)          -> None
    set_config(capacity, refill_per_sec) -> None
    get_config()                   -> dict

Default: 60 requests per minute per install-token. Any request that
would drain the bucket below zero is rejected with ``(False,
retry_after_seconds)``. The server maps that to ``429 Too Many
Requests`` with a ``Retry-After`` header.

Buckets are per-process, single-user install per D052. Testing
uses ``reset()`` between cases; the config helper is called at server
start from ``platform.toml`` ``[rate_limit]``.

Security invariants (pinned by tests/security/test_rate_limiter.py):

1. **Per-token isolation.** Two different token_keys never share a
   bucket. Presenting a valid token from a different install may not
   accidentally drain another install's budget.
2. **Monotonic retry-after.** The next retry_after never exceeds the
   configured refill window.
3. **No token leakage.** Bucket keys are the FINGERPRINT (F006
   `install_token_fingerprint`), never the raw token; nothing in this
   module writes to a log.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

DEFAULT_CAPACITY: int = 60             # 60 requests
DEFAULT_REFILL_PER_SEC: float = 1.0    # 60/min = 1/sec
_MIN_REFILL_PER_SEC: float = 1.0 / 3600.0   # ceiling of one refill per hour
_MAX_CAPACITY: int = 10_000


@dataclass
class _Bucket:
    tokens: float
    updated_at: float


_lock = threading.Lock()
_buckets: dict[str, _Bucket] = {}
_capacity: int = DEFAULT_CAPACITY
_refill_per_sec: float = DEFAULT_REFILL_PER_SEC


def set_config(*, capacity: int | None = None,
               refill_per_sec: float | None = None,
               requests_per_minute: int | None = None) -> None:
    """Reconfigure the bucket size / refill rate.

    ``requests_per_minute`` is a convenience — sets both ``capacity``
    (bursts allowed) and ``refill_per_sec`` (steady state) to the same
    per-minute figure. Explicit ``capacity`` / ``refill_per_sec`` win
    when both are provided.

    Bucket state is preserved across calls (a running install picking
    up a new config keeps its current tokens); rounding down when
    capacity shrinks below current tokens.
    """
    global _capacity, _refill_per_sec
    if requests_per_minute is not None:
        rpm = int(requests_per_minute)
        if rpm < 1 or rpm > _MAX_CAPACITY:
            raise ValueError(
                f"requests_per_minute must be 1..{_MAX_CAPACITY}, got {rpm}")
        if capacity is None:
            capacity = rpm
        if refill_per_sec is None:
            refill_per_sec = float(rpm) / 60.0
    if capacity is not None:
        cap = int(capacity)
        if cap < 1 or cap > _MAX_CAPACITY:
            raise ValueError(
                f"capacity must be 1..{_MAX_CAPACITY}, got {cap}")
        _capacity = cap
    if refill_per_sec is not None:
        r = float(refill_per_sec)
        if r < _MIN_REFILL_PER_SEC:
            raise ValueError(
                f"refill_per_sec must be >= {_MIN_REFILL_PER_SEC}, got {r}")
        _refill_per_sec = r
    with _lock:
        for b in _buckets.values():
            b.tokens = min(b.tokens, float(_capacity))


def get_config() -> dict:
    """Return the current bucket parameters. No side effect."""
    return {
        "capacity": _capacity,
        "refill_per_sec": _refill_per_sec,
        "requests_per_minute": round(_refill_per_sec * 60.0, 3),
    }


def _tick(bucket: _Bucket, now: float) -> None:
    """Refill the bucket up to ``_capacity`` based on elapsed time."""
    elapsed = max(0.0, now - bucket.updated_at)
    bucket.tokens = min(float(_capacity),
                        bucket.tokens + elapsed * _refill_per_sec)
    bucket.updated_at = now


def check(token_key: str | None,
          now: float | None = None) -> tuple[bool, float]:
    """Return ``(allowed, retry_after_seconds)``.

    ``token_key`` should be the F006 install-token fingerprint, never
    the raw token. Passing an empty / None key is treated as "no
    identity" and is refused with ``(False, 0.0)`` — the caller should
    have already run the install-token gate.
    """
    if not token_key or not isinstance(token_key, str):
        return False, 0.0

    t = time.monotonic() if now is None else float(now)
    with _lock:
        bucket = _buckets.get(token_key)
        if bucket is None:
            bucket = _Bucket(tokens=float(_capacity), updated_at=t)
            _buckets[token_key] = bucket
        _tick(bucket, t)
        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return True, 0.0
        # Not allowed -- how long until the next token drips in?
        deficit = 1.0 - bucket.tokens
        retry_after = deficit / _refill_per_sec if _refill_per_sec > 0 else 60.0
        # Cap the returned wait at the refill window so a client can
        # retry inside the same window rather than being stuck for
        # hours if a config is misapplied.
        retry_after = min(retry_after, float(_capacity) / _refill_per_sec)
        return False, round(retry_after, 3)


def reset(token_key: str | None = None) -> None:
    """Test helper. ``None`` clears every bucket."""
    with _lock:
        if token_key is None:
            _buckets.clear()
        else:
            _buckets.pop(token_key, None)


def bucket_count() -> int:
    """Number of buckets currently tracked. Test-only observability."""
    with _lock:
        return len(_buckets)
