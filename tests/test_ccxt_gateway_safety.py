import pytest

from ghost_amm.exchange.ccxt_gateway import CcxtGateway, CcxtGatewayBlocked, external_fair_event_from_tickers


def test_ccxt_gateway_blocks_order_submission_and_withdrawal_surface() -> None:
    gateway = CcxtGateway()
    with pytest.raises(CcxtGatewayBlocked):
        gateway.create_order("BTC/JPY", "limit", "buy", 0.001, 100)
    assert not hasattr(gateway, "withdraw")


def test_external_fair_event_from_ccxt_tickers_converts_btc_usd_to_jpy() -> None:
    event = external_fair_event_from_tickers(
        {"bid": 49990, "ask": 50010, "timestamp": 1000},
        {"last": 150, "timestamp": 900},
        exchange_id="external",
        ts_ms=1100,
    )

    assert event.event_type == "external_fair_price"
    assert event.ts_exchange == 1100
    assert event.payload["source"] == "external_btc_usd_jpy"
    assert event.payload["btc_usd"] == 50000
    assert event.payload["usd_jpy"] == 150
    assert event.payload["fair_jpy"] == 7500000
