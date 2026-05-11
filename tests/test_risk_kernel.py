from ghost_amm.amm.inventory import InventoryState
from ghost_amm.exchange.bitbank_rules import BitbankStatus, fallback_btc_jpy_spec
from ghost_amm.market.fair_price import FairPriceEngine
from ghost_amm.market.orderbook import OrderBook
from ghost_amm.market.shock import ShockState
from ghost_amm.risk.kernel import RiskKernel


def test_risk_blocks_wide_spread() -> None:
    book = OrderBook("bitbank", "BTC/JPY")
    book.apply_snapshot({"bids": [["90", "100000"]], "asks": [["110", "100000"]]}, 1, 1)
    fair = FairPriceEngine(max_spread_bps=10_000, stale_after_ms=1000).from_orderbook(book, 1)
    risk = RiskKernel(market_cfg={"max_spread_bps": 50, "min_depth_20bps_jpy": 0}, risk_cfg={"block_on_pair_stop_flags": True, "max_abs_skew": 10}, shock_cfg={"min_activation_to_quote": 0.1}, amm_cfg={"max_order_size": 1})
    decision = risk.evaluate(book=book, fair_state=fair, shock_state=ShockState(1, 1, 0, 0, 1, 1, None), inventory=InventoryState(1, 100), pair_spec=fallback_btc_jpy_spec(), status=BitbankStatus("btc_jpy", "NORMAL", 0.0001), now_ms=1)
    assert not decision.allow_quote
    assert decision.reason == "spread_too_wide"
