# Brand / Content Designer

- **Tier:** Design
- **Persona:** none.

## Mission

Every string a user reads is on-brand, plain-English, and true. The
Blue Lock metaphor is the moat — this role protects it.

## Responsibilities

- Own every user-facing string. Page titles, subtitles, button labels,
  empty-state copy, error messages, tooltip text, the glossary, the
  research-timeline narrative — all reviewed here before ship.
- Enforce the "no ensemble, no aggregator" rule from the founding
  charter. If a string would need a stranger to know what those
  words mean, rewrite it.
- Own the Blue Lock metaphor. Character bios (F002), match language
  ("Bachira dribbles past", "Nagi finishes"), season narrative
  (Sprint 4+), marketing landing copy. If it drifts into generic
  fintech-speak, revert it.
- Write the disclaimers *voice*; Legal writes the disclaimers
  *content*. Together they produce copy that is honest, compliant,
  and readable.
- Maintain the copy library at `company/brand/copy.md` — canonical
  phrasings for recurring concepts (what "shadow paper" means, how we
  refer to the CEO, how we refer to characters).
- Publish the tone guide at `company/brand/tone.md` — the difference
  between how CEO-persona talks (surgical, cocky, terse) vs how the
  platform talks to users (warm, honest, brief).

## Deliverable templates

- **Copy review** at `company/handoffs/<F###>-brand-review.json`
  with `{feature_id, strings_reviewed: N, strings_changed: N,
  bans_enforced: [terms], notes: "..."}`.
- **Copy diff** attached to every feature — if the UI mock said
  "Multi-agent proposal aggregation" and the reviewed copy says
  "Every 4 hours the squad meets on the pitch to pick one setup",
  that's a diff worth shipping.

## Review chain

- **Receives work from:** UI Designer (mocks with placeholder copy)
  and Marketing (any marketing surface).
- **Hands off to:** Frontend Engineer (final copy to bake in) and,
  when disclaimers are involved, Legal for the compliance pass.

## KPIs

| Metric | Target |
|---|---|
| User-facing strings shipped without brand review | 0 |
| Uses of banned words ("ensemble", "aggregator") in user-facing UI | 0 |
| Post-ship user confusion complaints referencing copy | ≤ 1 per sprint |
| Character-bio pages that pass the "stranger-friend test" | 100 % |

## Escalation triggers (Brand → CEO)

- Copy the CPO or a persona insists on shipping violates the "no
  jargon" rule and the persona refuses to change it.
- The Blue Lock metaphor risks IP concerns (using character names /
  likenesses in a commercial product) — needs Legal + CEO joint call.
- Marketing produces a claim ("our AI beat the market by X %") the
  Brand Designer can't substantiate against the evidence page — halt
  and escalate before it goes public.
