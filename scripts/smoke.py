"""Manual smoke test. Usage: uv run python scripts/smoke.py (hits the env from DELTA_MCP_ENV, default india_prod)."""

from __future__ import annotations

import asyncio
import time

from delta_exchange_mcp import config as config_mod
from delta_exchange_mcp.client import DeltaClient


async def main() -> None:
    cfg = config_mod.load()
    client = DeltaClient(cfg)
    try:
        print(f"env={cfg.env} base_url={cfg.base_url}")

        products = await client.get("/products", params={"page_size": 3, "states": "live"})
        result = products["result"] if isinstance(products, dict) else products
        print(f"\n[products] count={len(result)} first={result[0]['symbol'] if result else None}")

        symbol = result[0]["symbol"] if result else "BTCUSD"
        ticker = await client.get(f"/tickers/{symbol}")
        print(f"\n[ticker {symbol}] keys={list(ticker['result'].keys())[:6]}")

        ob = await client.get(f"/l2orderbook/{symbol}", params={"depth": 3})
        print(f"\n[orderbook {symbol}] buy={len(ob['result'].get('buy', []))} sell={len(ob['result'].get('sell', []))}")

        now = int(time.time())
        candles = await client.get(
            "/history/candles",
            params={"symbol": symbol, "resolution": "1h", "start": now - 6 * 3600, "end": now},
        )
        print(f"\n[candles {symbol} 1h] count={len(candles['result'])}")

        assets = await client.get("/assets")
        print(f"\n[assets] count={len(assets['result'])}")
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
