import pytest

from ghost_amm.exchange.ccxt_gateway import CcxtGateway, CcxtGatewayBlocked


def test_ccxt_gateway_blocks_order_submission_and_withdrawal_surface() -> None:
    gateway = CcxtGateway()
    with pytest.raises(CcxtGatewayBlocked):
        gateway.create_order("BTC/JPY", "limit", "buy", 0.001, 100)
    assert not hasattr(gateway, "withdraw")
