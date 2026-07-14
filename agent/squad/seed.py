"""Deterministic seed derivation for the replay kernel.

Every stochastic operation in the decision path consumes a seed derived
from `(agent_id, tick_id)` via `seed(...)`. Hard rule (09 section 1.2):
no `random.random()` or `time.time()` in the decision path.

Implementation: 64-bit SipHash-derived integer via Python's built-in
`hashlib.blake2b`. Deterministic across runs and platforms; cheap.
"""
from __future__ import annotations

import hashlib

# Salt prefix bumped when we want to invalidate every cached seed value.
_SALT = b"M001-sim-v1"


def seed(agent_id: str, tick_id: int) -> int:
    """Derive a 63-bit non-negative integer seed for (agent_id, tick_id).

    Properties:
      - Determinism: same inputs -> same output, every time, every host.
      - Avalanche: tiny input changes produce uncorrelated outputs (blake2b).
      - Collision-free across agents x ticks in practice (2^63 codomain).
    """
    if not isinstance(agent_id, str):
        raise TypeError(f"agent_id must be str, got {type(agent_id)!r}")
    if not isinstance(tick_id, int):
        raise TypeError(f"tick_id must be int, got {type(tick_id)!r}")
    payload = b"|".join(
        [_SALT, agent_id.encode("utf-8"), str(int(tick_id)).encode("ascii")]
    )
    digest = hashlib.blake2b(payload, digest_size=8).digest()
    return int.from_bytes(digest, "big") & ((1 << 63) - 1)


def seed_for(agent_id: str, tick_id: int, channel: str) -> int:
    """Derive a sub-seed for a named channel inside an agent's tick.

    Use this when an agent needs multiple independent RNG streams within
    the same tick (e.g. price noise vs sizing perturbation). Channels
    that share `(agent_id, tick_id)` but differ in `channel` are
    uncorrelated.
    """
    payload = b"|".join(
        [
            _SALT,
            agent_id.encode("utf-8"),
            str(int(tick_id)).encode("ascii"),
            channel.encode("utf-8"),
        ]
    )
    digest = hashlib.blake2b(payload, digest_size=8).digest()
    return int.from_bytes(digest, "big") & ((1 << 63) - 1)
