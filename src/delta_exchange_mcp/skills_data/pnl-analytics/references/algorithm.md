# Data acquisition and round-trip matching

Ported from the Delta P&L Analytics engine (`analytics-engine.ts`, `matchTrades`).
Follow it exactly — the metrics in `metrics.md` assume trades in this shape.

## 1. Fetch

| Step | Call | Why |
|---|---|---|
| 1 | `get_profile()` | Confirms auth and gives the user id. |
| 2 | `list_products(page_size=500)` | Product map keyed by `product_id`. Page through `meta.after` until exhausted; there are well over 500 products. |
| 3 | `bulk_fills_export(output_path, start_time_us)` or paged `get_fills` | The fills. |
| 4 | `get_wallet_transactions(transaction_types=["funding"], start_time_us=...)` | Funding is not in fills. |
| 5 | `get_margined_positions()` | Open positions, for unrealized P&L. |
| 6 | `get_wallet_balances()` | Equity, for portfolio context. |

From each product keep `contract_value`, `contract_type`, `underlying_asset.symbol`
and `symbol`. Expired products are absent from the default `list_products`
response; for a history that includes settled options, also pull
`get_settlement_prices(page_size=500)` and merge, or fall back to parsing the
underlying out of the fill's `product_symbol`.

Every `*_us` argument is microseconds since epoch. Multiply seconds by 1e6.

## 2. Match fills into round trips

Sort all fills ascending by `created_at`. Hold one open position per
`product_id`:

```
position = {size, avg_entry, fees, first_time, role}
```

`size` is signed: positive long, negative short. For each fill:

```
size   = int(fill.size)
price  = float(fill.price)
fee    = abs(float(fill.commission))
signed = +size if fill.side == "buy" else -size
```

Skip the fill when `size` or `price` is zero.

**Same direction, or flat.** When `old_size >= 0 and signed > 0`, or
`old_size <= 0 and signed < 0`, or `old_size == 0` — the position grows:

```
avg_entry = (avg_entry * abs(old_size) + price * size) / (abs(old_size) + size)
size      = old_size + signed
fees     += fee
```

When `old_size` was 0, reset `first_time` to this fill's `created_at` and `role`
to this fill's `role`. Continue to the next fill.

**Opposing direction.** The fill closes, and may then flip:

```
close_qty = min(abs(signed), abs(old_size))
direction = "long" if old_size > 0 else "short"

pnl = close_qty * contract_value * (price - avg_entry)        # long
pnl = close_qty * contract_value * (avg_entry - price)        # short
```

Emit one round trip:

| Field | Value |
|---|---|
| `underlying` | `product.underlying_asset.symbol`, else the first 3 chars of `product_symbol` |
| `product_symbol` | from the fill |
| `instrument_type` | `call` / `put` if `contract_type` contains "call" / "put", else `perpetual` |
| `direction` | as above |
| `entry_time` / `exit_time` | `first_time` / this fill's `created_at` |
| `entry_price` / `exit_price` | `avg_entry` / `price` |
| `size` | `close_qty` |
| `notional_value` | `close_qty * contract_value * price` |
| `pnl` | gross, from above |
| `fees` | `position.fees + fee` — all fees accumulated on the position, charged to this exit |
| `net_pnl` | `pnl - fees` |
| `pnl_pct` | `pnl / notional_value * 100`, or 0 when notional is 0 |
| `hold_duration_hours` | `(exit_time - entry_time) / 3600` |
| `role` | the position's role, one of `maker` / `taker` |

**Then update the position.** With `remaining = abs(signed) - close_qty`:

- `remaining > 0` — the fill flipped the position. Start fresh at this fill:
  `size = ±remaining` (sign of `signed`), `avg_entry = price`, `fees = 0`,
  `first_time = this fill's time`.
- `remaining == 0` — reduced or closed. `size = old_size + signed`; keep
  `avg_entry` when the new size is non-zero, otherwise 0; `fees = 0`;
  `first_time` unchanged.

Resetting `fees` to 0 after an exit is deliberate: those fees were already
charged to the round trip just emitted. Carrying them forward double-counts.

## 3. Known limits of this method

State these when they apply rather than letting the reader assume otherwise.

- **Fees land on the exit.** A position built over ten entries and closed once
  attributes all ten entry fees to that single round trip. Totals are right;
  per-trade fee figures on partial exits are approximate.
- **Positions open at the start of the window** produce an exit with no matching
  entry. They are skipped, because the first fill seen for a product is treated
  as an opening fill. A window that begins mid-position understates activity —
  another reason to pass a real `start_time_us`.
- **`funding_pnl` on a round trip is 0.** Funding is settled against the
  position, not the fill, so it is accounted separately from
  `get_wallet_transactions`. Never add it into `net_pnl` per trade.
- **Options that expired worthless** may have no closing fill at all. They
  settle. Reconcile with `get_settlement_prices` if the user's history is
  options-heavy and the numbers look light.
- **`contract_value` defaults to 1** when the product is unknown. A missing
  product map silently rescales every number, so verify the map covers every
  `product_id` in the fills before computing, and report how many did not match.
