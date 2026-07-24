# F021 — Player career depth: per-agent form guide on `/players/:id`

- **Sprint:** sprint-3-stickiness
- **Priority:** P0 (in-sprint) · Size **M**
- **Source:** stickiness pillar + the D111/D112 honest negative — the
  strongest trust asset we own should be visible where users look at
  the player, not only in the research manifest.
- **Consumes:** F002 `/players/:id` (`players.py` — `_read_events`,
  `_stats_for_agent`, `_recent_activity` already exist), `squad_live/
  events.jsonl`, the `/research` manifest (`research.py`) for the
  Phase AE finding link, roster/gate metadata
- **Consumed by:** `/players/:id` (extended), `/players` index cards
- **Feature flags:** `legal_relevant: true` (public claim data + Blue
  Lock character surface — Brand sweep), `security_relevant: false`
- **Claims introduced:** YES — rolling TQS, rolling win-rate, form
  sparkline series, gate-status strings. Register each (module
  `players.py`, new accessors, provenance disclaimer: shadow-paper
  activity/quality metrics, NOT profit performance).

## User story

A fan opens Sae's player page and sees the truth told like a squad
sheet: "**Benched — Phase AE FAIL.** Event mechanics tested against
349 events (2015–2025): 28.7% wins at 1.5R where breakeven needs 40%.
Read the finding →". On Isagi's page: a 20-trade TQS sparkline, form
trend, last five decisions with outcomes, current gate status. The
negative is not buried; it is the character's story arc — and the
reason a stranger trusts the rest of the numbers.

## Scope (in)

1. **`players.py` extensions (read-only):**
   - `form_guide(agent_id, live_dir=None, n=20) -> dict` — rolling
     TQS series + rolling win-rate over the last `n` closed trades
     (fewer if history is short; explicit `sample_size` field),
     computed from the same event rows `_stats_for_agent` reads.
   - `gate_status(agent_id) -> dict` — current roster/gate state per
     agent; for Sae: `{"status": "benched", "reason": "Phase AE FAIL",
     "finding_url": "/research#phase_ae_sae_event_specialist"}`
     sourced from roster metadata + the research manifest, not
     hardcoded prose.
   - `recent_decisions(agent_id, n=5)` — reuse/extend
     `_recent_activity` with outcome fields.
2. **UI:** sparkline rendered as inline SVG (no chart dependency) on
   `/players/:id`; compact form strip (e.g. W-L-W-W-Q) on `/players`
   index cards; gate-status badge incl. the benched state. All under
   `withStates()`; every stat labelled with its window ("last 20
   closed shadow-paper trades") and `sample_size`.
3. **Small-sample honesty:** below a minimum sample (default 5 closed
   trades) the win-rate renders as "insufficient sample (n=…)" — no
   percentage. The claim register entry records this rule.

## Scope (out)

- No changes to how TQS is computed or logged (read-only consumer).
- No cross-agent comparison table (that's F022's surface).
- No historical backfill beyond what `events.jsonl` already holds.
- No roster/gate state MUTATION — display only.

## Acceptance criteria

- Form guide numbers equal an independent recomputation from fixture
  events (equality-tested, not snapshotted).
- Sae's page shows the benched badge + FAIL reason + working link to
  the published finding; copy passes the banned-words sweep.
- Agents with zero closed trades render the honest empty state.
- New public fields registered; claim audit green; Legal review on
  tape (Brand co-check for character-voice copy).

## Test plan

`tests/platform/test_players_form_guide.py` (rolling windows, short
history, insufficient-sample rule, zero-history empty state, benched
gate status incl. finding link); `test_players_page.py` (extend:
sparkline SVG present, badge render, index form strip). Target ≥ 20
tests.

## Files touched (expected)

Edited: `agent/platform/players.py`, `agent/platform/pages.py`,
`company/legal/claim_register.md` (F021 additions to the F002/players
section). No new modules expected; if the SVG helper grows, it lands
in `pages.py` alongside the existing render helpers.
