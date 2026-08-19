"""Locate the CANONICAL research checkout for the shipped-manifest pins.

The shipped manifest describes the E0xx registry's canonical state, and
that state lives on `main` (per the branch-targeting table: `main` is
the registry lane, `multi-agent-ensemble` is the M001 program lane).

The sibling clone is a working checkout that spends most of its life on
whatever branch the current session needs, so pinning tests to it made
them fail whenever someone was mid-M001 -- permanently red for a reason
that has nothing to do with the code under test. A suite with
known-acceptable failures is a suite people stop reading, which is the
real cost.

So: prefer any checkout actually on `main`, including a durable
worktree, and skip rather than assert when none is available.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

# Ordered by preference. A dedicated `main` worktree comes first because
# it is the one location that stays on `main` by construction.
CANDIDATE_ROOTS: tuple[Path, ...] = (
    Path("/Users/the1finix/Documents/GitHub/fre-main"),
    Path("/Users/the1finix/Documents/GitHub/finance-research-experiments"),
)


def _branch_of(path: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "branch", "--show-current"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def canonical_research_root() -> Path | None:
    """A research checkout on `main`, or None.

    Returns None rather than falling back to an off-branch checkout: a
    manifest pin scored against the wrong branch is a misleading pass or
    a misleading failure, and both are worse than an honest skip.
    """
    for root in CANDIDATE_ROOTS:
        if root.is_dir() and _branch_of(root) == "main":
            return root
    return None


# The shipped manifest spans BOTH research lanes, and no single checkout
# can satisfy it: the E0xx registry lives on `main` while the M001 phase
# studies live on `multi-agent-ensemble`, and neither branch carries the
# other's artefacts. Pinning the whole manifest against one root was
# therefore asserting a state that exists nowhere, which is why those
# tests were permanently red.
#
# Each lane is pinned against the branch that actually owns it.
LANE_EXPECTED_IDS: dict[str, set[str]] = {
    "main": {
        "E001_concept_ablation", "E004_walk_forward",
        "E007_impulse_origin_bounce", "E022_structure_aware_tp_snap",
        "E024_near_tp_stall_exit",
    },
    "multi-agent-ensemble": {
        "E001_concept_ablation", "E004_walk_forward",
        "E007_impulse_origin_bounce", "phase_ac_pitch_assignment",
        "phase_ae_sae_event_specialist",
    },
}


def available_lanes() -> list[tuple[Path, str, set[str]]]:
    """Every research checkout whose branch this suite has a pin for.

    Returns `(root, branch, expected_ids)` per usable checkout. Empty
    when none is available, which callers should treat as a skip.
    """
    found: list[tuple[Path, str, set[str]]] = []
    seen: set[str] = set()
    for root in CANDIDATE_ROOTS:
        if not root.is_dir():
            continue
        branch = _branch_of(root)
        if branch in LANE_EXPECTED_IDS and branch not in seen:
            seen.add(branch)
            found.append((root, branch, LANE_EXPECTED_IDS[branch]))
    return found
