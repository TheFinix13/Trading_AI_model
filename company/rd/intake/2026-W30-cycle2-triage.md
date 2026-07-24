# R&D intake — cycle-2 triage (2026-W30, 2026-07-24)

- **Triaged by:** CPO (Noel Noa), with User Advocate signal review
- **Decision:** D113 · Companion: D114 (Sprint 3 scope-lock)
- **Trigger:** post-D110 state change (reconciliation merge landed the
  I002/I005/I006 fixes) + Sprint 3 scoping needs a clean queue.
- **Queue at open:** 12 open items (I002–I013). **At close: 10 open**
  (I005, I006 resolved; I002 → awaiting-verification, still counted
  open).

## Dispositions

| Item | Disposition | Rationale (one line) |
|---|---|---|
| I002 dashboard silence | `awaiting-verification` (open) | Fix LANDED via D110 merge (`c97e8f7`) — quiet-reason line, warm-up progress, upcoming-events panel; closes only when the VM cutover (runbook 7b.8) confirms the /v2 signals on the serving host. |
| I003 broker wizard dead-end | P2→**P1**, routed → **Sprint 3 F019** | Dogfood-found churn point on a paying customer's first screen; smallest pool item with the clearest churn story. |
| I004 internal-token pin | P3 kept, **bundled into F019** | One config-resolution seam on the same surface F019 already touches; rides early instead of waiting for the packaging sprint. |
| I005 branch drift (P0) | **RESOLVED** | D110 merge (`c97e8f7`) made `product` the single serving branch; 1784+1 skip, P0 invariant 23/23, claim audit green on the merged tree. |
| I006 news-cache path split | **RESOLVED** | Fix commit `be5706e` (config-dir anchor) arrived with the D110 merge; writer and watchdog reader now share one absolute anchor. |
| I007 calendar/broker tz verify | P1 re-affirmed, open | Verify-then-fix needs a live event captured on the VM (next: FOMC Jul 28–29); route updated — next-gen lane retired, code now on `product`. Not Sprint 3 (needs live capture, not read-only work). |
| I008 Windows test blind spot | P2 re-affirmed, open | Half-delivered: F018's adapter seam covers the mac-CI half; the pre-demo VM checklist folds into the 7b.8 cutover preflight. Process item, not feature scope. |
| I009 pandas pin | open, split state | Repo side done (`pandas>=2.2,<3`); VM venv still holds 3.0.3 — closes when the cutover rebuild reports `pandas<3`. Ops step, not sprint work. |
| I010 alerts durability + SSE cap | P2 re-affirmed → **Sprint 3 F023** | Protects the evidence trail the sales story depends on; small and bounded; P1-in-sprint. |
| I011 watchdog front-matter parser | P2 re-affirmed → **Sprint 3 F024** | The company loop's own watchdog must not mis-parse a P0's priority; PyYAML swap, small; P1-in-sprint. |
| I012 KPI semantics + audit cadence | P3 re-affirmed, open | Semantic call MADE: `experiments_in_flight` = open panel or scheduled compute only (queued states excluded; truthful value today 0). Pinned test flagged to the build executor; D108 cadence still awaits CEO ratification. |
| I013 Sae v2 finer-timeframe | P3, stays **parked** (research) | Un-park gate unchanged: M5/M1 + surprise-data plan, then fresh pre-registration (D111 stop rule — no v1 retune). |

## KPI update

- `intake_items_open`: 12 → **10** (resolved items don't count;
  awaiting-verification counts as open).
- `intake_items_closed_last_7d`: 1 → **3** (I001 on 07-23; I005, I006
  today).

## Notes for the next cycle

- Three items (I002, I007, I009) now block on the same event: the VM
  cutover to `product` (runbook 7b.8). One CEO ops session closes or
  advances all three.
- Sprint 3 (D114) drains three queue items (I003+I004 via F019, I010
  via F023, I011 via F024) — queue depth drops to 7 open on a full
  sprint ship, of which only I007/I009 are engineering-shaped.
