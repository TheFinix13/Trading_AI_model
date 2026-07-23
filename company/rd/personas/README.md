# Test personas & test customers

Dogfood cast for the Blue Lock platform (D092). The CEO asked for
"test personas/users along myself who test different parts of the
system... while we're at it, also create test customers." This
directory is the canonical roster; `scripts/dogfood_personas.py` reads
it and drives a real (locally-started, fully isolated) platform server
through each persona's journeys.

## Rules

- **Every credential in this directory is fake.** Fake logins, fake
  passwords, fake billing profiles. Nothing here may ever hold a real
  secret; the claim-register / invariant rules for the repo apply.
- **No live mode.** No persona journey may call
  `/api/live-mode/enable` with valid ceremony args. The dogfood script
  enforces this (it has no journey step for it), and the personas'
  docs must not describe one.
- Personas are markdown files with YAML front-matter:
  `id` (P001+), `name`, `archetype`, `goals` (list),
  `risk_tolerance` (`none` | `low` | `medium` | `high`),
  `devices` (list), `tests` (list of test surfaces — see mapping
  below). Test customers additionally carry a `fake_profile` block
  (billing-ready shape, obviously fake values).

## Surface mapping (persona `tests:` value → what gets exercised)

| `tests:` key  | Surface exercised by the dogfood script |
|---------------|------------------------------------------|
| `onboarding`  | `/api/onboarding/state` → passphrase → pairs → complete round-trip |
| `broker`      | `/api/broker/test-connection` failure paths: validation reject, MT5-unavailable copy, 5/60s rate limit |
| `kill_switch` | `/api/kill-switches/activate` → status → clear round-trip (GLOBAL) |
| `approvals`   | `/api/approvals/submit` (internal-token seam) → list → approve; second submit → reject. Plus the fail-closed no-token check |
| `alerts`      | `POST /api/alerts/test` → `/api/alerts/recent` shows the synthetic event |
| `research`    | `/research` page + `/api/research/verdicts` (claim provenance) |
| `hq_org`      | `/hq` page + `/api/hq/org` (F015 Org & Flow) |
| `pages`       | Plain GET smoke over the HTML routes the persona would visit |

## Roster

| id   | name             | archetype                          | primary surfaces |
|------|------------------|------------------------------------|------------------|
| P001 | Fiyin            | CEO / dogfood owner                | everything |
| P002 | Ada Nwosu        | cautious first-time retail trader  | onboarding, kill_switch, pages (mobile) |
| P003 | Marcus Bell      | power user / quant hobbyist        | approvals, alerts, broker |
| P004 | Dr. Elin Sorhaug | skeptical auditor                  | research, hq_org |
| P005 | Tunde Bakare     | non-technical customer             | onboarding, pages |
| P006 | Amaka + Chidi Eze| test customer pair (fake billing)  | onboarding, broker, kill_switch |

Reports land under `reports/dogfood/` (gitignored; path configurable
via `--out`). A committed sample lives at
`sample-dogfood-report.md` in this directory.
