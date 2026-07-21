# Persona Handoff — the mechanics

When persona **X** completes their stage and hands off to persona
**Y**, they produce a **handoff artifact** with two components:

## Component 1 — the JSON blob

Written to `company/handoffs/<feature_id>-<from>-to-<to>.json`. This
file is the machine-readable record; the HQ dashboard consumes it,
future audits reference it, and persona Y reads it before starting
their stage.

**Canonical schema:**

```json
{
  "from_role": "cpo",
  "to_role": "ux_researcher",
  "feature_id": "F001",
  "timestamp": "2026-07-21T15:30:00Z",
  "deliverables": [
    "company/sprints/sprint-0-trust-foundation/F001-performance-page.md"
  ],
  "notes": "Feature spec is locked. Prospects need to see the equity curve within 10 seconds of landing on the page. Data source is squad_live/events.jsonl + state.json sidecars.",
  "blockers": [],
  "review_criteria": [
    "Confirm the target user segment (retail forex trader evaluating an AI product) is right",
    "Confirm the 'trust in 10 seconds' framing survives contact with 3 real users (or CEO-as-proxy)",
    "Confirm the equity-curve visualisation is accessible (colour-blind palette)"
  ]
}
```

### Field semantics

| Field | Meaning |
|---|---|
| `from_role` | Role ID (matches `roles[].id` in `company_state.json`). |
| `to_role` | Role ID this handoff hands to. |
| `feature_id` | `F###` matching a `features[].id` entry. |
| `timestamp` | ISO 8601 UTC — when the handoff was written. |
| `deliverables` | Absolute-from-repo-root paths to every artifact produced. Each MUST exist on disk. |
| `notes` | 1–5 sentences. What the next persona should know that isn't obvious from the artifacts. |
| `blockers` | Empty array if none. Otherwise `[{summary, awaiting: "ceo"|"cpo"|"cto"|"<role>", raised_at}]`. |
| `review_criteria` | 2–5 bullets. What "done" looks like for the receiving persona — helps them recognise when their own stage is complete. |

### Naming conflicts

If persona X hands off to persona Y twice on the same feature (rework
loop), the second file is
`<feature_id>-<from>-to-<to>-r2.json`, then `-r3.json`, and so on.
Existing files are never overwritten; the full handoff history stays
on disk.

## Component 2 — the narrative

Alongside the JSON, persona X writes a 3-sentence narrative appended
to `company/ledger/decisions_log.md`:

```markdown
### D057 · 2026-07-21 · cpo → ux_researcher · F001

Locked the /performance route spec: equity curve, drawdown, Sharpe,
win rate, per-pair breakdown, powered by squad_live/events.jsonl.
Handoff to UX Researcher to validate the "trust in 10 seconds"
framing and produce a jobs-to-be-done table for the target segment
(retail forex trader evaluating an AI product). Handoff artifact:
`company/handoffs/F001-cpo-to-ux_researcher.json`.
```

### Why both?

- **JSON** is for machines: the HQ dashboard shows the Kanban card
  moving, and audits/tests can validate the graph of handoffs.
- **Narrative** is for humans: the CEO reads the decisions log to
  understand what's happening this sprint without opening every
  handoff artifact.

## The receiving persona's obligations

Persona Y, on picking up the handoff:

1. **Reads the handoff JSON first.** Not the spec, not the ledger —
   the handoff. It contains the notes and review criteria calibrated
   for this transition.
2. **Reads the deliverables listed.** Every path in `deliverables[]`
   is required reading.
3. **Confirms receipt** by updating the feature row in
   `company_state.json`: `current_stage` moves forward,
   `current_owner_role` becomes Y, `age_in_stage_days` resets to 0.
4. **Adds a `history[]` entry** for the transition.
5. **Only then starts work.** Skipping the handoff and diving into
   the spec is an anti-pattern — persona X's notes exist precisely
   because they know something the spec doesn't say.

## Worked example — F001, `cpo → ux_researcher`

### Handoff JSON

`company/handoffs/F001-cpo-to-ux_researcher.json`:

```json
{
  "from_role": "cpo",
  "to_role": "ux_researcher",
  "feature_id": "F001",
  "timestamp": "2026-07-21T15:30:00Z",
  "deliverables": [
    "company/sprints/sprint-0-trust-foundation/F001-performance-page.md"
  ],
  "notes": "The trust pillar is the whole point of Sprint 0. This is the feature that most directly delivers it. Prospects should see the equity curve within 10 seconds of landing on /performance. Data source is squad_live/events.jsonl + state.json sidecars — no new backend infrastructure. Blue Lock metaphor may show up in captions ('Bachira: 24 goals this month') but the *headline* number is the account equity curve.",
  "blockers": [],
  "review_criteria": [
    "Confirm the target user segment (retail forex trader evaluating an AI product) is right for this feature",
    "Confirm the 'trust in 10 seconds' framing survives contact with 3 real users (or CEO-as-proxy dogfood)",
    "Confirm the equity-curve visualisation is accessible — colour-blind palette, screen-reader labels for the summary stats",
    "Identify at least one adjacent user need this feature does NOT try to solve (feeds the non-goals list)"
  ]
}
```

### Decisions-log narrative

Appended to `company/ledger/decisions_log.md`:

```markdown
### D003 · 2026-07-21 · cpo → ux_researcher · F001

Locked the /performance route spec: equity curve + drawdown + Sharpe
+ win rate + per-pair breakdown, sourced from
squad_live/events.jsonl and state.json sidecars, no new backend.
Handoff to UX Researcher for a research memo — target user is the
retail forex trader evaluating an AI product; framing to validate is
"trust in 10 seconds"; accessibility (colour-blind, screen reader)
must land in this iteration. Handoff artifact at
`company/handoffs/F001-cpo-to-ux_researcher.json`.
```

### Ledger update

In `company/ledger/company_state.json`, the F001 row transitions:

```json
{
  "id": "F001",
  "current_stage": "research",
  "current_owner_role": "ux_researcher",
  "age_in_stage_days": 0,
  "history": [
    {"stage": "spec", "at": "2026-07-21T14:00:00Z",
     "role": "cpo",
     "deliverable": "company/sprints/sprint-0-trust-foundation/F001-performance-page.md",
     "note": "Spec locked."},
    {"stage": "research", "at": "2026-07-21T15:30:00Z",
     "role": "ux_researcher",
     "deliverable": "(pending)",
     "note": "Handoff received from CPO. Research memo pending."}
  ]
}
```

## Anti-patterns

- **Handoff-without-deliverables.** A JSON blob with an empty
  `deliverables` array is not a handoff — it's a note-to-self.
  Persona X must produce at least one on-disk artifact before Y
  starts.
- **Silent handoff.** Updating the ledger without writing the JSON
  breaks the audit trail. Both are required.
- **Narrative-only handoff.** Skipping the JSON to save time breaks
  the HQ dashboard's Kanban movement and future automation.
- **Reading the spec instead of the handoff.** The handoff notes are
  written for the *next* stage's context; the spec is written for the
  *whole feature*. They are not interchangeable.
- **Overwriting a prior handoff file.** Rework loops append (`-r2`,
  `-r3`), never overwrite. History is evidence.
