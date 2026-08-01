---
name: pnl-analytics
description: Full trading performance review from your own fills — FIFO-matched round trips, eight analytical views, a trader persona, an A+ to D- grade, and a self-contained HTML dashboard. Needs API credentials.
requires: credentials
---

# P&L analytics

Turn a fill history into a performance review: what was made, where it came
from, what it cost, and what to fix.

## When to run this

"Show me my P&L analytics", "how am I trading", "trading report", "what's my win
rate", "grade my trading", "where am I losing money", "am I any good at this".

Read this file first. Then load only the references you need:

| File | Read it when |
|---|---|
| `references/algorithm.md` | Always. Data acquisition and FIFO round-trip matching. |
| `references/metrics.md` | Always. The eight views and every formula. |
| `references/persona-grade.md` | For the persona, the grade, what-if scenarios, projections. |
| `assets/dashboard.html` | When producing the dashboard file. |

## Decide how to compute before you fetch anything

Round-trip matching over a real fill history is thousands of stateful
arithmetic steps. Doing that token by token produces numbers that are quietly
wrong, which is worse than refusing. Pick a tier and say which one you used.

**Tier A — you can execute code. Strongly preferred.**

1. `bulk_fills_export(output_path="~/.delta-exchange-mcp/reports/fills.csv",
   start_time_us=<account start>)` writes the full history to disk in one call.
   The export path is restricted to the working directory or home.
2. `list_products(page_size=500)` for the product map, saved as JSON alongside.
3. Write a throwaway script implementing `references/algorithm.md` and
   `references/metrics.md`. Read the CSV header rather than assuming column
   order. Have it print one JSON object.
4. Read that JSON back. Every number you report comes from it.

The fills never enter the conversation. This is the whole point.

**Tier B — no code execution. Fallback.**

Page `get_fills` with `page_size=200`, and after each page fold it into running
aggregates: open position per `product_id`, closed round trips, per-day and
per-symbol totals. Discard the raw page before fetching the next. Never hold the
full fill set at once.

**The guardrail.** Before either tier, call `get_fills(page_size=1)` and read
`meta.total_count` if present, otherwise estimate from the account's first fill.
If the count is above roughly 500 and Tier A is unavailable, stop and say so:

> You have about N fills. Without code execution I can only aggregate those
> approximately. I can either analyse a narrower window accurately — say the
> last 90 days — or you can run this where I can execute a script.

Offer the narrower window. Do not silently produce a number you cannot stand
behind.

## The 90-day trap

`get_fills` and `bulk_fills_export` return only the last ~90 days when
`start_time_us` is omitted, and the result carries a `notice` field saying so.
A "lifetime P&L" built on that default is wrong and looks right. Always pass
`start_time_us`. If the user does not name a period, ask whether they mean all
time or a window, and state the window you used in the output.

## Output

Two artefacts, in this order.

**1. The dashboard.** Load `assets/dashboard.html`, replace the contents of the
`<script id="pnl-data" type="application/json">` island with your computed JSON,
and write the file to `~/.delta-exchange-mcp/reports/pnl-<YYYY-MM-DD>.html`.
The template's own comments give the exact JSON shape. It is one file with no
network requests, so it opens offline. Tell the user the path and offer to open
it.

**2. Six lines in chat.** Not a transcript of the dashboard.

- Grade and persona.
- Net P&L, win rate, and the period covered.
- The largest single leak, quantified.
- One concrete change, with the number it would have been worth.
- Which compute tier you used, and any window limit that applied.

Expand only when asked.

## Honesty rules

- Round trips come from matched fills. A position still open contributes
  unrealized P&L only, kept separate from realized. Never add the two into one
  headline without labelling it.
- Funding is a real cost and lives in `get_wallet_transactions`, not in fills.
  A perps trader's fills-only P&L can be positive while the account shrank.
- If a metric needs more history than exists — Sharpe on four days of data —
  print `n/a` and say why. Do not annualise noise.
- State the window and the fill count on every report.

## Boundaries

This skill reads history and describes it. It does not place orders, and past
performance here is a record, not a forecast. The projection figures in
`references/persona-grade.md` are arithmetic extrapolations for illustration;
label them as such and never present them as expected returns.
