# AI Context — brain dump (updated 2026-08-19, v0.73)

> v0.73 — **F025 safe prerequisites landed + A9 renamed
> `sae_itoshi` → `aoshi_tokimitsu`.** Four of the eight F025 blockers
> were fixable without touching the squad→executor bridge, so they
> shipped ahead of the sprint: (B4) `live_executor.close_executed_position`
> — a real close path, deliberately kill-switch-EXEMPT (a kill switch
> must never trap you in a position) but still demo-only and
> executor-enable gated, exposed at `POST /api/executor/close/<ticket>`;
> (B5) magic number `314159` stamped on every outgoing MT5 request and
> every `executions.jsonl` row, so v2's orders are attributable against
> v1's on a shared account, configurable via `[live_executor] magic`;
> (B7) kill-switch coverage 6 → 17 symbols (XAGUSD/XAUUSD/indices/oil
> were silently fail-OPEN), and the settings grid now reads
> `supported_symbols` off the API instead of a hardcoded majors list, so
> adding a symbol no longer needs a page edit; plus the RUNBOOK §7c.1
> gap where the `[broker] terminal_path` + `portable = true` pin (the
> D124 account-contention fix) wasn't in the enable ceremony. **Still
> open and still blocking the $500 bridge: B1 (nothing calls
> `approval_queue.submit` on the squad path), B2 (squad fills 0.1 lot
> vs executor's 0.01 hard cap — every order would refuse on gate 8),
> B3 (Sentinel R1 measures risk at min-lot while fills are 10× — the
> advertised 5 %-per-trade cap is wrong by 10× on a real account; fix
> BEFORE the bridge), B6 (`record_fill(…, 0.0)` leaves the risk budget
> inert), B8 (no aggregate exposure cap).** G7 still FAIL 3/7.
> **A9 rename:** the M001 roster assigns A9 to Aoshi Tokimitsu
> ("macro-event-only vol-breakout — FOMC/NFP/CPI", verbatim this
> weapon) while "Sae Itoshi (foil)" is the frozen ADVERSARIAL baseline
> the squad must beat; shipping the striker under the opponent's name
> made every report ambiguous between a player and a benchmark. Renamed
> across roster/players/pages/engine; `state.json` migrates
> `per_agent_equity` + `per_agent_consecutive_losses` on load
> (`AGENT_ID_RENAMES`), legacy ids stay resolvable so pre-rename tapes
> and bookmarked `/players/sae` URLs still land. **Config keys keep the
> old spelling on purpose** — `SaeConfig`, `sae_enabled`,
> `--enable-sae`, `a09_sae.py` — so the VM watchdogs need no edit.
> Phase AE's FAIL verdict is unrevised: he is on the pitch as
> telemetry, not as a trusted trader. Suite: 2165 pass / 4 fail
> (3 pre-existing research-manifest fails + 1 fixed here).

> v0.72 — **$500-book groundwork + one-command VM update (`97b1fac`,
> `afcff74`, pushed to `product`).** (1) `scripts/update_platform.ps1` is
> the v2 twin of the trading clone's `update_agent.ps1`: self-locating,
> expects branch `product`, `--ff-only`, refuses to pull over
> uncommitted changes; verify step answers the v2 questions — is anything
> listening on 8787, is `sae_enabled` true in `state.json`, what equity
> R1 is sizing against, per-player books, tape age. Driven by `v2up` /
> `v2status` from the profile shortcuts installed out of the v1 clone.
> (2) **Config bug fixed:** `load_config` never parsed `[squad_live]`
> `equity` / `field_assignments` (nor `burn_in_bars` /
> `feed_stale_hours`), although `platform.toml.example` has documented
> them since AN-3 and `run_squad_live.main()` reads them — so the file
> silently stayed on the $100 sandbox and the XAGUSD field card was
> silently dropped; only CLI flags worked. Unset keys stay `None`/`{}` so
> runtime fallbacks remain authoritative. `equity = 500` in
> `platform.toml` now works: R1's per-trade cap goes $5 → $25, max
> admissible stop 50 → 250 pips EURUSD (10 → 50 XAGUSD). Tests:
> `tests/platform/test_squad_live_config_block.py` (+12); platform suite
> 1141 pass / 3 fail (all 3 pre-existing research-manifest fails).
> (3) **F025 chartered, NOT started** —
> `company/sprints/sprint-4-squad-demo-execution/`. The operator wants v2
> on the real $500 Exness demo; that is a feature, not a flag. Nothing
> calls `approval_queue.submit` on the squad path and `live_executor`'s
> only caller is the human Execute button. Eight blockers documented; the
> two that bite first are the lot contradiction (squad fills `FIXED_LOT`
> 0.1, executor hard-caps `max_volume_lots` 0.01 → every order refused on
> gate 8) and **Sentinel R1 measuring risk at min-lot while fills are
> 10×**, which makes the advertised 5 %-per-trade cap wrong by 10× on a
> real account — a correctness bug to fix BEFORE the bridge. Plus: no
> close path, no magic number, `record_fill(…, 0.0)` leaves the risk
> budget inert, kill switch doesn't cover XAGUSD, no aggregate exposure
> cap. G7 still has no passing verdict (§11.18 FAIL 3/7).

> v0.71 — **Observability week: the tape now tells the whole story
> (branch confirmed by user 2026-08-13: v2 → `product`, v1 → `main`;
> research: v1 → research `main`, v2 → `multi-agent-ensemble`).**
> Root cause of the Aug 1–10 "0 shots" weekly squad report found: the
> live engine wrote proposals/blocks/fills ONLY to the split files
> (`proposals_all/proposals_rejected/trades.jsonl`) while every
> narrative surface (/highlights, F001/F002, weekly report) reads
> `events.jsonl`, which carried only `tick_summary` rows. Fixes:
> (1) `engine.py` now emits dedicated `proposal`/`blocked`/`open`/
> `close` rows to events.jsonl (split files unchanged, raw archive);
> (2) `highlights.py` falls back to tick_summary counts for pre-fix
> historical tapes (headline discloses "counts from tick summaries");
> (3) `squad_notify.py` pages SHOT ON TARGET (fill geometry +
> conviction) and TACKLED (Sentinel rule + reason, or peer duel
> winner) from events.jsonl rows; goal/miss now carry MFE/MAE path +
> hold time. (4) Feed staleness ages in MARKET hours
> (`_market_age_seconds` excludes Fri 20:00→Sun 22:00 gaps) — kills
> the Sunday-reopen ~50h false page of 2026-08-09. (5) SAE ON by
> default in `watchdog_squad.ps1` (`-NoSae` opt-out; observability
> decision, NOT a validated-edge claim — Phase AE FAIL stands).
> (6) New `watchdog_platform.ps1` keeps serve_platform.py:8787 alive
> (it was down with no restarter — the localhost refusal of Aug 10).
> Tests: +tape-consistency suite (tests/test_squad_tape_events.py),
> +market-age, +fallback, +notify routing; full suite 2100 pass /
> 4 fail (3 research-manifest fails pre-existing on clean checkout,
> 1 tick-summary test updated for the new open rows). Finding, NOT
> changed: squad has NO time-based exit — `target_hold_hours` only
> feeds TQS scoring, so Bachira's GBPUSD short legitimately rode 5d
> to SL vs a 24h "target"; adding a time stop = strategy change →
> research pre-reg first. Research lane: E033 scheduled-news blackout
> pre-reg DRAFTED (finance-research-experiments
> `experiments/E033_scheduled_news_blackout/PROTOCOL.md`, untracked;
> cites AD.2 prior AGAINST + AE "avoidable, not tradable" FOR).

> v0.70 — **Barou v1.4 sealed FAIL; Chigiri:XAGUSD paper ready.**
> Stop/ATR≤2.25 gate: design PASS (PF 1.163) then sealed 2023–2026
> FAIL (PF 1.005, meanR −0.035, 3/5) — USDJPY seal CONSUMED; live
> stays `weapon_v14=False`. Autopsy Candidate A dies honestly.
> AN fade = `thin_sample_artifact` (2024 still PF 1.498 on full path).
> Squad/isolation doctrine filed. Paper path for Chigiri:XAGUSD
> shipped (`--field-assign` / `--equity 500`, Tier-2 field-pip fills;
> FX fills stay legacy 1e-4 for research parity). Runbook:
> `docs/runbooks/chigiri_xagusd_paper.md`. Next: VM paper enable;
> Barou Candidate B only with fresh pre-reg (not this sealed window).

> v0.68 — **Phase AN: the FIRST full-ladder validated cell.**
> Family of 5 chartered follow-ups ran as pre-registered (research
> `phase_an_field_followups/`, K=5 multi-start ISOLATION replays,
> honest per-field costs, floors declared before execution).
> **chigiri_hyoma:XAGUSD PASSED everything:** design 2015–2022 median
> PF 1.248 [1.229–1.292], meanR +0.070, 5/5 starts; sealed 2023-01→
> 2026-05 one-shot open median PF 1.27, meanR +0.198, 4/5 (verdict:
> validated-with-single-pass-caveat; recency fade noted — the
> 2024-01 start is the one negative path). XAGUSD 2023+ seal now
> CONSUMED (DATA_LEDGER row). The other 6 cells FAILED isolation:
> Rin:USDJPY survey headline collapsed (PF 0.924, 0/5 — squad
> context was filtering ~120 toxic trades; registry lesson: surveys
> in squad context inflate KPIs, isolation is the weapon's truth).
> Barou:USDJPY is a real near-miss (PF 1.138 vs 1.15 floor, meanR
> +0.105, 5/5, n=418 — his n-growth question answered: field
> problem, not weapon problem; legit path = Barou v1.x patch with
> fresh pre-reg). Barou home USDCAD fails isolation (0.957, 1/5).
> Chigiri:AUDUSD + Bachira:NZDUSD closed (fail final). Recommended
> next: Chigiri:XAGUSD → paper-loop candidacy (needs XAGUSD
> live-path I030 residue cleared first), Barou v1.x patch charter.

> v0.67 — **Phase AM: first-ever Tier-2 survey (virgin data).**
> Field cards shipped (`company/rd/field_cards/tier2-first-wave.md`,
> `48cf140`) with honest min-lot economics (indices/BTC $0.01/pt) +
> three declared distortions (zone grammar price-scale filters OFF
> on non-FX, FX cost model understates, regime_fit tilts high).
> Survey (XAU/XAG/USOIL/USTEC H4 2015–2022, equity=500 = the real
> v2 demo account, 2023+ seals intact): **chigiri:XAGUSD PASSES the
> floor — n=134, 50.0% wins, PF 1.541, meanR +0.243 — strongest
> cell any survey has produced**; barou:USTEC marginal pass
> (98/1.156). Isagi and Rin negative on ALL four Tier-2 fields.
> Pattern registry: Chigiri travels (AUDUSD/silver/gold-lite) while
> failing at home; Rin = deep-liquidity FX specialist (EURUSD +
> USDJPY only); Isagi does not travel at all; Barou rare-fires on
> trending fields. Chartered follow-up queue now: Rin:USDJPY,
> Chigiri:AUDUSD, Chigiri:XAGUSD, Bachira:NZDUSD (+ proposed
> Barou multi-field multi-start rolling USDJPY+USTEC into his
> n-growth charter — user call).

> v0.66 — **I030 FIXED + AL re-survey + Chigiri holdout kill.**
> Pip semantics now symbol-aware across the squad path (product
> commit `2650524`: tables in `provenance_pips.py`, threaded through
> sentinel R1, arm4 R6, paper-broker KPIs, Rin/Barou stop-pips, all
> proposers' stamps; 10 pinned tests; 948-test suite green). Parity
> PROVEN: 2019 3-major full-roster replay byte-identical pre/post
> fix (each call site keeps legacy mult-or-div float op — see
> research `i030_pip_semantics/PARITY_NOTE.md`). **AL A1 re-survey
> (fixed engine, same 4 pairs): USDJPY unblocked, 1,025 trades.
> Headline: itoshi_rin:USDJPY n=336 PF 1.212 +1,875 pips — Rin's
> best cell on any field. Chartered follow-ups now THREE:
> Rin:USDJPY, Chigiri:AUDUSD (held, 183/1.376), Bachira:NZDUSD
> (held, 332/1.269); Barou:USDJPY (78/1.364) noted, user call.**
> Chigiri autopsy verdict: pure win-rate deficit (32.1% vs 40%
> breakeven); loss cluster = US-afternoon/rollover fills. BUT the
> 2015–2018 quasi-holdout KILLED both cheap rework levers (the
> London-open niche is his WORST holdout segment, 26.1% wins;
> conviction gate non-discriminating — all fills ≥0.75). Chigiri's
> only evidence-backed path is the AUDUSD field-fit study. Lesson
> banked in `chigiri_v11_autopsy/HOLDOUT_CHECK.md`: every
> autopsy-derived candidate gets a holdout pass before a protocol.

> v0.65 — **D149: three lanes executed + the Chigiri convergence.**
> AK-2 Reo striker mode: `passthrough` (PF 0.94 ≈ leaders' base) —
> Reo stays filter-only; but his CHIGIRI mirrors are positive
> (n=307, PF 1.26) while Chigiri is net-negative. Phase AL Tier-1
> survey (4 pairs, design region 2015–2022): chartered follow-ups =
> **chigiri:AUDUSD (n=183, PF 1.376)** + **bachira:NZDUSD (n=332,
> PF 1.269)**; nagi:USDCHF + barou:AUDUSD qualifying-but-capped.
> Two independent lenses now say Chigiri's high-conviction core is
> sound, junk tail is the problem (v1.1 autopsy in flight).
> **I030 (P1): USDJPY = ZERO trades** — hardcoded `PIP_SIZE=0.0001`
> makes sentinel R1 block every JPY/metals/indices proposal; per-
> symbol instrument spec needed before any Tier-2 replay. **Tier-2
> banking COMPLETE:** 22 instruments H4+D1 2015→present in research
> repo `data/parquet_tier2/` (local; manifest committed); 2023+
> pre-sealed. Branch note: research `main` is 1 commit ahead
> locally (7e1473c, duplicate of ensemble f524abc) — drop or keep
> per user.

> v0.64 — **D148: instrument universe + player-development doctrine.**
> Tier 1 fields = AUDUSD/NZDUSD/USDJPY/USDCHF (banked; design
> pre-2023 only; 2023→present SEALED per field, DATA_LEDGER rule 4).
> Tier 2 = crosses/metals/energy/index CFDs (needs Dukascopy
> symbol-map extension). Tier 3 = futures later; single-name stocks
> OUT (separation rule). Rework doctrine: change the PLAYER, never
> the TEST (autopsy → literature-grounded redesign → sealed
> validation; one mechanism per versioned patch). First charters:
> Chigiri v1.1 autopsy, Reo AK-2 striker-mode counterfactual, Barou
> multi-start n-growth. New research standard
> `METHODOLOGY_thin_sample_replays.md`: thin-n (<100 trades) cells
> need K=5 staggered-start replays, 3-month burn-in, median judged,
> 4/5 sign stability — AF/AJ/AJ-2 thin-n readouts now flagged
> provisional. `mt5/ExportCalendarHistory.mq5` now in product repo
> (VM: pull → MetaEditor → compile → run on any chart → CSV in
> MQL5\Files). Fixed ledger drift: D147/D148 now in
> company_state.json.

> v0.63 — **Action plan + I029 resolved + Phase AK + DATA_LEDGER
> (D147)** 2026-08-04, same session:
> - **I029 RESOLVED (works-as-designed):** Reo's `intend()` returns
>   None BY DESIGN (chameleon mirror for Nagi's confluence). NEL
>   scoreboard now exempts him from the zero-conversion drain.
> - **Phase AK ablation (pre-reg): `reo_obstructive`** — without Reo,
>   Nagi fires 69 vs 27 trades (+156%); design premise FALSIFIED.
>   Measured role = quality throttle (Nagi meanR +0.222 with vs
>   +0.094 without; total R equal; squad unchanged). Options A
>   (keep + reclassify, recommended) / B (cut) / C (v2 redesign) on
>   file — user decides.
> - **DATA_LEDGER** (research repo, M001): window-consumption
>   registry. Key rules: 2024–2026 FX H4 validation window EXHAUSTED
>   (opened 4×, D139 saw all); AG's 2022–2025 event reservation still
>   pristine; AUDUSD/NZDUSD/USDJPY/USDCHF lightly fingerprinted
>   (Phase AC, void semantics); XAUUSD/XAGUSD/USOIL/USTEC virgin;
>   live tape = cleanest evidence. Every new protocol must cite it.
> - **Week plan** at `company/strategy/action-plan-2026-08-04.md`:
>   Lane 1 S1 surprise panel (BLOCKED ON USER: one VM MQL5 export),
>   Lane 2 new instruments, Lane 3 live measurement week (Night
>   Auditor daily; league table Friday), Lane 4 mechanism fixes.
>   Explicitly banned: re-sweeping the mined-out three pairs.

> v0.62 — **Phase AJ/AJ-2 cross-symbol transfer: 0/8, no promotion
> (D146)** 2026-08-04, same session. Both pre-registered before
> execution; sealed 2024–2026 window opened ONCE (for Barou:GBPUSD)
> and consumed. Verdicts: Rin does NOT travel (GBPUSD PF 1.037 flat
> n=224, USDCAD 0.778 — EURUSD-only restriction is load-bearing);
> Barou:EURUSD near-miss (PF 2.03 n=25) failed the subset guard
> (unseen 2015–2018 negative on its own); Barou:GBPUSD passed
> extended IS (PF 1.441 n=51, unseen years +10.9R) but FAILED sealed
> validation (PF 0.962, meanR +0.017). Home cells stable — clean
> study. **Registered discovery: thin-n agents' per-cell replay KPIs
> are window-start path-dependent** (Barou same calendar years n=25
> vs n=10 depending on 2019 vs 2015 replay start); AF's "Barou
> positive in all 8 cells" prior downgraded accordingly; AJ-3 must
> use single-agent isolation replays. Artifacts:
> `phase_aj_cross_symbol_transfer/` on `multi-agent-ensemble`
> (`bbb3f01`→`68471cd`). Next new-edge candidates: S1 panel (ONE VM
> calendar export blocks it), AG-2, Isagi AF-2, I029 Reo fix.

> v0.61 — **Neo Egoist League chartered + scoreboard shipped (D145)**
> 2026-08-04, same session: per-agent HP score from the tape
> (`scripts/league_table.py`, observe-only; charter in
> `company/strategy/neo-egoist-league-charter.md`). Rules v1: start
> 100 HP; 10 HP × realized R; −3 per overtime trade (>30 H4 bars);
> zero-conversion drain −1/250 bars (cap −25; advisors exempt);
> HP ≤ 0 ⇒ RELEGATION REVIEW flag (user decides — supersedes ad-hoc
> benching with due process). Trade time-limit = SCORING layer only
> (E020/E024/E026 exit-change graveyard binds). First causal table
> (val_cell_30, 2024-01→2026-07): Nagi 170.0 (n=7 thin), Chigiri
> 130.0, Rin 123.8 (n=72 anchor, EURUSD-only BY DESIGN — Barou is
> USDCAD-only, Chigiri EUR+GBP), Bachira 109.6, Reo 75.0
> (zero-conversion), Isagi 70.0, Barou 53.3. Multi-field ladder:
> cross-symbol re-runs first, then XAUUSD/XAGUSD/USOIL/USTEC (each
> gated on history + semantics audit + pre-registered causal replay),
> futures/stocks later. 7 tests (`tests/test_league_table.py`).

> v0.60 — **Night Auditor shipped (D144) + research artifacts committed**
> 2026-08-04, same session:
> - **Off-hours shifts Tier 1 BUILT:** `scripts/night_audit.py`
>   (deterministic, no LLM) audits one UTC day of tape daily at 06:30
>   via Task Scheduler (runbook §7b.10, task `NightAuditor`). Checks:
>   per-symbol coverage vs weekday H4 grid (silent-week catcher),
>   timestamp_miss regression, feed stale/refresh streaks, activity,
>   state cursor. Observe-and-draft ONLY: digest + intake stubs under
>   `<live_dir>/audits/`, one ops-Telegram line/day via the existing
>   `watchdog_alert` route. Role: `company/roles/night_auditor.md`
>   (persona Ego Jinpachi). 7 tests in `tests/test_night_audit.py`.
>   Tiers 2–3 (weekly agent triage, research batch lane) still proposals.
> - **Phase AF/AG/AH/AI artifacts COMMITTED** to
>   `finance-research-experiments` `multi-agent-ensemble` (`15cce83`,
>   35 files; raw 456MB replay caches + 7MB statement HTML gitignored
>   as reproducible). Repo restored to `main` afterwards for the v1
>   lane. The 3 research-registry test failures are branch-dependent
>   environmental (registry wants manifests from BOTH lanes) —
>   pre-existing, unchanged: 3 failed / 2058 passed.

> v0.59 — **D141 ladder executed + Phase AF causal re-tune verdicts**
> 2026-08-04, same session (D142–D143, I029 filed):
> - **Phase AF (research repo, pre-registered):** 8 IS cells (impulse
>   20/30/40/50 × rr_delta 0/+0.5, 2019–2023) + 3 sealed validation
>   replays (2024-01→2026-07), causal semantics. **Rin's DEPLOYED
>   config VALIDATED out-of-sample: PF 1.136, mean R +0.033, n=72** —
>   the anchor holds, nothing changes. Nagi imp50 (IS PF 2.65) failed
>   validation n-floor (n=10). Barou positive in ALL 8 IS cells
>   (1.14–1.39) but n<40 — near-miss, NOT benched. Bachira/Isagi/
>   Chigiri: no_causal_edge_in_grid (all cells PF<1.0); redesign
>   directions in REPORT (user directive: no benching). Isagi imp50
>   = PF 1.33/n=210 in VALIDATION ONLY (worst IS cell) — quarantined
>   as AF-2 regime hypothesis. **Reo: ZERO trades in all 11 cells →
>   I029 (P2).**
> - **Sae v2 ladder (D141→D143):** S0 shipped (`66c3bb7`, calendar
>   forecast/previous/actual fields + parse_numeric/surprise). S2/AG:
>   no arm promoted; registered near-miss — ≥8×ATR event continuation
>   +14–19 pips/trade, both IS halves positive, n=25–28 vs floor 30
>   (GBPUSD confirms shape). S3/AH: DEAD (dictionary ΔTone 38% sign
>   agreement, wrong-sign ρ) ⇒ **S4 presser listening stays gated,
>   unbuilt**. S1/AI: MT5 `CalendarValueHistory` export script +
>   normalizer ready; panel needs ONE VM run (see runbook note in
>   `phase_ai_surprise_panel/DATA_PLAN.md`). Headline/Trump lane:
>   defense-only design note; off-hours company shifts proposal
>   awaiting go/no-go (both in `company/strategy/`).
> - Research artifacts live UNCOMMITTED in `finance-research-experiments`
>   (M001 lane = `multi-agent-ensemble` branch; commit pending the
>   user's branch declaration).

> v0.58 — **Sae v2 chartered (D141)** 2026-08-04, same session: Phase
> AE's FAIL is binding for UNCONDITIONAL event plays only; the
> content-conditional hypothesis (most events are duds, the edge lives
> in the surprised minority) was never tested. Study ladder S0–S4 in
> `company/strategy/sae-v2-event-content-charter.md`; key plumbing gap
> found: `agent/news/calendar.py` DROPS the FF feed's
> `forecast`/`previous` fields and never captures `actual` — the squad
> knows WHEN news happens, not WHAT it said. `sae_enabled` stays False
> until a ladder study passes pre-registered floors.

> v0.57 — **The causality audit: the squad's replay edge was
> substantially LOOKAHEAD** 2026-08-04, same session as v0.56
> (D138–D140, I027–I028 shipped; audit chartered by the user's "full
> fix + research if needed" directive):
> - **I027/D138 (P0):** auditing whether the I024 live re-prepare
>   (history-so-far) matches the validated full-series replays found
>   TWO lookahead channels in `detect_zones` — impulse validity used a
>   median CENTERED on the impulse bar (±100 bars, so the FUTURE voted
>   on zone existence) and `fresh_zones` filtered on the BASE candle
>   index (zone tradable up to 3 bars before its displacement
>   existed) — plus unconfirmed swings feeding `_structural_tp`.
>   Empirically live fired only ~70–75% of replay signals. Fix:
>   trailing strictly-past median, `Zone.impulse_bar_index`
>   knowability gate, `confirm_bars` TP filter. Post-fix
>   prefix-vs-full parity: **ZERO divergence** (15/15 agent×symbol
>   cells) — live == replay byte-for-byte now. Audit + harnesses:
>   `reviews/audits/2026-08-04-prefix-parity/` (FINDINGS.md); pins:
>   `tests/test_causal_zones.py`.
> - **D139 (the verdict):** replay A/B 2019→2026 (36,698 bars,
>   identical data/roster, ONLY the semantics change): +29,207 pips /
>   PF 1.52 / mean R +0.30 → **−2,324 pips / PF 0.95 / mean R −0.03**.
>   G7/E004-lineage evidence invalidated as a live forecast. Per
>   agent: Bachira 1.67→0.93, Isagi 1.60→0.96 (collapse); **Rin
>   survives PF 1.20 (+1,014 pips, 218 trades)**; Nagi PF 1.47 (n=30);
>   Chigiri already-causal, unchanged-negative. Honest expectation
>   for the current parameterisation: ~breakeven; the shadow weeks
>   are MEASUREMENT. Roster re-validation/re-tuning under causal
>   semantics chartered to the research repo (fresh pre-reg; Rin is
>   the anchor). v1 LIVE record stands (live is naturally causal) but
>   old-detector v1 backtest evidence carries the same contamination
>   (logged to brain-box shared-findings).
> - **I028/D140:** `run_loop` hardened — MT5 refresh errors now retry
>   with bounded backoff (60s→900s) + `system_status` rows + one page
>   per streak; feed-staleness latch (`--feed-stale-hours` 9, FX
>   weekend-gap aware) tapes + pages starvation (the Aug 3 shape);
>   recovery rows on comeback. on_bar logic errors still crash loudly
>   (I022). Watchdog restart backstop verified (7b.9).
> - Suite **2051**: 2047 pass, 1 env-skip, same 3 pre-existing
>   research-registry fails (research repo on `main`, self-heals).

> v0.56 — **The silent-week post-mortem: squad was BLIND, not quiet**
> 2026-08-04 (D135–D137, I024–I026 all shipped; user-approved
> off-limits edits to `agent/squad/{engine,feed}.py` +
> `run_squad_live.py`, same class as the I019 precedent):
> - **I024 (P0, the headline):** Jul 28–Aug 3 weekly zip shows 0
>   proposals — the roster's `_PreparedSeries` was frozen at startup
>   `prepare()`; every bar closing after launch missed `index_by_ts`
>   and ALL bar-based agents abstained `timestamp_miss` at conf 0.00
>   (160 abstains, 69/74 tick summaries). The only 2 sighted bars
>   (Jul 28 11:00/12:00 catch-up; Bachira 0.75-conv EURUSD fade) were
>   eaten by the 2-bar burn-in ⇒ `intend()` never ran on valid data
>   all week. Fix: `SquadEngine._maybe_reprepare_roster` re-prepares
>   per symbol when a bar extends past `_roster_prepared_through`;
>   batch/replay parity byte-identical (never fires there — full
>   series prepared up front, which is also why research replays
>   could never catch this).
> - **I025:** `run_loop` mixed the mt5 feed's SLIDING-window bar
>   indices into the engine's append-only history (overwrote
>   historical bars, wrong fill bars from the first live bar).
>   Live path now `bar_index=None` + fill from next-in-batch else
>   forming bar. Masked last week only because I024 blinded agents.
> - **I026:** `Mt5Feed.poll_new_closed` only emitted the newest close
>   ⇒ H4 closes missed in a gap (Aug 3 DNS outage 10:26 UTC starved
>   the 08:00 close) were skipped forever; restarts dropped the gap.
>   Now emits every close past the cursor (oldest first) +
>   `mark_seen` seeded from `state.json` `last_bar_times`.
> - **Sae took no trades because Phase AE FAILED (v0.50/D111)** —
>   `sae_enabled=False` is the verdict holding, not a bug; FOMC week
>   proves the calendar plumbing (Karasu advisories fired on tape).
> - Aug 3 runtime death 14:07 UTC = host-level VM death (v1 review
>   confirmed DNS at 10:26, hard off 14:07), agent code blameless.
> - Tests: **11 new** (`tests/squad/test_live_reprepare.py`,
>   `tests/squad/test_feed_catchup.py`,
>   `tests/test_squad_live_mt5_loop.py` end-to-end through real
>   `run_loop`+`Mt5Feed`; 7/11 fail on pre-fix code). Suite 2050:
>   2039+1 pass, 1 env-skip, 3 pre-existing research-registry
>   fails (research repo on `main`, self-heals — v0.55 note).

> v0.55 — **Squad-goes-live day** 2026-07-28 (weekly v2 review +
> D127–D133, VM fully wired, shadow clock actually running):
> - **Weekly v2 review (Jul 15–28 bundle):** 8 of 10 weekdays silent
>   (6 symbol-bars vs ~180 expected) —
>   `docs/reviews/2026-07-28_v2_squad_week_review.md`.
> - **D129/D130 · I019 (P0, the real root cause):**
>   `run_squad_live.py --feed mt5` silently ran a frozen PaperBroker
>   snapshot (memoized at boot). Now builds `Mt5Broker` from `.env`
>   creds (v1's read-only login, Terminal A) and refuses paper
>   fallback loudly. CEO-approved off-limits edit;
>   `tests/test_squad_live_feed_broker.py`.
> - **D127 · I017 SHIPPED:** F017 `squad_tape_freshness` check +
>   runbook 7b.9 Task Scheduler wiring. **D133:** thresholds
>   recalibrated 5h/9h → 9h/13h (`last_bar_times` stores bar OPEN
>   labels; healthy age band is 4–8h — the first live pass
>   false-warned at 7.1h on a fresh tape). Closed same evening on the
>   first live `ok` (newest bars 7.4h, overall ok).
> - **D128 · I018:** /v2 next-close countdown re-anchored to the
>   tape's own `tick_summary` timestamps (was hardcoded to the wrong
>   H4 grid, off by 1h).
> - **D132 · I022:** squad Telegram copy tells the truth — live-mode
>   kickoff wording, Ctrl+C pages "interrupted" not "step budget
>   reached", unhandled exceptions page as crash not clean replay.
> - **D131 · I020 resolved (research lane):** Phase AD.2 NULL —
>   Karasu's ±15-min window is structurally inert on the H4 grid for
>   NFP/CPI/FOMC under both bar-open and entry anchors (0 fires /
>   51,042 points × 349 events); live semantics unchanged;
>   holding-window (C) prior banked AGAINST.
> - **VM state:** three scheduled tasks live (SquadLiveRuntime,
>   OpsWatchdog `--loop 300`, PlatformServer); squad connected
>   read-only (`login=436080896`, Exness-MT5Trial9), ingested the
>   12:00 UTC bar (19 thoughts incl. Bachira 0.75-conv EURUSD fade;
>   proposals correctly burn-in-gated); watchdog `overall: ok`.
> - Mac-local note: 3 research-registry pin tests fail while the
>   research repo checkout sits on `main` (concurrent session);
>   self-heals on `multi-agent-ensemble`.

> v0.54 — **Fix session D125** 2026-07-24: I014 first-run auth FIXED
> (the F008 first-visit 302 now preserves `?token=` and flushes the
> session Set-Cookie it used to drop; 5 security tests in
> `tests/security/test_i014_first_run_auth.py`). A004/I007 tz audit
> item VERIFIED CLEAN, no fix: live-feed anchors (Claims 12:30pm,
> Flash PMI 1:45pm = their known UTC schedule) prove FF publishes
> GMT/UTC as the parser assumes; VM evidence (Exness server clock
> UTC+0, H4 closes on UTC grid) validates broker epoch-as-UTC. Anchors
> pinned in `tests/test_news_calendar_tz_anchors.py`; note at
> `reviews/audits/2026-07-24-a004-calendar-tz-verification.md`.
> Intake open 7→5. Dual terminals live on VM; v1 recovered and
> trading its own account.

> v0.53 — **I015/D124 MT5 account-contention fix** 2026-07-24: the V2
> broker probe switched the VM's single MT5 terminal to the new "V2
> Platform" account; v1 saw a phantom drawdown ($969→$500) and
> correctly wrote kill.txt. Fix: `[broker] terminal_path`+`portable`
> in platform.toml pins EVERY platform-side MT5 session (F007 probe,
> F018 executor) to a dedicated second portable terminal via
> `broker_connection.terminal_launch_args()` (unset = old behaviour
> byte-identical; v2 bar feed already non-interfering — read-only
> login with v1's own creds). Runbook:
> `docs/runbooks/dual-mt5-terminals.md` (setup + v1 recovery: restore
> account in terminal A, delete kill.txt, restart). Invariant: new
> MT5 call sites in agent/platform/* route through
> `terminal_launch_args()`. 9 tests; v1 runtime paths untouched.

> v0.52 — **Sprint 3 "Stickiness" COMPLETE** 2026-07-24 (D116–D123,
> 6/6 shipped in one executor-day, verdict on tape). **P0s:** F019
> wizard recovery path + missing-broker chip + I004 token seam
> (D117); F020 `/highlights` match reports from events.jsonl (D118);
> F021 player form guide + manifest-derived gate status — Sae renders
> "Benched — fails pre-registered AE2 criterion" from the manifest's
> own strings (D119). **P1s:** F022 `/leaderboard` standings
> (agent/pair × all/30d/7d; cum-R sort, TQS tie-break; shared
> `MIN_FORM_SAMPLE=5` n-rule; nav 8→9 pills) (D120); F023 alerts
> opt-in JSONL sink (default OFF, failure-isolated) + SSE cap
> (`max_sse_streams=8`, 429-refuse-not-evict) + page backoff (D121);
> F024 watchdog front matter → `yaml.safe_load` via fast path
> (23-insertion non-test diff) (D122). **I012 rider:** in-flight KPI
> pinned (D113 semantics; exposed + fixed /hq overcount 1→0).
> Intake I003/I004/I010/I011 RESOLVED (queue 10→6). Suite
> 1784+1skip → **1969**; P0 23/23 untouched; claim audit green (F022
> + F023×2 register sections); zero-diff vs 9c0a591 empty. Honest
> notes (executor died mid-F021, parent shipped it; stale e2e
> pitch-pin from I002 repaired): sprint REPORT.md. CEO signoff D123.
> Build note: three hands, one review chain.

> v0.51 — **Chartering session** 2026-07-24 (D113–D115, docs only, no
> code). **Cycle-2 triage (D113):** I005+I006 RESOLVED via the D110
> merge; I002 → awaiting-verification (closes at VM cutover); queue
> 12 → 10 open; `experiments_in_flight` semantics locked (open
> panel/scheduled compute only). **Sprint 3 "Stickiness" scope-locked
> (D114):** F019–F024 as shipped above. **Auth migration charter
> (D115)** at `company/strategy/auth-migration-charter.md`: owner/
> viewer accounts, per-account keyring namespaces, P0 invariant binds
> to OWNER ACCOUNT not install, zero-step VM adoption, Phase 2
> (hosted) needs legal review + pen test first; implementation is its
> own sprint.

> v0.50 — **Phase AE verdict: FAIL** 2026-07-24 (D111–D112). Sae's
> event mechanics validated against a frozen 349-event NFP/CPI/FOMC
> calendar (2015–2025, primary sources): AE1 PASS (54 OOS trades)
> but **AE2 FAIL** — OOS mean TQS 0.097, CI [0.042, 0.162] vs
> 0.30/0.20 floors; 28.7% wins at 1.5R (breakeven 40%); both
> mechanics negative. AE4 clean (max incumbent delta +0.001).
> **`sae_enabled` stays False — no Aug 7 NFP arming;** hour-13 bleed
> = "avoidable, not tradable"; Karasu (Phase AD) is the only
> event-window lever. No retuning against this panel; Sae v2 needs
> fresh pre-reg. Published to `/research` (manifest + condensed
> finding). Research commits `dfe5ce1`→`2b3ef4b` on
> `finance-research-experiments::multi-agent-ensemble`.

> v0.49 — **Reconciliation merge** 2026-07-24 (D110, merge commit
> `c97e8f7`): `next-gen` merged into `product`; **`product` is the
> single serving branch** (A001/A002 P0 drift closed). Brings in the
> warm-up seeding fix (200-bar gate now seeds from history + 2-bar
> burn-in), Sae hydration (gated behind `--enable-sae`, default OFF
> pending Phase AE pre-reg), calendar cache repo-root anchor (A003)
> + fetch-failure visibility, and the I002 /v2 legibility fixes
> (quiet_reason, warm-up progress, upcoming-USD-events panel,
> Sae/Karasu on the pitch). Conflicts: `serve_platform.py` (product
> handler wins, `upcoming_events` endpoint ported inside token gate),
> RUNBOOK (union; redeploy = sec 7b.8, retargeted at `product`).
> Suite **1784 pass + 1 env-skip**; P0 23/23; claim audit green.
> D109 = secret-hygiene sweep (no secret-shaped literals in tests,
> `tests/CONVENTIONS.md`). VM cutover pending (runbook 7b.8).

> v0.48 — **Product hardening night** 2026-07-24 (D105–D108):
> ops-Telegram split (`[alerts.telegram.ops]`, OPS/DUAL_ROUTE event
> routing); audit fixes A005 (approval TTL 300 s + `approval_expired`,
> P0 pin → 23), A006 (atomic bag write), A007 (loss-cache); full audit
> filed (I005–I012, `pandas>=2.2,<3` pinned — VM venv REBUILD
> pending). Tests 1691 → 1720.

> v0.47 — **Sprint 2b Live Readiness COMPLETE** 2026-07-24
> (D097–D104): F017 Ops Watchdog (7-check registry, `watchdog_alert`
> transitions-only bus event, `/hq` chip strip, `run_watchdog.py`);
> F018 demo-order executor (the four gates' ONE caller, DEMO-ONLY
> guard in code, 0.01-lot cap, default-disabled, single-use approvals
> in `executions.jsonl`, `Mt5OrderAdapter` seam; runbook 7c ceremony
> + kill drill). Detail: `docs/00-journey.md` + sprint REPORT.md.

Read this first in a fresh chat. Deeper history: `docs/00-journey.md`
+ `docs/CHECKPOINT.md`. **Branches:** `main` = live demo agent;
**`product` = the single serving branch** (v2 platform + squad paper
+ commercial lane, post-D110 merge); `next-gen` retired as a serving
branch (feature branches → `product` from now on). Research on
`finance-research-experiments::multi-agent-ensemble`. Demo only.

## 1) What is built and working

- **Blue Lock Trading Co. (`product`):** 19-role company; review
  chain spec → research → design → architecture → build → qa →
  security\* → 7b research\* → legal\* → signoff → ship
  (\* = conditional). Sprint 0+1+2+2b+3 COMPLETE
  (5/5+3/3+6/6+2/2+6/6).
- **Real-Trading stack (default-OFF at every layer):** four-gate
  composition pinned by
  `tests/security/test_live_mode_off_invariant.py` (18 tests:
  Sprint-2 pin + 2b extensions). F009 auth, F010 claim-audit, F011
  kill-switches, F012 risk+broker-health, F013 approval+live-mode,
  F014 SSE alerts + Telegram, **F017 watchdog, F018 demo executor**
  (DEMO-only in code; enable via `[live_executor]` in platform.toml
  + live-mode ceremony; see runbook 7c).
- **R&D loop (2 cycles):** I001/I003/I004/I005/I006/I010/I011
  resolved; queue 6 open (I002 awaiting VM cutover, I007–I009,
  I012–I013); findings published: Phase AC + Phase AE honest
  negatives (on `/research` manifest); W30 rollup + cycle-2 triage on
  tape.
- **Stickiness surfaces (Sprint 3):** `/highlights` match reports,
  `/players/:id` form guide + gate status (Sae benched from the
  published AE manifest), `/leaderboard` standings (internal-only
  framing pinned; shared n<5 rule), alerts JSONL sink (opt-in) + SSE
  cap, watchdog YAML front-matter parser.
- **Public routes:** `/performance`, `/players[/:id]`, `/highlights`,
  `/leaderboard`, `/research`, `/onboarding`,
  `/settings/{broker,live-mode,kill-switches,reset-install}`,
  `/risk`, `/approvals`, `/alerts`, `/hq` (R&D pulse + F015 Org &
  Flow via `/api/hq/org`). F005 `withStates()` +
  `_BASE_CSS_VERSION = "1.1.0"` (unchanged — Sprint 3 CSS all
  page-local); nav = 9 pills.
- **Dogfood cast (F016):** 6 personas + `scripts/dogfood_personas.py`
  (in-process server, keychain-safe, no live mode by construction);
  first run 113/113 across onboarding/broker/kill/approvals/alerts.
- **Live (`main`):** unchanged. **Squad runtime:** now served from
  `product` (post-merge); warm-up seeds from history, Sae hydrated
  but OFF, calendar failures visible on /v2.
- **Tests:** **1969** (P0 invariant 23 cases untouched; claim audit
  green, 21 modules; e2e needs `PLAYWRIGHT_BROWSERS_PATH` else
  1 env-skip).

## 2) Key file paths

| Area | Files |
|---|---|
| Charter + R&D | `company/protocols/{review-chain,escalation,rd-loop,literature-standards}.md`, `company/roles/{cto,cpo,ceo,research_lead,user_advocate}.md`, `company/rd/{README,intake/{TEMPLATE,I001–I013,2026-W30-cycle2-triage.md},findings/,personas/,loop-validation.md}`, `company/strategy/{sellability-gaps,auth-migration-charter}.md`, `company/ledger/{company_state.json (140 D### + 19 roles + intake×26 + experiments),decisions_log.md}` |
| Sprint 3 stickiness (COMPLETE) | `agent/platform/{highlights,leaderboard}.py` + players.py F021 additions + alerts.py sink + alerts_sse.py cap + watchdog.py YAML parser, `company/sprints/sprint-3-stickiness/{README,F019…F024,REPORT}.md`, `company/legal/{F020,F021,F022,F023}-review.md`, tests `tests/platform/test_{highlights_*,leaderboard_*,players_form_guide,alerts_jsonl_sink,experiments_kpi_semantics}.py` |
| Sprint 2b live readiness | `agent/platform/{watchdog,live_executor}.py`, `scripts/run_watchdog.py`, `company/sprints/sprint-2b-live-readiness/{README,F017-ops-watchdog,F018-demo-order-executor,REPORT}.md`, `company/legal/{F017,F018}-review.md` + `executor-demo-warning.md`, `docs/RUNBOOK_demo_launch.md` sec 7c, tests `tests/platform/test_{watchdog_*,run_watchdog_script,live_executor_module,executor_api}.py` |
| Sprint 2 real-trading | `agent/platform/{rate_limiter,kill_switches,kill_switch_admin,risk_budget,broker_health,approval_queue,alerts,alerts_sse,alerts_telegram,auth}.py`, `agent/platform/pages.py` (KILL_SWITCHES / RISK / APPROVALS / LIVE_MODE_TOGGLE / ALERTS + HQ R&D pulse), `scripts/{serve_platform,check_claim_register,install_git_hooks}.py`, `scripts/git-hooks/pre-commit`, `company/legal/{live-mode,approval-queue}-warning.md` + `claim_register.md` |
| Sprint 0/1 backend | `agent/platform/{performance,players,research,hq (R&D pulse extension),credentials,broker_connection,onboarding}.py` |
| Tests | `tests/security/test_live_mode_off_invariant.py`, `tests/platform/{test_hq_org,test_dogfood_personas,test_hq_page_rd_pulse}.py` |
| Org web + dogfood | `agent/platform/hq.py` (`org_state()`), `agent/platform/pages.py` (HQ Org & Flow), `scripts/dogfood_personas.py`, `company/rd/personas/` |
| Strategy / Live / Squad | `agent/alphas/{concepts/{zone_alpha,_htf},zone_routing}.py`; **off-limits:** `agent/{live,risk,squad}/*`, `scripts/run_{live,squad_live}.py` |
| Docs | `docs/{CHECKPOINT,00-journey,RUNBOOK_demo_launch}.md` |

## 3) Next immediate goal

**VM cutover DONE 2026-07-28** (runbook 7b.8/7b.9: `product` clone,
three scheduled tasks, `.env` with v1 read-only creds, watchdog
`overall: ok`) — the shadow clock (D095 step 2) is finally running on
a live feed. **1) A004 FOMC live capture, Jul 29 18:00 UTC** (Funds
Rate + Statement, presser 18:30; GDP + Core PCE Jul 30) — first real
high-impact event on a healthy feed; verify Karasu advisories and the
calendar tz anchors live, leave everything running. **2) Auth
migration sprint** (D115 charter) is the next chartered build lane —
cross-user leaderboard ranking and any multi-user copy stay blocked
on it; needs a scope-lock chartering session. **3) RELAUNCH the squad runtime
on the VM** — pull `product` (D135–D140 fixes), restart the three
scheduled tasks, and verify within one H4 close that tick summaries
show real per-agent reads (zone-touch / no-breakout narratives), NOT
`timestamp_miss`. The w/c 2026-08-04 bundle is the first honest
measurement week: expect 0 silent weekdays / ~90 bars AND nonzero
proposal counts when setups occur — but with D139 expectations set
(causal semantics ⇒ ~breakeven squad; Rin is the one with a proven
causal edge; this week is measurement, not harvest). **4) CHARTER
the causal re-validation study** in `finance-research-experiments`
(fresh pre-registration, causal detector semantics, Rin's surviving
parameterisation as anchor; Bachira/Isagi need re-tuning or benching
verdicts). Open intake queue: I002 (awaiting-verification),
I007–I009, I012–I013 (I012 only awaits the D108 audit-cadence CEO
ratification — the pinned test shipped). **5) Act on AN follow-through:**
(a) VM: enable Chigiri:XAGUSD paper per `docs/runbooks/chigiri_xagusd_paper.md`
(pull `product` @ ≥84564de, field_assignments + equity=500, restart
SquadLiveRuntime); judge on fresh tape only;
(b) Barou v1.4 DONE — sealed FAIL; do not enable v14; Candidate B
needs a new pre-reg on unconsumed data if pursued;
(c) Rin:USDJPY / Chigiri:AUDUSD / Bachira:NZDUSD / Barou:USDCAD/USTEC
CLOSED. USDJPY 2023+ seal CONSUMED. Zone-grammar + v1 PositionSizer
I030 residue remains for real-order / zone-agent Tier-2 only. **6) MT5
calendar export still blocked on VM** — user must sync the Calendar
tab in the terminal Toolbox, then re-run the diagnostic script
(commit `f0a9062`) and report the Experts-tab lines (unblocks
S1/Phase AI surprise panel). **7) I030 residue:** live path
(position sizer) + zone-grammar pip thresholds remain
major-calibrated — field cards per D148 before any new symbol goes
live; USDJPY/Tier-2 replays are now VALID. S4 presser listening is
GATED SHUT (S3 dead); Trump/headline shocks advisory-lane only.

**Parked (no start without discussion):** wiring four-gate composition
to squad's real-order path; Sprint 4 `/feedback` route (D084 defers —
F013/F014 signals drain via User Advocate + CPO Monday triage);
external peer-review budget (Sprint 6+ whitepaper); squad → real
broker orders; v1 zones live-path rewrite; any touch of
`agent/{live,risk,squad}/*` from a non-integration sprint; TRUSTING
Aoshi's event trades (Phase AE FAIL stands, D111 — he is enabled for
OBSERVATION since 2026-08-13; a redesign needs fresh pre-reg); PLG
cooldown retune (E013 f/u); any spend
(Finance zero-authority).
