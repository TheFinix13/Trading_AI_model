# F002 -- user-journey memo

- **Feature:** F002 -- `/players` index + `/players/:id` bios
- **Author:** UX Researcher
- **Date:** 2026-07-21

## Target segments

Two distinct users arrive at these pages, and the pages must serve
both without pulling either off-mission:

1. **The prospect from /v2.** They just watched the pitch replay,
   noticed the roster on the sidebar, and want to understand "who
   are these characters". They know what the platform is; they
   don't yet know the players.
2. **The casual reader from search.** They googled something like
   "blue lock trading isagi" out of curiosity. They don't know
   what the platform is. The bio must stand on its own without
   the /v2 context.

## Jobs to be done

Each striker's bio page must answer, in order:

1. Who is this character on the pitch (playstyle_tag + status).
2. What is their signature setup (the ASCII diagram or single
   sentence blurb).
3. What is their trading behaviour (the 2-4 paragraph prose,
   stranger-friendly, zero "ensemble" / "aggregator" jargon).
4. What have they done recently (last 5 rows from
   `squad_live/events.jsonl`).
5. How have they evolved (bullet list of versions and dates).

The index page (`/players`) answers a different job: **which of
the ten strikers should I click first?** It should show all ten
in one glance, with playstyle_tag as the headline, status pill
(active / standby / retired) visible, and 2-3 top-line numbers
(proposals / wins / net_pips) as a hook.

## "Stranger-friendly" test

Brand Designer's copy for each bio must pass this test: a person
with zero exposure to the platform reads one bio and can then
describe the character's playstyle in one sentence. Concretely:

- "Rin: only trades EURUSD, only when the risk-to-reward is exactly
  2." -> pass.
- "Rin: cold-anchor precision striker with strict-RR structural-
  cleanliness zone gating." -> fail.

Bios must survive the stranger test even for auxiliary strikers.
Karasu is not less bio-worthy for being side-channel-only; his
story is "the striker who never takes a trade".

## Non-goals ratified

Per the F002 spec, the following adjacent needs are explicitly
NOT in scope:

- **No** editable bio content. Users cannot annotate.
- **No** per-character P&L attribution chart. Text stats only.
  (Sprint 3+ if the numbers ever warrant it.)
- **No** side-by-side comparison view.
- **No** commentary generation ("today Bachira felt aggressive").
- **No** search / filter across characters (ten characters, index
  page suffices).
- **No** localisation. English only.

## Accessibility

- Semantic HTML: `<h1>` for character name, `<h2>` for each
  bio section, `<dl>` for stats key-value list.
- The signature-setup ASCII lives in a `<pre>` with a
  `role="img"` and `aria-label` describing the setup in plain
  language ("Isagi: zone touch fade against daily trend, target
  1.5R").
- Status pills use both colour AND text — colour-blind users still
  see "retired" / "active" / "standby" labels.

## Risks flagged

- **Sae + Kunigami low-data risk:** Sae is disabled by default
  (Phase AE pre-reg pending). Kunigami is retired from proposing.
  Both will show near-zero live stats. The bio pages must not
  feel broken as a result — the source_hint copy explains why.
- **Character-name spelling drift:** Copy in bios must match the
  spellings in `company/brand/copy.md`. Any drift is a QA gate
  failure.

## Handoff

Ready for UI Designer -> mocks for `/players` index + one bio-page
mock at desktop and 375 px.
