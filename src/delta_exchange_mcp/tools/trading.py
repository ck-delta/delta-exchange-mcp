"""Authenticated trading tools (mutations).

Registered only when DELTA_API_KEY/SECRET are set AND DELTA_MCP_MODE=trade. Every tool
takes a `dry_run` flag that validates and echoes the payload without sending it, and every
call (dry-run or real) is recorded to the audit log. Mutations never auto-retry (see
DeltaClient retry policy) — a timeout is surfaced, not silently re-sent.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from delta_exchange_mcp.audit_log import AuditLog
from delta_exchange_mcp.client import DeltaClient
from delta_exchange_mcp.errors import DeltaApiError

_MAX_BATCH = 50
_STOP_TRIGGER_METHODS = "mark_price, last_traded_price, spot_price"


def _bs(value: bool | None) -> str | None:
    """Delta's order-level flags are string enums "true"/"false", not JSON booleans."""
    if value is None:
        return None
    return "true" if value else "false"


def _csv(values: list[str] | None) -> str | None:
    if not values:
        return None
    return ",".join(values)


def _clean(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop None-valued keys so we never send `field: null` in a request body."""
    return {k: v for k, v in payload.items() if v is not None}


def _require_one(product_id: int | None, product_symbol: str | None) -> None:
    if (product_id is None) == (product_symbol is None):
        raise ValueError("pass exactly one of product_id or product_symbol")


def register(mcp: FastMCP, client: DeltaClient, audit: AuditLog | None = None) -> None:
    _uid_cache: dict[str, int] = {}

    async def _user_id() -> int:
        if "id" not in _uid_cache:
            prof = await client.get("/profile", auth=True)
            inner = prof.get("result", prof) if isinstance(prof, dict) else {}
            uid = inner.get("id") or inner.get("user_id") if isinstance(inner, dict) else None
            if uid is None:
                raise ValueError("could not resolve user_id from /profile")
            _uid_cache["id"] = int(uid)
        return _uid_cache["id"]

    async def _finish(
        tool: str, method: str, path: str, payload: dict[str, Any], *, dry_run: bool
    ) -> Any:
        payload = _clean(payload)
        if dry_run:
            if audit:
                audit.record(tool, payload, dry_run=True)
            return {"dry_run": True, "method": method, "path": path, "payload": payload}
        sender = {"POST": client.post, "PUT": client.put, "DELETE": client.delete}[method]
        try:
            result = await sender(path, payload, auth=True)
        except DeltaApiError as e:
            if audit:
                audit.record(tool, payload, error=str(e))
            raise
        if audit:
            audit.record(tool, payload, result=result)
        return result

    # ---------------------------------------------------------------- single order

    @mcp.tool()
    async def place_order(
        size: int = Field(description="Order size in contracts."),
        side: str = Field(description="buy or sell."),
        order_type: str = Field(description="limit_order or market_order."),
        product_id: int | None = Field(default=None, description="Product id (or pass product_symbol)."),
        product_symbol: str | None = Field(default=None, description="e.g. BTCUSD (or pass product_id)."),
        limit_price: str | None = Field(default=None, description="Required for limit_order."),
        stop_order_type: str | None = Field(default=None, description="stop_loss_order or take_profit_order."),
        stop_price: str | None = Field(default=None, description="Trigger price for stop orders."),
        trail_amount: str | None = Field(default=None, description="Trailing-stop amount."),
        stop_trigger_method: str | None = Field(default=None, description=_STOP_TRIGGER_METHODS),
        time_in_force: str | None = Field(default=None, description="gtc or ioc."),
        post_only: bool | None = Field(default=None, description="Reject if it would take liquidity."),
        reduce_only: bool | None = Field(default=None, description="Only reduce an existing position."),
        client_order_id: str | None = Field(default=None, description="Your id, max 32 chars."),
        dry_run: bool = Field(default=False, description="Validate + echo payload without sending."),
    ) -> dict[str, Any]:
        """Place a single order. Pass exactly one of product_id or product_symbol.

        limit_price is required for limit_order. For stop orders set stop_order_type plus
        stop_price (or trail_amount).
        """
        _require_one(product_id, product_symbol)
        payload = {
            "size": size,
            "side": side,
            "order_type": order_type,
            "product_id": product_id,
            "product_symbol": product_symbol,
            "limit_price": limit_price,
            "stop_order_type": stop_order_type,
            "stop_price": stop_price,
            "trail_amount": trail_amount,
            "stop_trigger_method": stop_trigger_method,
            "time_in_force": time_in_force,
            "post_only": _bs(post_only),
            "reduce_only": _bs(reduce_only),
            "client_order_id": client_order_id,
        }
        return await _finish("place_order", "POST", "/orders", payload, dry_run=dry_run)

    @mcp.tool()
    async def edit_order(
        id: int = Field(description="Order id to edit."),
        size: int = Field(description="Total size after the edit."),
        product_id: int | None = Field(default=None, description="Product id (or pass product_symbol)."),
        product_symbol: str | None = Field(default=None, description="e.g. BTCUSD (or pass product_id)."),
        limit_price: str | None = Field(default=None, description="New limit price."),
        stop_price: str | None = Field(default=None, description="New stop trigger price."),
        trail_amount: str | None = Field(default=None, description="New trailing-stop amount."),
        post_only: bool | None = Field(default=None, description="Reject if it would take liquidity."),
        dry_run: bool = Field(default=False, description="Validate + echo payload without sending."),
    ) -> dict[str, Any]:
        """Edit an open order. Pass exactly one of product_id or product_symbol."""
        _require_one(product_id, product_symbol)
        payload = {
            "id": id,
            "size": size,
            "product_id": product_id,
            "product_symbol": product_symbol,
            "limit_price": limit_price,
            "stop_price": stop_price,
            "trail_amount": trail_amount,
            "post_only": _bs(post_only),
        }
        return await _finish("edit_order", "PUT", "/orders", payload, dry_run=dry_run)

    @mcp.tool()
    async def cancel_order(
        product_id: int = Field(description="Product id the order belongs to."),
        id: int | None = Field(default=None, description="Order id to cancel."),
        client_order_id: str | None = Field(default=None, description="Your client_order_id."),
        dry_run: bool = Field(default=False, description="Validate + echo payload without sending."),
    ) -> dict[str, Any]:
        """Cancel a single order by id or client_order_id."""
        if (id is None) == (client_order_id is None):
            raise ValueError("pass exactly one of id or client_order_id")
        payload = {"product_id": product_id, "id": id, "client_order_id": client_order_id}
        return await _finish("cancel_order", "DELETE", "/orders", payload, dry_run=dry_run)

    @mcp.tool()
    async def cancel_all_orders(
        product_id: int | None = Field(default=None, description="Limit to one product."),
        contract_types: list[str] | None = Field(
            default=None, description="Limit to contract types (ignored if product_id is set)."
        ),
        cancel_limit_orders: bool | None = Field(default=None, description="Include limit orders."),
        cancel_stop_orders: bool | None = Field(default=None, description="Include stop orders."),
        cancel_reduce_only_orders: bool | None = Field(default=None, description="Include reduce-only orders."),
        dry_run: bool = Field(default=False, description="Validate + echo payload without sending."),
    ) -> dict[str, Any]:
        """Cancel open orders. WARNING: with no filters this cancels ALL of your open orders."""
        payload = {
            "product_id": product_id,
            "contract_types": _csv(contract_types),
            "cancel_limit_orders": _bs(cancel_limit_orders),
            "cancel_stop_orders": _bs(cancel_stop_orders),
            "cancel_reduce_only_orders": _bs(cancel_reduce_only_orders),
        }
        return await _finish("cancel_all_orders", "DELETE", "/orders/all", payload, dry_run=dry_run)

    # ---------------------------------------------------------------- batch orders

    def _check_batch(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not orders:
            raise ValueError("orders must be a non-empty list")
        if len(orders) > _MAX_BATCH:
            raise ValueError(f"batch size {len(orders)} exceeds max {_MAX_BATCH}")
        return [_clean(o) for o in orders]

    @mcp.tool()
    async def place_batch_orders(
        orders: list[dict[str, Any]] = Field(
            description="Up to 50 orders, each {size, side, order_type, limit_price?, "
            "time_in_force?, post_only?, client_order_id?}. All same contract. No IOC/stop."
        ),
        product_id: int | None = Field(default=None, description="Product id (or pass product_symbol)."),
        product_symbol: str | None = Field(default=None, description="e.g. BTCUSD (or pass product_id)."),
        dry_run: bool = Field(default=False, description="Validate + echo payload without sending."),
    ) -> dict[str, Any]:
        """Place up to 50 orders on one contract in a single request."""
        _require_one(product_id, product_symbol)
        payload = {
            "product_id": product_id,
            "product_symbol": product_symbol,
            "orders": _check_batch(orders),
        }
        return await _finish("place_batch_orders", "POST", "/orders/batch", payload, dry_run=dry_run)

    @mcp.tool()
    async def edit_batch_orders(
        orders: list[dict[str, Any]] = Field(
            description="Up to 50 edits, each {id, size, order_type, limit_price?, post_only?}."
        ),
        product_id: int | None = Field(default=None, description="Product id (or pass product_symbol)."),
        product_symbol: str | None = Field(default=None, description="e.g. BTCUSD (or pass product_id)."),
        dry_run: bool = Field(default=False, description="Validate + echo payload without sending."),
    ) -> dict[str, Any]:
        """Edit up to 50 orders on one contract in a single request."""
        _require_one(product_id, product_symbol)
        payload = {
            "product_id": product_id,
            "product_symbol": product_symbol,
            "orders": _check_batch(orders),
        }
        return await _finish("edit_batch_orders", "PUT", "/orders/batch", payload, dry_run=dry_run)

    @mcp.tool()
    async def cancel_batch_orders(
        orders: list[dict[str, Any]] = Field(
            description="Up to 50 orders to cancel, each {id} or {client_order_id}."
        ),
        product_id: int | None = Field(default=None, description="Product id (or pass product_symbol)."),
        product_symbol: str | None = Field(default=None, description="e.g. BTCUSD (or pass product_id)."),
        dry_run: bool = Field(default=False, description="Validate + echo payload without sending."),
    ) -> dict[str, Any]:
        """Cancel up to 50 orders on one contract in a single request."""
        _require_one(product_id, product_symbol)
        payload = {
            "product_id": product_id,
            "product_symbol": product_symbol,
            "orders": _check_batch(orders),
        }
        return await _finish("cancel_batch_orders", "DELETE", "/orders/batch", payload, dry_run=dry_run)

    # ---------------------------------------------------------------- bracket orders

    @mcp.tool()
    async def place_bracket_order(
        product_id: int | None = Field(default=None, description="Product id (or pass product_symbol)."),
        product_symbol: str | None = Field(default=None, description="e.g. BTCUSD (or pass product_id)."),
        stop_loss_order: dict[str, Any] | None = Field(
            default=None, description="{order_type, stop_price, limit_price?, trail_amount?}."
        ),
        take_profit_order: dict[str, Any] | None = Field(
            default=None, description="{order_type, stop_price, limit_price?}."
        ),
        bracket_stop_trigger_method: str | None = Field(default=None, description=_STOP_TRIGGER_METHODS),
        dry_run: bool = Field(default=False, description="Validate + echo payload without sending."),
    ) -> dict[str, Any]:
        """Attach a take-profit / stop-loss bracket to a position. Provide at least one leg."""
        _require_one(product_id, product_symbol)
        if stop_loss_order is None and take_profit_order is None:
            raise ValueError("provide at least one of stop_loss_order or take_profit_order")
        payload = {
            "product_id": product_id,
            "product_symbol": product_symbol,
            "stop_loss_order": _clean(stop_loss_order) if stop_loss_order else None,
            "take_profit_order": _clean(take_profit_order) if take_profit_order else None,
            "bracket_stop_trigger_method": bracket_stop_trigger_method,
        }
        return await _finish("place_bracket_order", "POST", "/orders/bracket", payload, dry_run=dry_run)

    @mcp.tool()
    async def edit_bracket_order(
        id: int = Field(description="Order id whose bracket params to update."),
        product_id: int | None = Field(default=None, description="Product id (or pass product_symbol)."),
        product_symbol: str | None = Field(default=None, description="e.g. BTCUSD (or pass product_id)."),
        bracket_stop_loss_price: str | None = Field(default=None, description="Stop-loss trigger price."),
        bracket_stop_loss_limit_price: str | None = Field(default=None, description="Stop-loss limit price."),
        bracket_take_profit_price: str | None = Field(default=None, description="Take-profit trigger price."),
        bracket_take_profit_limit_price: str | None = Field(default=None, description="Take-profit limit price."),
        bracket_trail_amount: str | None = Field(default=None, description="Trailing-stop amount."),
        bracket_stop_trigger_method: str | None = Field(default=None, description=_STOP_TRIGGER_METHODS),
        dry_run: bool = Field(default=False, description="Validate + echo payload without sending."),
    ) -> dict[str, Any]:
        """Edit the bracket (TP/SL) params on an existing order."""
        _require_one(product_id, product_symbol)
        payload = {
            "id": id,
            "product_id": product_id,
            "product_symbol": product_symbol,
            "bracket_stop_loss_price": bracket_stop_loss_price,
            "bracket_stop_loss_limit_price": bracket_stop_loss_limit_price,
            "bracket_take_profit_price": bracket_take_profit_price,
            "bracket_take_profit_limit_price": bracket_take_profit_limit_price,
            "bracket_trail_amount": bracket_trail_amount,
            "bracket_stop_trigger_method": bracket_stop_trigger_method,
        }
        return await _finish("edit_bracket_order", "PUT", "/orders/bracket", payload, dry_run=dry_run)

    # ---------------------------------------------------------------- positions & leverage

    @mcp.tool()
    async def set_product_leverage(
        product_id: int = Field(description="Product id to set order leverage for."),
        leverage: str = Field(description="Leverage multiplier, e.g. '10'."),
        dry_run: bool = Field(default=False, description="Validate + echo payload without sending."),
    ) -> dict[str, Any]:
        """Set order leverage for a product."""
        return await _finish(
            "set_product_leverage", "POST",
            f"/products/{product_id}/orders/leverage", {"leverage": leverage}, dry_run=dry_run,
        )

    @mcp.tool()
    async def adjust_position_margin(
        product_id: int = Field(description="Product id of the position."),
        delta_margin: str = Field(description="Margin to add (positive) or remove (negative), e.g. '5.0'."),
        dry_run: bool = Field(default=False, description="Validate + echo payload without sending."),
    ) -> dict[str, Any]:
        """Add or remove isolated margin on a position."""
        payload = {"product_id": product_id, "delta_margin": delta_margin}
        return await _finish(
            "adjust_position_margin", "POST", "/positions/change_margin", payload, dry_run=dry_run
        )

    @mcp.tool()
    async def close_all_positions(
        close_all_portfolio: bool = Field(default=True, description="Close cross/portfolio-margined positions."),
        close_all_isolated: bool = Field(default=True, description="Close isolated-margin positions."),
        dry_run: bool = Field(default=False, description="Validate + echo payload without sending."),
    ) -> dict[str, Any]:
        """Close all open positions. WARNING: closes everything matching the flags.

        Your user_id is required by the API and is resolved automatically from your profile
        (fetched once and cached) — you do not pass it.
        """
        payload = {
            "close_all_portfolio": close_all_portfolio,
            "close_all_isolated": close_all_isolated,
            "user_id": await _user_id(),
        }
        return await _finish("close_all_positions", "POST", "/positions/close_all", payload, dry_run=dry_run)

    @mcp.tool()
    async def configure_auto_topup(
        product_id: int = Field(description="Product id of the position."),
        auto_topup: bool = Field(description="Enable or disable auto top-up for this position."),
        dry_run: bool = Field(default=False, description="Validate + echo payload without sending."),
    ) -> dict[str, Any]:
        """Override auto top-up for a single position (otherwise inherits the account setting)."""
        payload = {"product_id": product_id, "auto_topup": auto_topup}
        return await _finish("configure_auto_topup", "PUT", "/positions/auto_topup", payload, dry_run=dry_run)
