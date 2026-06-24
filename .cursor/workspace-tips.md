# Workspace Tips — multi-pair-trading-agent

> Recommended Cursor / VS Code multi-root setup for working across
> production code (this repo), research (`finance-research-experiments`),
> and the canonical state layer (`brain-box`).

## Why a multi-root workspace?

This project's research lives in `finance-research-experiments`
(specifically `programs/M001_multi_agent_ensemble` on the
`multi-agent-ensemble` branch). Production code lives here. The Brain
Box at `/Users/the1finix/Documents/GitHub/brain-box/` is the canonical
state-tracking layer across all three. Having all three open in one
workspace lets you:

- Cross-reference doctrine (research repo) with production code (this
  repo) without window-switching.
- Update the Brain Box session log inline when work lands.
- Search across all three with one `⌘ ⇧ F`.
- Read the doctrine while writing the agent that implements it.

## Recommended roots (in this order)

1. `/Users/the1finix/Documents/GitHub/multi-pair-trading-agent`
2. `/Users/the1finix/Documents/GitHub/finance-research-experiments`
3. `/Users/the1finix/Documents/GitHub/brain-box`

**The ordering matters.** Cursor's chat agent uses the first root as
the default working directory. Putting this repo first means
production-code edits remain the default; the agent will use absolute
paths for the other two roots, which is what we want.

## How to add a root

Cursor / VS Code:

1. File → Add Folder to Workspace → pick the folder.
2. Repeat for each root.
3. File → Save Workspace As →
   `~/cursor-workspaces/finance-multi-pair.code-workspace`.
4. Next session: open the `.code-workspace` file and all three roots
   come back.

## Conventions across the three repos

| Where | What lives there | What does NOT live there |
|---|---|---|
| `multi-pair-trading-agent` (this repo) | Production code (`agent/`, `scripts/`, `tests/`), live broker / monitor / state, validation scripts, `ai_context.md` | Research drafts, exploratory notebooks, doctrine docs |
| `finance-research-experiments` (research) | Doctrine, literature surveys, hypothesis tests, simulator prototypes, M001 program docs, all sub-experiment branches | Production code, broker config, anything that runs against the live broker |
| `brain-box` (state layer) | Cross-workspace index, session logs, agent registry, separation rules, journey docs | Code, doctrine drafts (those are pointers from brain-box, not content) |

## Useful cross-repo shell snippets

From this repo's root:

```bash
# Combined git status across the two code repos
( cd /Users/the1finix/Documents/GitHub/multi-pair-trading-agent && \
  git status -s && echo "--- finance-research-experiments ---" && \
  cd /Users/the1finix/Documents/GitHub/finance-research-experiments && \
  git status -s )

# What branch am I on in the research repo?
( cd /Users/the1finix/Documents/GitHub/finance-research-experiments && \
  git branch --show-current )

# List all M001 sub-experiment branches (active + archived)
( cd /Users/the1finix/Documents/GitHub/finance-research-experiments && \
  git branch -a | rg 'multi-agent-ensemble|archive/m001' )
```

## Branching convention reminder (research repo only)

Set in `finance-research-experiments/README.md` after the
2026-06-24 audit. Recap:

- `main` = sealed/completed work only.
- Long-lived program branches (e.g. `multi-agent-ensemble`) for
  multi-phase research programs.
- Short-lived sub-experiment branches off the program branch.
- **Branches are never force-deleted.** On completion, they are
  renamed `archive/<original>` and tagged `<id>-final-<date>`.
- Abandoned experiments are also archived, not deleted — the
  abandonment is itself a finding.

This repo (`multi-pair-trading-agent`) follows standard git-flow
because it's production: feature branches off `main`, merge via PR,
short branches deleted on merge after tag. Long-lived branch
**`m001-development`** holds the pre-M001 production baseline; M001
code graduates here at Φ6.

## Brain Box session-end ritual

Before closing a meaningful session, append a one-line entry to
`brain-box/life/finance-research/multi-pair-trading-agent.md`:

```
## Session log
- YYYY-MM-DD — <one-line summary of what was decided / shipped>
```

Bump `last_updated:` in front-matter. See
`.cursor/rules/use-brain-box.mdc` (in this repo) for the full ritual.

## When you don't want all three open

For pure production-code work (e.g., chasing a bug in
`agent/live/monitor.py`), single-root on this repo is fine. The
agent can still reach the other two by absolute path if needed, just
less conveniently — and search results across roots disappear.

## Single-root fallback workspace

If you prefer keeping single-root the default and toggling
multi-root only for cross-cutting sessions, save TWO workspace
files:

- `finance-multi-pair-prod.code-workspace` — this repo only.
- `finance-multi-pair-research.code-workspace` — all three roots.

Open whichever matches the session.
