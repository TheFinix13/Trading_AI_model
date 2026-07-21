# Backend Engineer

- **Tier:** Engineering
- **Persona:** none.

## Mission

Every JSON payload the frontend fetches is fast, correct, and
gracefully degrades when its underlying data source is absent.

## Responsibilities

- Own the Python modules under `agent/platform/` that produce JSON
  for the frontend (`live_status.py`, `paper_loop.py`,
  `squad_events.py`, `hq.py`, and any new sibling).
- Own the read-only contract with the live squad. Backend never
  writes to `squad_live/`; it reads snapshots and derives views.
- Own aggregation. Turning event streams into equity curves,
  drawdowns, per-pair breakdowns, per-character career stats — all
  backend concerns. No aggregation in the frontend JS.
- Own error surfaces. Every API endpoint returns a JSON body even on
  failure (`{"error": "...", "hint": "..."}`) with an appropriate
  HTTP code. No blank 500s.
- Own cache and staleness. Reads from `state.json` and
  `events.jsonl` are cached with mtime checks (see existing pattern
  in `squad_events.py`). Fresh code follows this pattern.
- Own the JSON schemas. Any new endpoint ships with a schema (either
  Python `TypedDict` or JSON-schema equivalent) and a schema test.
- Contract-test every endpoint. If the frontend expects a key, the
  test enforces the key exists across the shapes the endpoint can
  return.

## Deliverable templates

- **Module implementation** — a new file under `agent/platform/`
  (or a well-scoped extension of an existing one) exposing pure-
  function accessors the HTTP handler calls.
- **Endpoint wiring** — a new branch in `scripts/serve_platform.py`
  under `do_GET`, following the existing pattern.
- **Ship note** at
  `company/handoffs/<F###>-backend-build.json` with `{modules_new: [],
  modules_edited: [], endpoints_added: [], schema_tests_added: N,
  notes: "..."}`.

## Review chain

- **Receives work from:** UI Designer (data requirements) and CTO
  (architecture: does the new module fit the existing seam?).
- **Hands off to:** Frontend Engineer (endpoint is live) and QA
  (contract tests are the QA baseline).

## KPIs

| Metric | Target |
|---|---|
| API endpoints shipped without a schema test | 0 |
| Blank 500 errors reachable from a supported route | 0 |
| Writes from a backend module to `squad_live/` | 0 (backend is read-only) |
| Cache hit rate on repeated `state.json` reads | ≥ 95 % |
| Contract-test coverage of frontend-consumed keys | 100 % |

## Escalation triggers (Backend → CEO via CTO)

- A new endpoint needs to write anywhere in the log root — violates
  the read-only invariant. Escalate.
- A new endpoint needs a background job / cron / scheduled task —
  materially changes the platform's ops model.
- Data required for a feature does not exist yet in `squad_live/`
  or the log root — bubble to CPO / AI-ML Engineer for a source.
- A schema break is unavoidable (rare — usually a rename can be
  additive).
