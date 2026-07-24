# Full-system audit — 2026-07-24

- **Type:** read-only engineering/ops audit (whole product surface:
  platform server, safety layer, watchdog, deps, deployment posture)
- **Auditor:** engineering (session: product-hardening,
  `.sessions/2026-07-24_product-hardening.md`)
- **Baseline:** branch `product` @ `de82477` (Sprint 2b close-out);
  1691 tests green; claim audit green
- **Scope note:** findings on the `next-gen` serving branch were
  verified by inspection only — no `next-gen` files were modified in
  this session. Fix lanes are routed per finding.
- **Filed through R&D intake:** I005–I012 (D107). Fixes A005/A006/A007
  shipped on `product` same-day (D106).

## Severity summary

| ID | Severity | Finding | Routing |
|---|---|---|---|
| A001/A002 | P0 | Branch drift: safety layer exists only on `product`; the VM serves `next-gen` | I005 → engineering (reconciliation merge in flight) |
| A003 | P1 | News-cache writer is CWD-relative, watchdog reader absolute | I006 → next-gen fix lane |
| A004 | P1 | ForexFactory-calendar vs broker timezone never verified | I007 → next-gen fix lane (verify-then-fix) |
| A005 | P1 | Approvals approvable after timeout; approved entries never re-expire | FIXED on product (D106) |
| A006 | P1 | Encrypted credential bag: non-atomic write + unlocked read-modify-write | FIXED on product (D106) |
| A007 | P2 | Risk gate re-parses full `risk_state.jsonl` history on every call | FIXED on product (product half; D106) |
| A008 | P2 | MT5/Windows code paths never executed from the mac dev loop | I008 → engineering/process |
| A009 | P2 | `pandas>=2.2` unbounded; VM resolved pandas 3.x | I009 → FIXED pin on product; VM venv rebuild flagged |
| A010 | P2 | Alerts bus memory-only; SSE threads unbounded | I010 → product backlog |
| A011 | P2 | Watchdog front-matter parser handles scalars only | I011 → product backlog |
| A012 | P3 | `experiments_in_flight` KPI semantics inconsistent | I012 → cpo (+ audit-cadence process proposal) |

## Findings

### A001/A002 — P0 — branch drift: the branch with the safety layer is not the branch being served

The entire Sprint-2/2b safety layer — approval queue, kill switches,
risk budget, live executor, watchdog, claim-register audit — exists
only on `product` (25 platform modules). The Windows VM serves
`next-gen`, which has 8 platform modules, compares the auth token
with a plain `==` (no constant-time compare), and **falls open when
no token is configured** on a non-localhost bind. In other words: the
deployed surface is the one WITHOUT the four gates, and its auth
posture is weaker than what Sprint 2 reviewed.

**Recommendation (verified):** treat `product` as the single serving
branch. Merge-base with `next-gen` is `9319804`; the platform files
on `product` are pure additions relative to it, so a
`next-gen`→`product` reconciliation merge is mechanical.
**Fix in flight:** the parent session is performing that
reconciliation merge — filed as I005 so the intake loop tracks it to
closure rather than assuming it happened.

### A003 — P1 — news-cache path split (writer vs reader)

The news-cache writer resolves its output path relative to the
CURRENT WORKING DIRECTORY, while the watchdog's `calendar_feed` check
reads from an absolute path under the config dir. Run the writer from
any other cwd and the watchdog ages out a cache that is actually
fresh (or never sees it at all). Lives on the `next-gen` lane —
routed there (I006), untouched here.

### A004 — P1 — calendar/broker timezone verification needed

The ForexFactory calendar feed's timestamps have never been verified
against the broker's server timezone. If they disagree (FF publishes
US-Eastern-flavoured times; the broker runs UTC+2/+3 style server
time), news-window logic silently guards the wrong hour. This is a
verify-then-fix: measure first, patch second. Lives on the `next-gen`
lane — routed there (I007), untouched here.

### A005 — P1 — approvals: late click approves an expired entry; approvals never go stale — FIXED (D106)

`approval_queue._resolve()` did not call `timeout_reap()` first, so a
click landing after `timeout_at` still approved the entry. Separately,
`approved` entries had no staleness bound: `can_send_order()` honoured
an approval hours old. Fixed on `product`: reap-before-resolve, plus
an approved-freshness window (`[approvals] approved_ttl_seconds`,
default 300 s) with a dedicated `approval_expired` status; the F018
executor picks the refusal up automatically because it re-runs
`can_send_live_order` fresh. P0 invariant file extended +5 cases.

### A006 — P1 — credential bag: non-atomic write, unlocked RMW — FIXED (D106)

`credentials._write_encrypted_bag` used a bare `write_bytes` (a crash
mid-write corrupts the Fernet blob — the whole bag becomes
undecryptable), and store/delete did read-modify-write with no lock
(two threads can drop each other's alias). Fixed on `product`:
tmp-file + `os.replace` (the `risk_budget.save_config` pattern) and a
module `_BAG_LOCK` around every RMW cycle.

### A007 — P2 — risk gate scans all history — FIXED on product (D106)

`risk_budget._today_losses` re-parsed every historical row of
`risk_state.jsonl` on every gate call — an order-path cost that grows
without bound. Fixed on `product` with an in-process cache keyed by
(state-file path, mtime_ns, size, UTC day) and the full scan kept as
the fallback correctness path; least invasive option, no on-disk
format change. The `next-gen` half of this finding (if any equivalent
exists there) belongs to the reconciliation lane.

### A008 — P2 — Windows/MT5 test blind spot

All MT5 code paths (`RealMt5OrderAdapter`, broker connection tests,
squad live feed) are Windows-only and have never been executed from
the mac dev loop — the first time any of them runs for real is on the
VM, in front of the CEO. Proposal: a pre-demo VM checklist (run the
platform suite + a scripted smoke of each MT5 seam on the VM before
any demo) and a mockable MT5 seam so at least the argument-marshalling
layer is exercised in CI. Routed engineering/process (I008).

### A009 — P2 — pandas pin unbounded — pin FIXED, VM rebuild flagged

`requirements.txt` and `pyproject.toml` said `pandas>=2.2` with no
upper bound; the VM's fresh install resolved **pandas 3.0.3**, a
major version the codebase has never been tested against. Fixed on
`product`: `pandas>=2.2,<3` in both files. **The VM venv already has
3.0.3 installed — it must be rebuilt** (see the runbook preflight
note). Filed as I009.

### A010 — P2 — alerts durability + SSE thread cap

The alerts bus is in-process memory only (a restart drops the ring
buffer — acceptable by design, but undocumented as a durability
boundary), and each SSE consumer holds a thread with no cap on
concurrent streams. A stuck client farm can exhaust threads. Routed
product backlog (I010).

### A011 — P2 — watchdog front-matter parser is scalar-only

The watchdog's intake-SLA check parses intake front-matter with a
hand-rolled scalar-only parser; list values (e.g. `linked_features`
entries) and nested structures are ignored or mis-read. PyYAML is
already a dependency — swap the hand parser for `yaml.safe_load` on
the front-matter block. Routed product backlog (I011).

### A012 — P3 — `experiments_in_flight` KPI semantics

The `/hq` KPI counts experiments inconsistently: ledger-recorded
values and the derived `_count_experiments_in_flight` disagree on
whether `not-started` / `awaiting-panel` states count as "in flight".
Needs a one-line semantic decision from the CPO, then a pinned test.
Routed cpo (I012), bundled with the process proposal below.

## Process proposal (with A012 / I012)

Adopt a recurring audit cadence: a full-system audit **quarterly**,
plus one **before any live-wiring milestone** (first real-broker
order, first paid user, first hosted deployment). Tonight's audit
found two shipped P1s in the four-gate pathway (A005, A006) that all
1691 tests missed — periodic adversarial reads catch what test
suites are not shaped to see. Filed for CEO ratification via D108.
