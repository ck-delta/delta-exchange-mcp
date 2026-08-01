# The eight views

Every formula below runs on the round trips produced by `algorithm.md`, plus the
funding transactions, open positions and balances. Round money to 2 decimals,
percentages to 1, fee ratios to 4.

Throughout: `winners` are round trips with `net_pnl > 0`, `losers` with
`net_pnl < 0`, and breakeven exactly 0. Breakeven trades count in the
denominator of the win rate.

## 1. Overview

```
net_pnl        = sum(net_pnl)
gross_pnl      = sum(pnl)
total_fees     = sum(fees)
win_rate       = len(winners) / len(trades) * 100
avg_winner     = mean(net_pnl of winners)
avg_loser      = mean(net_pnl of losers)          # negative
win_loss_ratio = abs(avg_winner / avg_loser)
best_trade     = max(net_pnl)
worst_trade    = min(net_pnl)
```

Split `net_pnl` by `direction` (long vs short) and by `instrument_type`
(perpetual vs call + put). Report `unrealized_pnl` as the sum of
`unrealized_pnl` over `get_margined_positions`, always as its own line.

**Equity curve**: sort by `exit_time`, accumulate `net_pnl`. Keep the last 500
points for plotting; compute on all of them.

**Distributions**: 20-bin histograms of `net_pnl` and of non-zero `pnl_pct`.
Bin width is `(max - min) / 20`; the last bin is inclusive at both ends. Drop
empty bins. When min equals max, emit one bin.

## 2. P&L analysis

Group round trips by `exit_time`:

- **Daily** — `exit_time[:10]`. Sum `net_pnl`, count trades.
- **Hourly** — `exit_time[11:13]` as an integer, all 24 buckets present even
  when empty. Report average P&L per trade and win rate, not the total: totals
  just track where the volume was.
- **Day of week** — order Monday first, Sunday last.
- **Monthly** — `exit_time[:7]`. Trades, gross, fees, net, win rate, best,
  worst.

**By underlying**: trades, `net_pnl`, win rate, capital deployed
(`sum(notional_value)`), and `avg_return = pnl / capital * 100`. Sort by
`abs(net_pnl)` descending.

**Top contributors** are the five most positive; **top detractors** the five
most negative. The **waterfall** is the top 20 by absolute P&L with a running
cumulative.

## 3. Instruments

Counts and `net_pnl` for perpetuals, calls, puts, and options combined. Capital
versus return per underlying, as a scatter of `(capital, avg_return)`. Long
versus short split for the top 15 underlyings.

**Correlation matrix**: build a per-token daily P&L series. Keep tokens with at
least 5 days of data, cap at 10 tokens. Pearson over the union of all trading
dates, treating a missing date as 0. Fewer than 3 shared observations returns 0.

This is a correlation of daily P&L, not of price. Say so — it measures whether
positions won and lost together, which is the useful question.

## 4. Funding

Funding comes from `get_wallet_transactions(transaction_types=["funding"])`, not
from fills.

```
total_funding = sum(float(tx.amount))
```

The sign is from the account's side: negative is paid, positive is received.
Group by the product's underlying, by day, and cumulatively. Split into
`funding_paid` (amount < 0) and `funding_received` (amount > 0). Build a monthly
table of trading P&L beside funding P&L, over the union of both sets of months.

For a perps trader this view often carries the answer. Trading P&L can be
positive while funding drains the account.

## 5. Expiry (options only)

Skip the view when there are no option round trips.

Parse the expiry from the last dash-separated part of `product_symbol`
(`C-ETH-2340-160426` → `160426`, read as `DDMMYY` → `2026-04-16`).

```
dte = max(0, floor((expiry_date - entry_time) / 1 day))
```

| DTE at entry | Expiry type | DTE bucket |
|---|---|---|
| 0–1 | Daily | `0-day` when exactly 0, else `1-3 days` |
| 2–7 | Weekly | `1-3 days` or `4-7 days` |
| 8–31 | Monthly | `7+ days` |
| 32+ | Quarterly+ | `7+ days` |

Report P&L, count and win rate by expiry type; P&L and count by DTE bucket and
by expiry date.

## 6. Risk

Daily returns are the daily `net_pnl` series, in currency, not percent.

```
mean      = mean(daily)
std       = sample stdev(daily)                    # n-1, needs >= 2 days
sharpe    = mean / std * sqrt(365)                 # 0 when std == 0
downside  = sqrt(sum(r^2 for r in daily if r < 0) / count(r < 0))
sortino   = mean / downside * sqrt(365)            # 0 when downside == 0

profit_factor = sum(winners) / abs(sum(losers))    # 999 if no losers and profitable, else 0
payoff_ratio  = abs(avg_winner / avg_loser)
expectancy    = win_rate/100 * avg_winner + (1 - win_rate/100) * avg_loser
```

**Max drawdown** runs on the cumulative daily curve:

```
peak = max(peak, cumulative)
dd   = (cumulative - peak) / peak * 100     # only while peak > 0
max_drawdown = min(dd)                      # negative
```

That percentage is relative to peak cumulative P&L, not to account equity. When
the curve starts negative, `peak` stays 0 and drawdown reads 0 — say `n/a`
rather than "no drawdown".

```
calmar / recovery_factor = net_pnl / abs(max_drawdown)
```

**Streaks** are computed on days, not trades: consecutive profitable days and
consecutive losing days, current and best.

Sharpe and Sortino on fewer than about 30 daily observations are noise. Print
the value with the observation count, or `n/a` under 7 days.

## 7. Charges

```
fees_pct_pnl    = total_fees / abs(gross_pnl) * 100
fees_pct_volume = total_fees / sum(notional_value) * 100
maker_fill_rate = count(role == "maker") / len(trades) * 100
gst_estimate    = total_fees * 0.18
```

Split fees by maker and taker, by instrument (perpetuals vs options), and the
top 10 underlyings by fee spend.

`gst_estimate` is 18% Indian GST applied to exchange fees. It is an estimate,
not a tax statement — label it that way. Delta's own baseline rates are 0.05%
taker and 0.02% maker on perpetuals; use the product's real
`taker_commission_rate` when precision matters.

## 8. Portfolio

From `get_margined_positions`, for each position with non-zero `size`: symbol,
underlying, absolute size, direction from the sign, `entry_price`, `mark_price`,
`unrealized_pnl`, `margin`, `liquidation_price`, `realized_funding`.

Notional for options uses the index price, never the premium:

```
notional_usd = abs(size) * contract_value * index_price
```

`unrealized_pnl` for short options is already sign-corrected by the server. Use
it as given.

Report open count, total unrealized, best and worst position, and each
underlying's share of total notional.
