"""The shipped P&L calculator owns matching, funding state, and report output."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from delta_exchange_mcp.report.cli import render_dashboard, run
from delta_exchange_mcp.report.contract import INPUT_VERSION, Product, ReportInput
from delta_exchange_mcp.report.fifo import Fill, match
from delta_exchange_mcp.report.metrics import calculate

START = datetime(2026, 1, 1, tzinfo=UTC)
PRODUCT = Product(
    product_id=27,
    symbol="BTCUSD",
    underlying="BTC",
    contract_type="perpetual_futures",
    contract_value=1,
)


def fill(side: str, price: float, hour: int, fee: float = 1) -> Fill:
    return Fill(
        product_id=27,
        product_symbol="BTCUSD",
        quantity=1,
        side=side,
        price=price,
        fee=fee,
        created_at=START + timedelta(hours=hour),
        role="maker",
    )


def report_input(tmp_path: Path, **overrides: Any) -> ReportInput:
    values = {
        "schema_version": INPUT_VERSION,
        "fills_csv": tmp_path / "fills.csv",
        "window_start": START,
        "window_end": START + timedelta(days=1),
        "generated_at": START + timedelta(days=1),
        "products": [PRODUCT],
        "funding": None,
        "positions": None,
    }
    values.update(overrides)
    return ReportInput(**values)


def test_fifo_closes_the_oldest_entry_instead_of_the_average_price() -> None:
    trades = match(
        [fill("buy", 100, 0), fill("buy", 200, 1), fill("sell", 150, 2)],
        {27: PRODUCT},
    )

    assert len(trades) == 1
    assert trades[0].entry_price == 100
    assert trades[0].pnl == 50
    assert trades[0].fees == 2
    assert trades[0].net_pnl == 48


def test_fifo_allocates_entry_and_exit_fees_across_partial_lots() -> None:
    opening = Fill(
        product_id=27,
        product_symbol="BTCUSD",
        quantity=2,
        side="buy",
        price=100,
        fee=4,
        created_at=START,
        role="taker",
    )
    first_close = fill("sell", 110, 1, fee=3)
    second_close = fill("sell", 120, 2, fee=5)

    trades = match([opening, first_close, second_close], {27: PRODUCT})

    assert [trade.fees for trade in trades] == [5, 7]
    assert sum(trade.fees for trade in trades) == 12


def test_fifo_preserves_negative_maker_commission_as_a_rebate() -> None:
    trades = match(
        [fill("buy", 100, 0, fee=-1), fill("sell", 150, 1, fee=-1)],
        {27: PRODUCT},
    )

    assert trades[0].fees == -2
    assert trades[0].net_pnl == 52


def test_fifo_close_can_span_lots_and_flip_direction() -> None:
    closing = Fill(
        product_id=27,
        product_symbol="BTCUSD",
        quantity=3,
        side="sell",
        price=130,
        fee=0,
        created_at=START + timedelta(hours=2),
        role="taker",
    )
    trades = match(
        [
            fill("buy", 100, 0, fee=0),
            fill("buy", 120, 1, fee=0),
            closing,
            fill("buy", 120, 3, fee=0),
        ],
        {27: PRODUCT},
    )

    assert [trade.entry_price for trade in trades] == [100, 120, 130]
    assert [trade.direction for trade in trades] == ["long", "long", "short"]
    assert [trade.pnl for trade in trades] == [30, 10, 10]


def test_missing_funding_stays_unavailable_instead_of_becoming_zero(
    tmp_path: Path,
) -> None:
    fills = [fill("buy", 100, 0), fill("sell", 150, 1)]
    unavailable = calculate(report_input(tmp_path, funding=None), fills)
    fetched_empty = calculate(report_input(tmp_path, funding=[]), fills)

    assert unavailable.headline.funding is None
    assert unavailable.headline.net_including_funding is None
    assert unavailable.funding is None
    assert fetched_empty.headline.funding == 0
    assert fetched_empty.headline.net_including_funding == 48
    assert fetched_empty.funding is not None


def test_missing_product_contract_fails_instead_of_assuming_one(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="no product contract"):
        calculate(report_input(tmp_path, products=[]), [fill("buy", 100, 0)])


def test_cli_validates_and_writes_the_versioned_report_and_dashboard(
    tmp_path: Path,
) -> None:
    fills = tmp_path / "fills.csv"
    fills.write_text(
        "product_id,product_symbol,size,side,price,commission,created_at,role\n"
        "27,BTCUSD,1,buy,100,1,2026-01-01T00:00:00Z,maker\n"
        "27,BTCUSD,1,sell,150,1,2026-01-01T01:00:00Z,maker\n",
        encoding="utf-8",
    )
    source = tmp_path / "input.json"
    source.write_text(
        report_input(tmp_path, fills_csv="fills.csv", funding=[]).model_dump_json(),
        encoding="utf-8",
    )
    output = tmp_path / "report.json"
    dashboard = tmp_path / "report.html"

    run(source, output, dashboard)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["meta"]["schema_version"] == "delta.pnl.report.v1"
    assert payload["headline"]["net_pnl"] == 48
    assert (
        json.loads(
            dashboard.read_text(encoding="utf-8")
            .split('<script id="pnl-data" type="application/json">', 1)[1]
            .split("</script>", 1)[0]
        )
        == payload
    )
    with pytest.raises(ValueError, match="must not overwrite"):
        run(source, source)


def test_dashboard_embedding_escapes_a_script_close_sequence() -> None:
    rendered = render_dashboard(
        {"headline": {"leak": "</script><script>bad()</script>"}}
    )
    island = rendered.split('<script id="pnl-data" type="application/json">', 1)[
        1
    ].split("</script>", 1)[0]

    assert "</script>" not in island
    assert json.loads(island)["headline"]["leak"] == "</script><script>bad()</script>"
