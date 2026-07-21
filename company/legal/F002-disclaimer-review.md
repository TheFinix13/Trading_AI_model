# F002 -- Legal disclaimer review

- **Feature:** F002 -- `/players` + `/players/:id`
- **Reviewer:** Legal
- **Verdict:** `pass`
- **Date:** 2026-07-21

## What was reviewed

- Ten user-visible bio pages (`/players/isagi` .. `/players/kunigami`)
  plus the index page `/players` and the 404 shell.
- Copy in `company/roster/players/*.md` (10 files).
- IP posture memo `company/legal/blue-lock-ip-notice.md`.

## Verdict

`pass` -- the IP disclaimer text matches the canonical library entry
verbatim on every user-facing surface. Character-name spellings on
each bio page match the spellings register in
`company/brand/copy.md`. No content on any bio page reproduces
manga panels, character art, or copyrighted assets.

## Specific checks

| Requirement | Verdict |
|---|---|
| IP disclaimer verbatim on `/players` index. | ✅ |
| IP disclaimer verbatim on every `/players/:id`. | ✅ (10/10) |
| IP disclaimer on the 404 shell. | ✅ (via nav / footer -- the 404 shell doesn't render the disclaimer inline but does not carry any Blue Lock name either; approved as low-risk). |
| Character-name spellings from `copy.md`. | ✅ |
| No copyrighted imagery from the manga / anime. | ✅ (ASCII diagrams only). |
| Fallback naming plan documented. | ✅ (`company/legal/blue-lock-ip-notice.md` section "Fallback: generic naming plan"). |
| No commercial framing on any bio page. | ✅ |
| No user testimonials. | ✅ (there are none). |

## Claim register update (F002)

Added to `company/legal/disclaimers.md`:

- Character-name spellings -- verified against
  `company/brand/copy.md::spellings`.
- Playstyle-tag copy -- verified against
  `company/roster/players/<id>.md::header`.
- Status pill (active / standby / retired) -- traces to
  `agent/platform/players.py::_ROSTER`.
- Stats numbers -- traces to
  `agent/platform/players.py::_stats_for_agent`.

## Sign-off

F002 IP posture cleared for Sprint 0. Re-audit before any Sprint
6+ paid or public-marketing surface.
