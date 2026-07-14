"""The squad event JSON schema — the sim-vs-paper contract, as code.

One place that says what a v2 match event looks like, whatever produced
it (replay-cache parsing today, the paper loop's live stream, the real
squad later). ``validate_event`` is a plain-dict validator (no external
schema dependency) returning a list of problems, empty when the event
conforms. Contract tests validate BOTH producers against it, so schema
drift between replay and live paths fails loudly in CI instead of
silently breaking the UI.

Field reference (light payload; the optional ``detail`` dict carries
heavy forensics and is stripped from paged API responses):

* common      -- t: ISO-8601 str, type: one of EVENT_TYPES, agent: str
* proposal    -- symbol, dir, conviction (0..1-ish float)
* blocked     -- symbol, by (agent id or "SENTINEL"), rule (bool),
                 reason (str)
* open        -- symbol, dir
* close       -- symbol, goal (bool), pnl_pips (float), exit_reason,
                 tqs (float|None), r (float|None)
* thought     -- text (str), symbol (str|None); optional stream, absent
                 from the G7 review caches by design
"""
from __future__ import annotations

from datetime import datetime

EVENT_TYPES = ("proposal", "blocked", "open", "close", "thought")

# type -> {field: (allowed python types, required?)}
_FIELDS: dict[str, dict[str, tuple[tuple, bool]]] = {
    "proposal": {
        "symbol": ((str,), True),
        "dir": ((str,), True),
        "conviction": ((int, float), True),
    },
    "blocked": {
        "symbol": ((str,), True),
        "by": ((str,), True),
        "rule": ((bool,), True),
        "reason": ((str,), True),
    },
    "open": {
        "symbol": ((str,), True),
        "dir": ((str,), True),
    },
    "close": {
        "symbol": ((str,), True),
        "goal": ((bool,), True),
        "pnl_pips": ((int, float), True),
        "exit_reason": ((str,), True),
        "tqs": ((int, float, type(None)), False),
        "r": ((int, float, type(None)), False),
    },
    "thought": {
        "text": ((str,), True),
        "symbol": ((str, type(None)), False),
    },
}


def validate_event(event: object) -> list[str]:
    """Problems with ``event`` against the contract; [] when it conforms."""
    if not isinstance(event, dict):
        return [f"event is {type(event).__name__}, expected dict"]
    errors: list[str] = []

    etype = event.get("type")
    if etype not in EVENT_TYPES:
        return [f"type={etype!r} not in {EVENT_TYPES}"]

    t = event.get("t")
    if not isinstance(t, str) or not t:
        errors.append(f"t={t!r} must be a non-empty str")
    else:
        try:
            datetime.fromisoformat(t)
        except ValueError:
            errors.append(f"t={t!r} is not ISO-8601")

    if not isinstance(event.get("agent"), str) or not event["agent"]:
        errors.append(f"agent={event.get('agent')!r} must be a non-empty str")

    for field, (types, required) in _FIELDS[etype].items():
        if field not in event:
            if required:
                errors.append(f"{etype}: missing required field {field!r}")
            continue
        val = event[field]
        # bool is an int subclass; reject it where a number is expected.
        if isinstance(val, bool) and bool not in types:
            errors.append(f"{etype}.{field}={val!r} is bool, expected "
                          f"{'/'.join(t.__name__ for t in types)}")
        elif not isinstance(val, types):
            errors.append(f"{etype}.{field}={val!r} has type "
                          f"{type(val).__name__}, expected "
                          f"{'/'.join(t.__name__ for t in types)}")

    detail = event.get("detail")
    if detail is not None and not isinstance(detail, dict):
        errors.append(f"detail must be a dict when present, "
                      f"got {type(detail).__name__}")
    return errors


def validate_events(events: list[dict]) -> list[str]:
    """Validate a whole stream; problems are prefixed with the index."""
    out: list[str] = []
    for i, e in enumerate(events):
        out.extend(f"[{i}] {msg}" for msg in validate_event(e))
    return out
