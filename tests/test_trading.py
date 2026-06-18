"""Trading tools: body signing, dry-run, validation, user_id caching, audit, mode gating."""

import hashlib
import hmac
import json
from typing import Any

import httpx
import pytest
import respx

from delta_exchange_mcp import audit_log
from delta_exchange_mcp.client import DeltaClient
from delta_exchange_mcp.config import INDIA_TESTNET_REST, Config
from delta_exchange_mcp.server import build_server
from delta_exchange_mcp.tools import trading
from mcp.server.fastmcp import FastMCP


def _client() -> DeltaClient:
    cfg = Config(
        env="india_testnet", base_url=INDIA_TESTNET_REST,
        api_key="k1", api_secret="s1", mode="trade",
    )
    return DeltaClient(cfg)


async def _call(client: DeltaClient, name: str, audit=None, **kwargs: Any) -> Any:
    mcp = FastMCP("test")
    trading.register(mcp, client, audit)
    return await mcp.call_tool(name, kwargs)


def _payload(call_result: Any) -> dict[str, Any]:
    """mcp.call_tool returns (content, structured); pull the structured dict out."""
    structured = call_result[1]
    return structured.get("result", structured) if isinstance(structured, dict) else structured


# --------------------------------------------------------------- body signing (critical)


@pytest.mark.asyncio
@respx.mock
async def test_place_order_signs_exact_body_bytes():
    route = respx.post(f"{INDIA_TESTNET_REST}/orders").mock(
        return_value=httpx.Response(200, json={"success": True, "result": {"id": 7}})
    )
    client = _client()
    await _call(
        client, "place_order",
        product_id=27, size=1, side="buy", order_type="limit_order", limit_price="10000",
    )

    req = route.calls[0].request
    body = req.content.decode()
    # Sent bytes must be compact JSON (no spaces) so the signature matches.
    assert body == json.dumps(json.loads(body), separators=(",", ":"))
    ts = req.headers["timestamp"]
    expected = hmac.new(b"s1", f"POST{ts}/v2/orders{body}".encode(), hashlib.sha256).hexdigest()
    assert req.headers["signature"] == expected
    assert req.headers["api-key"] == "k1"


@pytest.mark.asyncio
@respx.mock
async def test_post_only_bool_becomes_string_enum():
    route = respx.post(f"{INDIA_TESTNET_REST}/orders").mock(
        return_value=httpx.Response(200, json={"success": True, "result": {}})
    )
    client = _client()
    await _call(
        client, "place_order",
        product_id=27, size=1, side="buy", order_type="market_order", post_only=True,
    )
    assert route.calls[0].request.read().__contains__(b'"post_only":"true"')


@pytest.mark.asyncio
@respx.mock
async def test_auto_topup_bool_stays_json_bool():
    route = respx.put(f"{INDIA_TESTNET_REST}/positions/auto_topup").mock(
        return_value=httpx.Response(200, json={"success": True, "result": {}})
    )
    client = _client()
    await _call(client, "configure_auto_topup", product_id=27, auto_topup=True)
    assert b'"auto_topup":true' in route.calls[0].request.content


# --------------------------------------------------------------- dry-run


@pytest.mark.asyncio
@respx.mock
async def test_dry_run_sends_nothing_and_echoes_payload():
    route = respx.post(f"{INDIA_TESTNET_REST}/orders").mock(
        return_value=httpx.Response(200, json={"success": True, "result": {}})
    )
    client = _client()
    out = _payload(await _call(
        client, "place_order",
        product_id=27, size=2, side="sell", order_type="market_order", dry_run=True,
    ))
    assert route.called is False
    assert out["dry_run"] is True
    assert out["method"] == "POST" and out["path"] == "/orders"
    assert out["payload"]["size"] == 2 and out["payload"]["side"] == "sell"


# --------------------------------------------------------------- validation


@pytest.mark.asyncio
async def test_place_order_requires_exactly_one_product_ref():
    client = _client()
    with pytest.raises(Exception, match="exactly one of product_id or product_symbol"):
        await _call(client, "place_order", size=1, side="buy", order_type="market_order")
    with pytest.raises(Exception, match="exactly one of product_id or product_symbol"):
        await _call(
            client, "place_order",
            product_id=1, product_symbol="BTCUSD", size=1, side="buy", order_type="market_order",
        )


@pytest.mark.asyncio
async def test_batch_cap_enforced():
    client = _client()
    orders = [{"size": 1, "side": "buy", "order_type": "limit_order", "limit_price": "1"}] * 51
    with pytest.raises(Exception, match="exceeds max 50"):
        await _call(client, "place_batch_orders", product_id=27, orders=orders)


# --------------------------------------------------------------- user_id auto-fetch


@pytest.mark.asyncio
@respx.mock
async def test_close_all_fetches_and_caches_user_id():
    profile = respx.get(f"{INDIA_TESTNET_REST}/profile").mock(
        return_value=httpx.Response(200, json={"success": True, "result": {"id": 999}})
    )
    close = respx.post(f"{INDIA_TESTNET_REST}/positions/close_all").mock(
        return_value=httpx.Response(200, json={"success": True, "result": {}})
    )
    client = _client()
    mcp = FastMCP("test")
    trading.register(mcp, client, None)
    await mcp.call_tool("close_all_positions", {})
    await mcp.call_tool("close_all_positions", {})

    assert profile.call_count == 1  # cached after first fetch
    assert close.call_count == 2
    assert b'"user_id":999' in close.calls[0].request.content


# --------------------------------------------------------------- audit log


@pytest.mark.asyncio
@respx.mock
async def test_audit_records_success_and_error_without_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("DELTA_MCP_AUDIT_FILE", str(tmp_path / "audit.log"))
    monkeypatch.setattr(audit_log, "_INSTANCE", None)
    cfg = Config(
        env="india_testnet", base_url=INDIA_TESTNET_REST,
        api_key="k1", api_secret="s1", mode="trade",
    )
    audit = audit_log.configure(cfg)
    assert audit is not None

    respx.post(f"{INDIA_TESTNET_REST}/orders").mock(
        side_effect=[
            httpx.Response(200, json={"success": True, "result": {"id": 5, "state": "open"}}),
            httpx.Response(400, json={"success": False, "error": {"code": "insufficient_margin"}}),
        ]
    )
    client = _client()
    await _call(client, "place_order", audit=audit,
                product_id=27, size=1, side="buy", order_type="market_order")
    # FastMCP wraps the DeltaApiError in a ToolError, but _finish records it first.
    with pytest.raises(Exception, match="insufficient_margin"):
        await _call(client, "place_order", audit=audit,
                    product_id=27, size=1, side="buy", order_type="market_order")

    text = (tmp_path / "audit.log").read_text()
    lines = [json.loads(line) for line in text.splitlines()]
    assert len(lines) == 2
    assert lines[0]["result"] == {"id": 5, "state": "open"}
    assert "insufficient_margin" in lines[1]["error"]
    # Credentials must never appear in the audit file.
    assert "s1" not in text and "signature" not in text and "api-key" not in text


@pytest.mark.asyncio
async def test_audit_kill_switch(tmp_path, monkeypatch):
    monkeypatch.setenv("DELTA_MCP_AUDIT", "off")
    monkeypatch.setattr(audit_log, "_INSTANCE", None)
    cfg = Config(
        env="india_testnet", base_url=INDIA_TESTNET_REST,
        api_key="k1", api_secret="s1", mode="trade",
    )
    assert audit_log.configure(cfg) is None


# --------------------------------------------------------------- mode gating


def test_trade_tools_absent_in_read_mode():
    cfg = Config(
        env="india_testnet", base_url=INDIA_TESTNET_REST,
        api_key="k1", api_secret="s1", mode="read",
    )
    mcp = build_server(cfg)
    names = {t.name for t in mcp._tool_manager.list_tools()}
    assert "place_order" not in names
    assert "get_positions" in names  # account tools still present


def test_trade_tools_present_in_trade_mode(monkeypatch):
    monkeypatch.setenv("DELTA_MCP_AUDIT", "off")  # no file writes during this test
    monkeypatch.setattr(audit_log, "_INSTANCE", None)
    cfg = Config(
        env="india_testnet", base_url=INDIA_TESTNET_REST,
        api_key="k1", api_secret="s1", mode="trade",
    )
    mcp = build_server(cfg)
    names = {t.name for t in mcp._tool_manager.list_tools()}
    for tool in (
        "place_order", "edit_order", "cancel_order", "cancel_all_orders",
        "place_batch_orders", "edit_batch_orders", "cancel_batch_orders",
        "place_bracket_order", "edit_bracket_order", "set_product_leverage",
        "adjust_position_margin", "close_all_positions", "configure_auto_topup",
    ):
        assert tool in names
