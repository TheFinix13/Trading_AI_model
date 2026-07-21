# F003 -- user-journey memo

- **Feature:** F003 -- `/research`
- **Author:** UX Researcher
- **Date:** 2026-07-21

## Target segment

The **sceptical prospect** who has just watched the `/v2` pitch
replay and the `/performance` numbers. They now want a third
receipt: how do you *know* your strategy is real, and how do you
know when it isn't?

This is not the general public. This is a person who has already
decided the platform might be interesting and is looking for a
reason to disqualify it. The `/research` page's job is to hand them
that reason if it's there, and to give them the receipt trail if
it isn't.

## Jobs to be done

Above the fold, `/research` must answer:

1. **What do you publish?** Not just the wins — the failures too.
2. **How do I know you didn't cherry-pick?** Because the verdicts
   were pre-registered before the numbers came in, and a
   Benjamini-Hochberg false-discovery-rate correction is applied
   per family.
3. **Show me a failed one.** Any of E022 / E024 / phase_ac_pitch —
   these are the receipts.

The framing name (per the CEO): **anti-marketing marketing**. The
page's value is that it is *not* selling.

## Content order

Per the F003 spec §3, entries render newest-first with a date
header per month. On the mobile card view the date header collapses
to a two-line stack.

Every entry answers:

1. Verdict-kind pill (alive / dead / stopped / fail / pass_thin).
2. Campaign name + date.
3. One-paragraph brand summary (the CPO-manifest override wins;
   otherwise fall back to the REPORT.md abstract).
4. Headline stat block.
5. "Read full report" link (relative path into the sibling
   `finance-research-experiments` checkout on the machine that
   serves the page).

## FDR budget explainer

Below the timeline sits a collapsed `<details>` block with a
plain-English explainer of pre-registration + BH-FDR. The reader
who wants the receipt trail expands it; the reader who trusts the
verdicts scrolls past.

## Non-goals ratified

- **No** live-progress bars for in-flight campaigns.
- **No** search / filter (5-15 entries in Sprint 0; won't scale
  until Sprint 3+).
- **No** subscribe / RSS.
- **No** commenting or editing.
- **No** ability to run a new experiment from this page.

## Accessibility

- Semantic HTML: `<h1>` page title, `<h2>` per date header,
  `<article>` per verdict card.
- Verdict pills use colour + text label (colour-blind users still
  see the label).
- The FDR-explainer `<details>` block is native HTML with
  keyboard-toggle support out of the box.

## Handoff

Ready for UI Designer -> desktop + 375px mock of the timeline +
one verdict card + the FDR explainer state (collapsed +
expanded).
