# R&D loop validation — cycle 1 (2026-W30)

Written 2026-07-23. The rd-loop protocol (D085) was adopted
2026-07-22 with the explicit warning that a loop on paper is
aspirational until a real cycle runs through it. This memo records
what cycle 1 actually was, how it was measured, and the verdict.

## The cycle-1 workload

| Loop stage (rd-loop.md) | What actually happened | Ledger |
|---|---|---|
| Intake (§1–§2) | I001 (post-mortem, filed 2026-07-22) + I002 (dogfood, real CEO signal, filed 2026-07-23) | — |
| CPO triage (§3) | First real drain 2026-07-23: I001 self-triage confirmed; I002 classified FEATURE-REQUEST / P1 in the same session it was filed | D087, D088 |
| Routing (§4) | I001 → process (resolved via codification); I002 → product (Sprint 3 / next-gen candidate — consciously NOT implemented in this session, respecting branch scope) | D087, D088 |
| Publish (§5) | Phase AC condensed finding published to `company/rd/findings/` + publication-manifest provenance updated — the cross-repo bridge exercised for real (research repo read-only) | D089 |
| Loop closure (§6) | I001 closed with status + measurement (Sprint 2 duration, its own pre-declared discriminator) + n/a notify; W30 rollup published | D087, rollup |

## Measurement criteria and observed values

| Criterion | Target (protocol) | Observed cycle 1 | Pass? |
|---|---|---|---|
| Time-to-triage vs SLA | Weekly Monday drain; P0 on-arrival (§3) | I001: filed Wed 07-22, triaged at filing, CPO-confirmed 07-23 (~46 h, inside a weekly SLA). I002: triaged in the same session it was filed (≈ 0 h). No P0s arrived. | PASS |
| % intake with route decisions | 100% | 2/2 (I001 process, I002 product) | PASS |
| Findings published | ≥ 1 real finding (the Wed deliverable in §9's operating calendar) | 1 — Phase AC negative, with commit-SHA provenance and FDR arithmetic intact | PASS |
| End-to-end loop latency (signal → filed → triaged → routed) | No numeric SLA pre-declared; measured for baseline | I002: CEO signal (2026-07-23) → filed → triaged → routed same day. I001: 46 h filed → resolved. | PASS (baseline recorded) |
| Ledger link (§7) | Every P1+ routing gets a D### in both ledgers | D087–D090, MD + JSON 1:1 | PASS |
| Weekly rollup (§6) | Published with opened/closed/depth/aged | `intake/2026-W30-rollup.md` | PASS |

## Honest caveats

- **Small-N.** Two intake items, one finding, one drain. Cycle 1
  proves the pipes carry water, not that they carry volume. The
  ≥ 10-item drain trigger, the aged-30d flag, and the notify
  handshake (no external submitter yet) remain unexercised.
- **Same-executor triage.** Filing (User Advocate) and triage (CPO)
  were performed by one executor wearing both personas in one
  session — consistent with the I001/D087 codification, but it means
  time-to-triage ≈ 0 is an artifact of the topology, not evidence of
  a fast SLA under load.
- **The finding was pre-staged.** Phase AC was already flagged as the
  publication candidate in `findings/README.md`; cycle 1 demonstrated
  the condensation + manifest + ledger path, not the discovery path.

## Verdict — cycle 1: PASS

Every loop stage fired at least once with a real artifact on tape,
every intake item has a status and a route, the first honest-negative
finding is published with reproducibility anchors, and the rollup +
ledger sync are on-record. The loop is live. Re-validate at cycle 2+
under the conditions cycle 1 could not test: an external submitter
(notify handshake), a P0, and a queue deep enough to make the drain
non-trivial.
