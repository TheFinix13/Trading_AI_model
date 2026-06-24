# AI Context — brain dump (updated 2026-06-24, v0.21.1)

> v0.21.1 — **Wave 2 cleanup done.** Production repo stale-reference sweep
> shipped: `scripts/deploy_windows.ps1` rewritten to `multi-pair-trading-agent`
> (title + clone URL + candidate paths); `[project.scripts] eurusd-agent` →
> `multi-pair-agent` (pyproject.toml + `agent/cli.py` usage string); `.env.example`
> now tracked via explicit `!.env.example` gitignore exception; workspace rule
> `.cursor/rules/git-no-cursor-attribution.mdc` committed. CLI subcommand drops
> (`evaluate`/`alphas`/`smoke`) deferred to Wave 3 alongside their backing-script
> archive. **VM impact:** next `pip install -e .` produces the `multi-pair-agent`
> binary; if any operator script shells `eurusd-agent`, update it. Queued:
> Wave 3 (dead-code delete + `_archive/` sweep + dep purge + Docker/MT5 archive).
>
> v0.21 — **Branching + Wave 1 cleanup.** Long-lived branch `m001-development`
> created from main (M001 graduation target). Production repo Wave 1 docs-only
> cleanup done (six HISTORICAL numbered docs → `docs/archive/`; 03/05/06
> rewritten; M001 pointer + unclear resolutions). M001 R&D (v0.3) lives in
> `finance-research-experiments` /
> `programs/M001_multi_agent_ensemble/` (branch `multi-agent-ensemble`,
> commit `1548b23`). Rollback tag: `v2-zone-d1-against-stable-2026-06-24`
> (`6f1cc75`). UNCLEAR resolutions: `evaluate.py` → TRANSITION (archive Wave 3);
> `allocator.py` → KEEP-AND-INHERIT (M001 allocator seed).
>
> v0.20 — Repo split; M001 doctrine migrated to research repo; pointer at
> `docs/research/multi-agent-ensemble/README.md`. Prior detail: `docs/CHECKPOINT.md`.

Read this first in a fresh chat. Strictly technical state summary.
Deeper history: `docs/00-journey.md`. Snapshot: `docs/CHECKPOINT.md`.
**Active R&D:** `finance-research-experiments` /
`programs/M001_multi_agent_ensemble/` (branch `multi-agent-ensemble`,
commit `1548b23`, M001 v0.3). Pointer: `docs/research/multi-agent-ensemble/README.md`.

## 1) What is built and working

- **Validated strategy:** `zone_d1_against` — SupplyDemandAlpha, H4 zone touch
  faded AGAINST D1 trend. Locked: `htf_align="D1", htf_align_mode="against",
  htf_lookback=10, htf_min_move_pips=60.0`. Evidence chain in
  `docs/00-journey.md` / `docs/reviews/`.
- **Deployment router:** EURUSD/H4/all @1.0, GBPUSD/H4/all @0.5, USDCAD/H4/all
  @0.5. Unknown cells fail-safe skip; contract tests in
  `tests/test_zone_routing.py`.
- **Live runner:** one process per symbol; router default; conviction-scaled
  risk 0.5–2% × risk_scale. `scripts/run_live.py --symbol --log-dir --broker`.
- **Observability:** daily logs, 15-min heartbeat, bracketed tags, near-miss/loss
  vaults (JSONL+PNG), target ladder (observation-only), `daily_summary.py`,
  `state.json` sidecar. 349 tests passing.
- **Deployed:** Windows VMware, Exness demo ($100 / 1:1000), 3 PowerShell tabs.
  VM update: `git fetch && git reset --hard origin/main && pip install -r requirements.txt`.
- **Branches:** `main` = production; `m001-development` = pre-M001 baseline for
  future M001 graduation; tag `v2-zone-d1-against-stable-2026-06-24` at
  `6f1cc75` for rollback.

## 2) Key file paths

| Area | Files |
|---|---|
| Strategy | `agent/alphas/concepts/zone_alpha.py`, `agent/alphas/concepts/_htf.py` |
| Router | `agent/alphas/zone_routing.py` |
| M001 seed (keep) | `agent/alphas/allocator.py` — Ledoit-Wolf, long-only weights |
| Live | `scripts/run_live.py`, `agent/live/signal_loop.py`, `agent/live/state_store.py` |
| Vaults / ladder | `agent/journal/vault.py`, `agent/journal/target_ladder.py`, `scripts/daily_summary.py` |
| Validation | `scripts/run_zone_all_tfs.py`, `scripts/run_ablation.py`, `scripts/run_walk_forward.py` |
| Docs | `docs/CHECKPOINT.md`, `docs/00-overview.md`, `docs/archive/`, `docs/audits/` |
| M001 pointer | `docs/research/multi-agent-ensemble/README.md` |
| Workspace setup | `.cursor/workspace-tips.md` (multi-root: this repo + research + brain-box) |

## 3) Next immediate goal

**Active track: M001 multi-agent ensemble (Φ0 → Φ1) in research repo.**

Next deliverable: `02b-literature-survey.md` (source-cited formula entries per
`02-literature-survey-plan.md`). Parallel: Φ2 simulator scaffold on research repo.

**Production repo (this):** Wave 2 done (deploy URL + CLI rename +
`.env.example` track + workspace rule). Wave 3 queued per
`docs/audits/2026-06-24_production_repo_audit.md` §5 — dead-code delete +
`_archive/` sweep + dep purge + Docker/MT5 archive (apply
`docs/audits/2026-06-24_unclear_resolutions.md` for evaluate vs allocator).

**Monitor-only:** `zone_d1_against` on $100/1:1000 demo — no param changes;
collecting live PnL for future DSR gate when A1 Isagi wraps the roster.

Parked: see `docs/ROADMAP.md` (target_rr study, partial TP, USD exposure, D1
promotion, autonomy ladder).
