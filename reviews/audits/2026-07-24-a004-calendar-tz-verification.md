# A004 verification — calendar vs broker timezone (CLOSED, no fix needed)

Date: 2026-07-24 · Verifier: engineering · Audit finding: A004 (P1, I007)

## The question

The audit flagged that ForexFactory calendar timestamps had never been
verified against the broker's server timezone. Two independent
assumptions were unproven:

1. `agent/news/calendar.py::_parse_event_time` tags feed times as UTC
   ("FF feed timestamps are GMT"). If the feed actually published
   US-Eastern times, every news window would guard the wrong hour
   (4–5 h off), including NFP.
2. `agent/live/broker.py` converts MT5 bar epochs with
   `datetime.fromtimestamp(..., tz=timezone.utc)`. MT5 rate times are
   server-clock epochs, so this is only correct when the broker's
   server runs UTC+0.

## Evidence

**Feed side — verified against the live weekly feed (fetched
2026-07-24 14:30 UTC from `nfs.faireconomy.media/ff_calendar_thisweek.xml`):**

| Anchor event | Known schedule | = UTC (July, EDT) | Feed row |
|---|---|---|---|
| US Unemployment Claims (07-23) | 08:30 US-Eastern, every Thursday | 12:30 UTC | `12:30pm` |
| US Flash Manufacturing PMI (07-24) | 09:45 US-Eastern | 13:45 UTC | `1:45pm` |

Both anchors land exactly on their known UTC times → **the feed
publishes GMT/UTC. The parser's assumption is correct.** Had the feed
been US-Eastern, the Claims row would have read `8:30am`.

**Broker side — verified on the VM the same day:**

- The Exness Trial MT5 terminal's Market Watch clock read `13:28:36`
  when actual UTC was 13:28 (screenshot, 2026-07-24) → server clock =
  UTC+0.
- Both dashboards independently derive H4 closes on the
  00/04/08/12/16/20 **UTC** grid from raw MT5 bar times ("next H4
  close ~16:00 UTC"), which only happens when server epochs are
  UTC-aligned. An EET (UTC+3) server would put closes at 01/05/09/13/17/21.

→ **`fromtimestamp(..., tz=timezone.utc)` is correct for this broker.**

## Verdict

No code change required. Both conversion paths are right, and the
whole pipeline (feed event `time_utc` ↔ bar `time`) compares like with
like in UTC.

## Pinned + residual risk

- `tests/test_news_calendar_tz_anchors.py` pins the two anchor rows so
  a parser regression that shifts event times off their known UTC
  schedule fails loudly.
- Residual risk (accepted, documented): the broker-side conclusion is
  Exness-specific. A different broker on EET server time would need
  the epoch shift handled. If the platform ever onboards a second
  broker vendor, add a server-clock skew check at connect (compare the
  latest closed bar's time against wall-clock UTC modulo the bar
  period) before trusting news windows. Filed as a note here rather
  than an intake item — it has no live trigger today.
