# Blue Lock IP posture -- F002 legal note

- **Feature:** F002 -- `/players` + `/players/:id`
- **Author:** Legal
- **Date:** 2026-07-21

## Canonical disclaimer text

The following text is authoritative. Any surface that names Blue
Lock characters must render this exact string (or a Legal-approved
translation) inside a `.disclaimer` block. It also appears in
`company/legal/disclaimers.md` under key `third-party-name-usage`.

> Blue Lock is a manga / anime by Yusuke Nomura and Muneyuki
> Kaneshiro, published by Kodansha. Characters here are named as
> homage to describe our AI agents' trading playstyles; no
> affiliation, endorsement, or commercial arrangement is claimed.

## Why we can use the names (analysis)

- **Nominative-use / commentary posture.** Character names appear
  as *descriptive metaphors* for internal AI-agent playstyles
  ("cold geometric precision", "monstrous dribble rebel"). No
  merchandise, no cosplay, no character art, no manga-panel
  reproduction. The names function as reference labels for
  algorithms, similar to how research papers reference "the
  Kalman filter" or "Barnes-Hut simulation".
- **No implied endorsement.** Every user-visible bio page renders
  the disclaimer above the copy fold. The `/hq` dashboard and
  the CEO's public messaging never claim a partnership with
  Kodansha, Nomura, or Kaneshiro. Marketing copy is explicitly
  scoped away from any framing that would suggest a licence.
- **No character likeness use.** No visual assets from the
  manga / anime appear on the platform. Character bio pages use
  ASCII diagrams that describe *trading setups*, not the
  characters themselves.
- **Non-commercial in Sprint 0.** Sprint 0 does not monetise. The
  first paid surface (Sprint 6+) will re-audit IP posture with
  a specialist attorney before launch.

## Fallback: generic naming plan

If Kodansha or a rights-holder objects (formal request, C&D, or
correspondence), CEO decides in one of three lanes:

1. **Keep names, add explicit "unofficial fan project" line.**
   Add a paragraph to the disclaimer describing this posture and
   remove any commercial framing that hasn't already been removed.
2. **Rename all agents to generic labels** (`Striker 1` through
   `Striker 10`, keeping trading behaviour and doctrine intact).
   The migration is code-scoped: `agent_id` values on the wire
   change from `isagi_yoichi` -> `striker_1`, ledger references
   update, and every user-facing surface renders the generic
   name. Tests migrate in one pass.
3. **Rename to a different metaphor family** (colours, planets,
   etc.). Same code-scope as (2). CEO chooses the theme.

The engineering estimate for path (2) is a single-day migration:
one dictionary at `agent/platform/players.py::_ROSTER`, plus
downstream string replacements. The doctrine files in
`docs/canon-doctrine/` would be reworded but the trading logic is
name-agnostic.

## Claim register (F002)

| Claim on any bio page | Verified against | Signed off by |
|---|---|---|
| Character-name spellings | company/brand/copy.md::spellings | brand_designer |
| Playstyle_tag copy | company/roster/players/<id>.md::header | ai_ml_engineer |
| status pill (active/standby/retired) | agent/platform/players.py::_ROSTER | ai_ml_engineer |
| stats numbers (proposals, wins, net_pips, best_pair, ...) | agent/platform/players.py::_stats_for_agent | qa |
| Recent-activity list | agent/platform/players.py::_recent_activity | qa |

## Legal sign-off

F002 IP posture cleared for Sprint 0. Re-audit before any Sprint
6+ paid or public-marketing surface.
