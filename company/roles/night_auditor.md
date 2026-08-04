# Night Auditor

- **Tier:** Operations (reports into QA/DevOps; verdicts reviewed by CEO)
- **Persona:** Ego Jinpachi — the analyst in the control room who
  watches every match tape overnight and delivers the brutal morning
  readout. He never steps on the pitch and never picks the team; he
  tells you what the tape actually says.

## Mission

Read yesterday's tape every morning so a silent day, a feed stall, or
an abstention regression is caught on **day one** — not at the weekly
review. The last three P0s (silent week, crash-loop, lookahead) were
all visible on the tape days before a human read it.

## What this role IS and IS NOT

This is the ONLY role that executes outside Cursor sessions (Tier 1 of
`company/strategy/company-offhours-shifts-proposal.md`): a plain
deterministic Python script (`scripts/night_audit.py`), no LLM, run
daily by Windows Task Scheduler on the VM.

- **IS:** observe-and-draft. Reads `<live_dir>` tape files, writes a
  digest + intake STUBS under `<live_dir>/audits/`, sends one Telegram
  line via the existing `watchdog_alert` ops route.
- **IS NOT:** a decision-maker. No parameter changes, no git, no
  ledger writes, no order powers, no squad-state mutation. Stubs are
  drafts; a human session triages them into real `I###` intakes or
  dismisses them with a note.

## Responsibilities (the nightly check registry)

1. **Tape coverage** — tick_summary rows per symbol vs the weekday H4
   grid (03/07/11/15/19/23 UTC). Zero rows on a weekday = alarm; this
   alone would have caught the silent week on day one.
2. **timestamp_miss regression** — any I024-class abstention narrative
   on the tape = alarm.
3. **Feed health** — `system_status` stale rows = alarm;
   refresh_error streak ≥ 3 = warn (I028 instrumentation).
4. **Activity readout** — proposals/trades/ticks counts (context, not
   alarm; quiet is legal).
5. **State cursor** — where `state.json.last_bar_times` ended the day.

## Division of labour vs the Ops Watchdog (F017)

The 5-minute watchdog answers "is it alive RIGHT NOW?" (process,
heartbeat, freshness) and pages on transitions. The Night Auditor
answers "did yesterday MAKE SENSE?" (coverage, regressions, streaks)
once per day. Neither replaces the other.

## Deliverables

- `<live_dir>/audits/night_audit_YYYYMMDD.md` — the morning digest.
- `<live_dir>/audits/stubs/YYYYMMDD_<check>.md` — one DRAFT stub per
  warn/alarm, for next-session triage.
- One Telegram line/day on the ops chat: "all nominal" or
  "N anomalie(s): …".

## KPIs

| Metric | Target |
|---|---|
| Silent weekdays detected within 24 h | 100 % |
| Pages sent per day | ≤ 1 |
| Mutations performed outside `<live_dir>/audits/` | 0 |
| Stubs triaged (accepted or dismissed) within 2 sessions | 100 % |

## Escalation

The auditor never escalates on its own — its alarm line IS the
escalation. If the digest is missing for 2 consecutive weekdays, that
is itself an anomaly the user or the weekly review must chase (the
task died; see runbook §7b.10 verify steps).
