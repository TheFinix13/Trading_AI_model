# F021 — Legal review (player career depth: form guide + gate status)

**Verdict:** APPROVED — claims registered in-commit; the benched copy
is manifest-sourced (already Legal-gated at D112); Brand sweep clean.

## Why this review fired

`legal_relevant: true`: `/players/:id` and the `/players` index gain
public performance-shaped numbers (rolling TQS series, windowed
win-rate, W/L form, net pips over the window) plus a character-voice
gate surface ("Benched — <verdict>") that quotes a published research
finding.

## Claims

Every public field of the three new `agent/platform/players.py`
accessors (`form_guide`, `gate_status`, `recent_decisions`) and both
new constants (`MIN_FORM_SAMPLE`, `FORM_WINDOW_DEFAULT`) is registered
in `company/legal/claim_register.md` §F021 in the same commit, under
the provenance disclaimer "shadow-paper activity/quality metrics, NOT
profit performance". Every stat names its window (`window_label`) and
its `sample_size` in the payload, and the page caption repeats the
window in plain words ("last N closed shadow-paper trades").

## Honesty mechanics reviewed

1. **Insufficient-sample rule (rolling constraint, shared with
   F022).** Below `MIN_FORM_SAMPLE` (5) closed trades the win-rate is
   `None` in the payload and the UI renders the literal
   "insufficient sample (n=…)" note — no percentage is ever computed
   from a sub-5 sample. Pinned by module tests (n=0, n=3, n=5
   boundary) and page copy tests. Rendering any percentage below the
   floor, or lowering the constant, requires a fresh Legal review.
2. **Recomputability.** Form-guide numbers are equality-tested
   against independent recomputations from fixture rows, not
   snapshotted.
3. **The benched copy is not prose.** `gate_status` only renders
   "benched" when the roster row's `finding_campaign` resolves to a
   PUBLISHED `fail`/`dead` entry in the CPO publication manifest —
   the reason string and headline stat are the manifest's own fields,
   which passed Legal at D112. Manifest missing, unpublished, or a
   non-fail verdict → honest "standby" fallback (all three pinned by
   tests). No hardcoded verdict prose exists in `players.py` or
   `pages.py`.
4. **Zero-history days are honest.** An agent with no closed trades
   renders "No closed shadow-paper trades on tape yet" — the F005
   empty-state posture, no fabricated form.

## Brand sweep (character-voice co-check)

The added template strings contain neither "ensemble" nor
"aggregator". The benched surface uses the squad register already
established on /v2 ("Benched", "Read the finding") and quotes the
Phase AE verdict label verbatim from the manifest — the honest
negative rendered as the character's story arc, per the F021 spec's
user story. No profit language, no "verified", no forward-looking
claims.

## Rolling constraints (on tape)

- The insufficient-sample rule above (shared F021/F022).
- The benched state must remain manifest-derived; hardcoding a
  gate reason string into the roster or pages is a Legal regression.
