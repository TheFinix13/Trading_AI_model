# .sessions/ — live session claims

One claim file per active Cursor session that intends to WRITE to this
repo (including sessions anchored in another workspace). Claim files are
gitignored; only this README is tracked.

Full protocol and format:
`/Users/the1finix/Documents/GitHub/brain-box/agents/concurrent-session-safety.md` (§1–§2).

Quick reference — filename `<YYYY-MM-DD>_<topic-slug>.md`:

```markdown
- started: 2026-07-14T12:05Z
- anchor: <workspace the chat is anchored in>
- topic: <one line>
- scope:
  - <files/dirs this session expects to write>
  - ai_context.md (append-only)
- status: active            # flip to "done — <outcome>" or delete at session end
```

Rules of thumb: write your claim before your first edit; narrower scope
wins contested paths; same-file conflicts go to the user; `active` claims
older than 24 h are presumed abandoned.
