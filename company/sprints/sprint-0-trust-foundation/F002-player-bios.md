# F002 — `/players/:id` character bio routes

- **Priority:** P0
- **Sprint:** Sprint 0 · Trust Foundation
- **Owner (build):** Frontend + Backend (with AI/ML Engineer for stats)
- **Reviewers:** UX Researcher, UI Designer, Brand Designer, AI/ML,
  CTO, QA, Legal, CEO
- **Current stage:** `spec`
- **Written by:** CPO

## User story

> As a **prospect who's just landed on the /v2 pitch page**, I want
> to click a character (Isagi, Bachira, Rin, Chigiri, Reo, Nagi,
> Barou, Karasu, Sae, Kunigami) and go to a page that tells me who
> they are, what they trade like, and how they've performed, so I
> understand the platform is a *team of specialists* not a black
> box.

Corollary:

> As a **casual reader** who found this through search
> ("blue lock trading isagi"), I want the bio page to make sense
> on its own without knowing what the platform is.

## Acceptance criteria

The feature is done when:

1. `GET /players/:id` returns 200 for each of the ten striker IDs:
   `isagi, bachira, rin, chigiri, reo, nagi, barou, karasu, sae,
   kunigami`. Also accepts case-insensitively and slug variants
   (`isagi-v1`, `isagi/`, `Isagi`).
2. `GET /players/unknown` returns 404 with a friendly page that
   lists the ten valid striker names as links.
3. `GET /players` (index) returns 200 and shows the ten strikers as
   a grid — same visual style as the `/v2` player-detail hover
   card, but as a full page.
4. Each bio page shows, in order:
   - **Header**: character name, playstyle tag (e.g.
     "metavision baseline finisher"), status pill
     (`active`/`standby`/`retired`), signature-setup blurb.
   - **Stats panel**: proposals (all-time), wins, win-rate,
     best pair (by net pips), best-ever single trade, worst-ever
     single trade, avg pip per trade, days-active.
   - **Playstyle section**: 2–4 paragraphs of Brand-written prose
     explaining how the character makes decisions in stranger-
     friendly language. Zero uses of "ensemble" or "aggregator".
   - **Signature setup**: a small SVG diagram (or ASCII in
     v1-of-the-page if SVG blocks) showing the archetypal setup
     this character trades.
   - **Evolution history**: bullet list of versions and dates
     (`v1.0 landed 2026-06-24 · v1.2 rebel-tight stop 2026-07-06 ·
     v1 retired 2026-07-06 (Kunigami)` etc.).
   - **Recent activity**: last 5 proposals or trades from
     `squad_live/events.jsonl`, filtered to this character.
5. Data source: Backend Engineer produces
   `agent/platform/players.py::get_player(id)` which reads:
   - Static bio content from
     `company/roster/players/<striker>.md` (authored by AI/ML
     Engineer + Brand Designer).
   - Live stats from `squad_live/events.jsonl` (same events reader
     as `/v2`).
   - Version history from `company/roster/players/<striker>.md`'s
     "Evolution history" section.
6. Backend `GET /api/players/:id` returns JSON `{id, name,
   playstyle, status, signature_blurb, stats: {...}, playstyle_prose:
   "...", evolution: [{version, date, note}], recent_activity: [...]}`.
7. Mobile responsive (F004 coordination): 375 px viewport works —
   stats panel becomes 2-column grid, evolution history stacks.
8. Loading + error state (F005): both wired.
9. Every bio page includes a footer disclaimer clarifying:
   "Blue Lock is a manga / anime by Yusuke Nomura and Muneyuki
   Kaneshiro, published by Kodansha. Characters here are named as
   homage to describe our AI agents' trading playstyles; no
   affiliation or endorsement is claimed." — text approved by Legal.
10. Test coverage:
    - `tests/platform/test_players_page.py` — GET /players/:id
      for each of the ten IDs returns 200 with expected structural
      markers.
    - `tests/platform/test_players_api.py` — `/api/players/:id`
      contract test.
    - `tests/platform/test_players_module.py` — unit tests for
      `players.get_player(id)`.

## Non-goals

- **No** editable bio content (users can't add notes).
- **No** per-character P&L attribution chart. Text stats only.
- **No** character comparison view (Bachira vs Isagi side-by-side).
  Sprint 3 concern.
- **No** commentary generation ("today Bachira felt aggressive").
  Sprint 4 "match highlights" concern.
- **No** search / filter across characters. Ten characters — links
  from the index page suffice.
- **No** localisation (English only). Sprint 5+ concern.

## Dependencies

- **AI/ML Engineer** authors `company/roster/players/*.md` for the
  ten characters (10 files, ~50 lines each). This is the canonical
  bio source and doubles as internal documentation.
- **Brand Designer** copy-reviews all ten bios; ensures playstyle
  prose is stranger-friendly.
- **Backend Engineer** writes `agent/platform/players.py` and the
  `/api/players/*` endpoints.
- **Frontend Engineer** writes `PLAYERS_INDEX_PAGE` and
  `PLAYER_DETAIL_PAGE` (or a single `PLAYERS_PAGE` with routing
  via query string — decided at UI Design stage).
- **Legal** authors the IP disclaimer footer.
- **UI Designer** mocks bio-page (desktop + mobile) and index.

## Review checklist

Analogous to F001. Special items:

| Reviewer | Additional check |
|---|---|
| AI/ML Engineer | Bio playstyle accurately describes striker's *actual* behaviour in `squad_live/`. Coaching notes from the last 30 days are reflected. |
| Brand Designer | Each bio passes the "stranger-friend test" — a reader who's never seen this platform can, after reading one bio, describe the character's playstyle. |
| Legal | IP disclaimer language matches `disclaimers.md`'s `third-party-name-usage` entry; character names' commercial-use posture recorded in `claim_register.md`. |
| UX Researcher | Non-goals ratified — no adjacent user need silently pulled in. |

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| IP disclaimer wording insufficient / Kodansha C&D risk. | Legal escalates immediately if IP posture becomes untenable; Brand ready with generic-fallback naming (Striker 1, Striker 2) if CEO decides to pivot away from the metaphor commercially. |
| Some characters have almost no data (Sae disabled by default, Kunigami retired). | "No recent activity" placeholder shows the reason (disabled / retired) prominently; the bio page is still useful as a historical document. |
| AI/ML Engineer can't write ten bios by design phase. | CPO cuts scope: launch with the 7 originally-shipped strikers (Isagi–Barou); Karasu / Sae / Kunigami land in a Sprint 0.5 follow-up. |

## Definition of shipped

Ten routes reachable, index reachable, tests green, disclaimer in
place, at least three bios have been "stranger-friend tested" (CEO
shares with a non-technical person, they can describe the character
after reading).
