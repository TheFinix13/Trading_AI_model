# F013 — Design mocks: `/approvals` + `/settings/live-mode`

## `/approvals`

Two stacked sections. Cards render newest-first inside a
`grid-template-columns: 1fr 1fr` grid on desktop, `1fr` at
`max-width: 700px`.

```
+------------------------------------------+
| Approval-queue warning (verbatim Legal)  |
| ~120px scroll box, dim border            |
+------------------------------------------+
| Pending (2)                              |
+------------------+-----------------------+
| EURUSD           | GBPUSD                |
| side / size ...  | side / size ...       |
| rationale        | rationale             |
| timeout in 04:47 | timeout in 04:12      |
| [Approve][Reject]| [Approve][Reject]     |
| [reason textarea]| [reason textarea]     |
+------------------+-----------------------+
| Recent                                    |
+------------------+-----------------------+
| USDCAD [approved]| USDJPY [rejected]     |
| ...              | ...                   |
+------------------+-----------------------+
```

## `/settings/live-mode`

Single-column with three "sections", only one visible at a time
based on the current state.

**OFF state (default):**

```
+---------------------------------------+
| Live mode                             |
| Small dim intro paragraph             |
|                                       |
| [OFF -- no live orders will be sent]  |
|                                       |
| Enable live mode                      |
| +--- verbatim warning ---+            |
| |  (scrolls at 360px)    |            |
| +------------------------+            |
| [ ] I understand ...                  |
| Type: [ENABLE LIVE MODE           ]   |
| [Enable]  [Cancel]                    |
+---------------------------------------+
```

**ON state:**

```
+---------------------------------------+
| Live mode                             |
| [ON -- live orders are authorised]    |
|                                       |
| Small dim paragraph pointing to       |
| /approvals + kill-switches + /risk    |
|                                       |
| [Turn off live mode]                  |
+---------------------------------------+
```

## Colour semantics

- Red `#a94a4a` background on the ON state indicator + Enable button
  (the same red is used for the Reject button on `/approvals`). The
  colour signals "danger, real money at risk".
- Dim / muted panel for the OFF state -- boring on purpose.
- Green `#2a7f4a` for Approve -- affirmation, not danger. Deliberate
  asymmetry: green means "yes, use the queue as designed", red
  means "no, or stop".

## Copy strings (for `company/brand/copy.md`)

- **Live-mode OFF pill:** "OFF -- no live orders will be sent"
- **Live-mode ON pill:** "ON -- live orders are authorised"
- **Approvals pending section header:** "Pending"
- **Approvals recent section header:** "Recent (approved / rejected / timed out)"
- **Empty pending:** "No proposals waiting." (via F005 empty-state)
- **Empty recent:** "Nothing resolved yet."
- **Sprint 2 caveat:** "Sprint 2 caveat: the platform ships the
  approval queue and the 4-check pathway, but no live pathway in
  this sprint feeds proposals into `submit()`. Live-mode default
  OFF at /settings/live-mode."
