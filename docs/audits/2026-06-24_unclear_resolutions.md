# UNCLEAR resolutions — production repo audit (2026-06-24)

Parent decisions for §6 items in
[`2026-06-24_production_repo_audit.md`](2026-06-24_production_repo_audit.md).
Recorded here so Wave 3 archiving does not re-debate them.

## 1. `scripts/evaluate.py` (+ `scripts/evaluate_alphas.py`)

**Resolution: TRANSITION — rebuild target abandoned; not the M001 eval surface.**

| Field | Decision |
|---|---|
| Category | TRANSITION (keep in place until Wave 3 archive) |
| Rationale | The v2-reset "rebuild target" never landed. The 224-cell grid lives in `run_zone_all_tfs.py` + `run_ablation.py`. `evaluate.py` only exercises `ReactionAlpha` + the legacy allocator — not the validated zone pipeline. |
| M001 role | None. M001 Φ4 reuses the existing validation gauntlet (`run_walk_forward`, `run_ablation`, etc.), not this stub. |
| Wave 3 action | Archive to `agent/_archive/scripts/` and drop `evaluate` / `alphas` CLI subcommands (audit §3 action 9). |

## 2. `agent/alphas/allocator.py`

**Resolution: KEEP-AND-INHERIT — seed for M001 Capital Allocator (Ego coach layer).**

| Field | Decision |
|---|---|
| Category | KEEP-AND-INHERIT (do not archive in Wave 3) |
| Rationale | Implements Ledoit-Wolf shrinkage on daily-return covariance, tangency weights clipped to long-only. Only live caller today is `scripts/evaluate.py`, but the **math** is the right primitive seed for M001 F1–F3 (Bates–Granger / risk parity / HRP stack in `04-quant-foundations.md`). F1–F3 will **extend** this, not replace it wholesale. |
| M001 role | Seed for Φ6 Capital Allocator; strikers share weights from this layer after ablation evidence passes. |
| Wave 3 action | Add a module header note pointing to M001 F1–F3; do **not** move to `_archive/`. |

## Cross-reference

- Wave 1 (done 2026-06-24): docs-only cleanup per audit §5 Wave 1.
- Wave 2 (deferred): deploy-windows URL, CLI rename — audit §5 Wave 2.
- Wave 3 (deferred): dead-code delete, `_archive/` sweep, dep purge, Docker/MT5 — audit §5 Wave 3; apply resolutions above when archiving `evaluate.py` but **not** `allocator.py`.
