---
id: I009
source: audit
submitter: user_advocate
submitted_at: 2026-07-24T00:30:00Z
classification: BUG
priority: P2
status: in_progress
route: engineering
linked_features: []
linked_decisions:
  - D107
linked_experiments: []
contact: internal (2026-07-24 full-system audit, A009)
resolved_at: null
history:
  - stage: filed
    at: 2026-07-24T00:30:00Z
    by: user_advocate
    note: "Filed from the 2026-07-24 full-system audit (A009). Pin fixed same-session on product (pandas>=2.2,<3); VM venv rebuild outstanding."
---

# I009 — pandas pin unbounded; VM resolved pandas 3.x (A009)

## What happened

`requirements.txt` and `pyproject.toml` pinned `pandas>=2.2` with no
upper bound. The VM's fresh install resolved **pandas 3.0.3** — a
major version this codebase has never been tested against.

## Why it matters

A silent major-version jump on the machine that actually serves the
product. Any pandas 3.x behaviour change (copy-on-write default,
dtype promotions) lands untested in the live path.

## Resolution status

**Pin fixed same-session on `product`:** `pandas>=2.2,<3` in both
`requirements.txt` and `pyproject.toml`.

**OUTSTANDING — FLAGGED PROMINENTLY: the VM venv already has pandas
3.0.3 installed. The pin does not fix an existing venv. The VM venv
must be rebuilt** (`pip install -r requirements.txt --force-reinstall`
or a fresh venv) — see the runbook preflight note added with this
filing (`docs/RUNBOOK_demo_launch.md` section 4).

## Triage decision

- **Classification:** BUG · **Priority:** P2 · **Route:** engineering.
- **Owner from here:** cto (VM rebuild is a runbook step for the CEO).

## Closure notes

Open until the VM venv reports `pandas<3`. Full audit:
`reviews/audits/2026-07-24-full-system-audit.md`.

- **Related decisions:** D107.
