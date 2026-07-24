---
id: I014
source: ceo
submitter: user_advocate
submitted_at: 2026-07-24T13:22:00Z
classification: BUG
priority: P1
status: resolved
route: engineering
linked_features: ["F006", "F008"]
linked_decisions: ["D125"]
linked_experiments: []
contact: internal (CEO hit it live during the 2026-07-24 VM cutover)
resolved_at: 2026-07-24T15:40:00Z
history:
  - stage: filed
    at: 2026-07-24T13:30:00Z
    by: user_advocate
    note: "Filed from the CEO's first-run on the VM. Workaround in use: append ?token= to every URL manually."
  - stage: resolved
    at: 2026-07-24T15:40:00Z
    by: engineering
    note: "Fixed same day (D125). Root cause was in the F008 first-visit 302 itself: it dropped the query string AND bypassed _send, so the session cookie planted by _authorized was never emitted. Fix: Location preserves ?token= and the 302 flushes Set-Cookie. Security contract pinned in tests/security/test_i014_first_run_auth.py (5 cases incl. wrong-token-gets-no-cookie and cookie-alone-reaches-onboarding)."
---

# I014 — First-run auth UX: the /onboarding redirect drops ?token= and the auth cookie doesn't persist across HTML hops

## What happened

During the 2026-07-24 VM cutover (fresh install, `--auth-token` set,
F008 onboarding gate on), the CEO opened `/v2?token=…` and was
redirected to `/onboarding` — which then returned
`{"error": "unauthorized — pass ?token= or Authorization: Bearer"}`.
The redirect did not carry the token, and the cookie the first
authorized request should have set did not cover the hop. Every page
401s until the user manually re-appends `?token=` — on the very first
screen a paying customer would ever see.

## Expected

1. The F008 onboarding redirect preserves the presented `?token=`
   query parameter (or relies on a cookie guaranteed to already be
   set).
2. The first authorized request — HTML or API — sets the auth cookie
   so subsequent navigation inside the same browser needs no query
   parameter.

## Notes for the fix session

- Surface area: `scripts/serve_platform.py` (legacy `--auth-token`
  gate + F008 redirect path) and the F006 cookie-set logic.
- Security review fires (auth-adjacent); the fix must not weaken the
  gate (no token echo in Location headers beyond what the client
  already presented, no cookie on unauthorized responses).
- Test shape: redirect-preserves-token pin + cookie-set-on-first-HTML
  pin; dogfood persona P002 first-run journey should pass without
  manual query-string surgery.
