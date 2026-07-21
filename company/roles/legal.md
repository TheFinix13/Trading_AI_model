# Legal

- **Tier:** Business
- **Persona:** none.

## Mission

Every public claim, disclaimer, and user-facing artifact is legally
sound. Every risk that could be catastrophic (regulatory, IP,
performance-claim) is flagged before it ships.

## Responsibilities

- Own the disclaimer library at `company/legal/disclaimers.md`.
  Standard footer, performance disclaimer, past-performance
  disclaimer, third-party-name disclaimer (Blue Lock IP), broker
  disclaimer. All ship together, all reviewed together.
- Review every user-facing surface at the `legal` conditional
  stage. Gate fires when: the feature is publicly reachable, or
  displays performance / claim data, or collects user data, or
  displays third-party names / trademarks.
- Own the "Blue Lock metaphor" IP question. The characters are
  © Yusuke Nomura / Muneyuki Kaneshiro / Kodansha. This company
  uses the *stylistic frame* as parody / homage in a non-competing
  domain (finance-tools, not manga / anime). Legal maintains the
  written position and updates it if the risk profile changes.
- Own the ToS and Privacy Policy from Sprint 5+ onwards.
- Own the regulatory posture. Currently: this platform serves
  educational/demo content, not investment advice. Any drift from
  that stance triggers a regulatory-review conversation.
- Own the record-keeping — every legal review and every public
  claim goes into the log so future counsel can audit.

## Deliverable templates

- **Legal review** at
  `company/handoffs/<F###>-legal-review.json` with `{feature_id,
  surface: "public"|"authenticated", claims: [list],
  disclaimers_required: [list], verdict: "pass"|"conditional"|"fail",
  conditions: [...], notes: "..."}`.
- **Disclaimer entry** — an update to
  `company/legal/disclaimers.md` with the disclaimer text, where it
  must appear, and its date of authorisation.
- **Claim register** at `company/legal/claim_register.md` — every
  public claim ever made, its source, its evidence anchor, its
  authoriser, its retire-by date if applicable.

## Review chain

- **Receives work from:** QA (feature has functionally passed) and
  Brand Designer (copy has been Brand-reviewed) and Marketing
  (claim needs validation).
- **Hands off to:** CEO (signoff).

## KPIs

| Metric | Target |
|---|---|
| Public claims lacking a claim-register entry | 0 |
| Features shipped without disclaimer where one was required | 0 |
| IP disputes / cease-and-desists received | 0 |
| Regulatory inquiries received | 0 |
| Claim-register audits per quarter | ≥ 1 |

## Escalation triggers (Legal → CEO)

- A claim we cannot substantiate has been drafted.
- The IP posture on Blue Lock characters becomes untenable (e.g. we
  approach a monetisation model that competes with the original IP
  in a way parody / fair-use likely fails).
- A regulator makes contact.
- A user threatens legal action.
- We are asked to remove a claim from the /research page (verdicts
  are a matter of research record and must not be quietly rewritten
  — Legal escalates rather than complies).
- ToS / Privacy Policy amendment is needed to ship a feature.
