from ghost_amm.amm.inventory import InventoryState
from ghost_amm.exchange.bitbank_rules import BitbankStatus, fallback_btc_jpy_spec
from ghost_amm.market.fair_price import FairPriceEngine, FairPriceState
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


def test_fill_burst_cooldown_blocks_only_same_side_until_expiry() -> None:
    book = OrderBook("bitbank", "BTC/JPY")
    book.apply_snapshot({"bids": [["99", "100000"]], "asks": [["101", "100000"]]}, 1, 1)
    fair = FairPriceEngine(max_spread_bps=10_000, stale_after_ms=1000).from_orderbook(book, 1)
    risk = RiskKernel(
        market_cfg={"max_spread_bps": 500, "min_depth_20bps_jpy": 0},
        risk_cfg={
            "block_on_pair_stop_flags": True,
            "max_abs_skew": 10,
            "max_same_side_fills_per_window": 3,
            "fill_burst_window_ms": 10_000,
            "fill_burst_cooldown_ms": 60_000,
        },
        shock_cfg={"min_activation_to_quote": 0.1},
        amm_cfg={"max_order_size": 1},
    )
    for ts in [1000, 2000, 3000]:
        risk.record_fill(side="buy", ts_ms=ts)

    decision = risk.evaluate(
        book=book,
        fair_state=fair,
        shock_state=ShockState(1, 1, 0, 0, 1, 1, None),
        inventory=InventoryState(1, 100),
        pair_spec=fallback_btc_jpy_spec(),
        status=BitbankStatus("btc_jpy", "NORMAL", 0.0001),
        now_ms=3000,
    )

    assert decision.allow_quote
    assert not decision.allow_buy
    assert decision.allow_sell
    assert decision.reason == "fill_burst_cooldown"
    assert decision.blocked_sides == ["buy"]

    after_cooldown = risk.evaluate(
        book=book,
        fair_state=fair,
        shock_state=ShockState(1, 1, 0, 0, 1, 1, None),
        inventory=InventoryState(1, 100),
        pair_spec=fallback_btc_jpy_spec(),
        status=BitbankStatus("btc_jpy", "NORMAL", 0.0001),
        now_ms=63_001,
    )
    assert after_cooldown.allow_buy
    assert after_cooldown.allow_sell
    assert after_cooldown.reason is None


def test_fill_burst_cooldown_can_block_all_quotes_when_both_sides_burst() -> None:
    book = OrderBook("bitbank", "BTC/JPY")
    book.apply_snapshot({"bids": [["99", "100000"]], "asks": [["101", "100000"]]}, 1, 1)
    fair = FairPriceEngine(max_spread_bps=10_000, stale_after_ms=1000).from_orderbook(book, 1)
    risk = RiskKernel(
        market_cfg={"max_spread_bps": 500, "min_depth_20bps_jpy": 0},
        risk_cfg={
            "block_on_pair_stop_flags": True,
            "max_abs_skew": 10,
            "max_same_side_fills_per_window": 2,
            "fill_burst_window_ms": 10_000,
            "fill_burst_cooldown_ms": 60_000,
        },
        shock_cfg={"min_activation_to_quote": 0.1},
        amm_cfg={"max_order_size": 1},
    )
    for side in ["buy", "buy", "sell", "sell"]:
        risk.record_fill(side=side, ts_ms=1000)

    decision = risk.evaluate(
        book=book,
        fair_state=fair,
        shock_state=ShockState(1, 1, 0, 0, 1, 1, None),
        inventory=InventoryState(1, 100),
        pair_spec=fallback_btc_jpy_spec(),
        status=BitbankStatus("btc_jpy", "NORMAL", 0.0001),
        now_ms=1000,
    )

    assert not decision.allow_quote
    assert not decision.allow_buy
    assert not decision.allow_sell
    assert decision.reason == "fill_burst_cooldown"
    assert decision.blocked_sides == ["buy", "sell"]


def test_inventory_max_base_qty_blocks_buy_only() -> None:
    book = OrderBook("bitbank", "BTC/JPY")
    book.apply_snapshot({"bids": [["99", "100000"]], "asks": [["101", "100000"]]}, 1, 1)
    fair = FairPriceEngine(max_spread_bps=10_000, stale_after_ms=1000).from_orderbook(book, 1)
    risk = RiskKernel(
        market_cfg={"max_spread_bps": 500, "min_depth_20bps_jpy": 0},
        risk_cfg={"block_on_pair_stop_flags": True, "max_abs_skew": 10, "max_base_qty": 1.5},
        shock_cfg={"min_activation_to_quote": 0.1},
        amm_cfg={"max_order_size": 1},
    )

    decision = risk.evaluate(
        book=book,
        fair_state=fair,
        shock_state=ShockState(1, 1, 0, 0, 1, 1, None),
        inventory=InventoryState(1, 1000),
        pair_spec=fallback_btc_jpy_spec(),
        status=BitbankStatus("btc_jpy", "NORMAL", 0.0001),
        now_ms=1,
    )

    assert decision.allow_quote
    assert not decision.allow_buy
    assert decision.allow_sell
    assert decision.side_block_reasons["buy"] == "max_base_qty"


def test_inventory_balance_limits_block_unfunded_sides() -> None:
    book = OrderBook("bitbank", "BTC/JPY")
    book.apply_snapshot({"bids": [["99", "100000"]], "asks": [["101", "100000"]]}, 1, 1)
    fair = FairPriceEngine(max_spread_bps=10_000, stale_after_ms=1000).from_orderbook(book, 1)
    risk = RiskKernel(
        market_cfg={"max_spread_bps": 500, "min_depth_20bps_jpy": 0},
        risk_cfg={"block_on_pair_stop_flags": True, "max_abs_skew": 10},
        shock_cfg={"min_activation_to_quote": 0.1},
        amm_cfg={"max_order_size": 1},
    )

    decision = risk.evaluate(
        book=book,
        fair_state=fair,
        shock_state=ShockState(1, 1, 0, 0, 1, 1, None),
        inventory=InventoryState(0.5, 50),
        pair_spec=fallback_btc_jpy_spec(),
        status=BitbankStatus("btc_jpy", "NORMAL", 0.0001),
        now_ms=1,
    )

    assert not decision.allow_quote
    assert decision.side_block_reasons["buy"] == "quote_balance_insufficient"
    assert decision.side_block_reasons["sell"] == "base_balance_insufficient"


def test_max_quote_usage_blocks_buy_only() -> None:
    book = OrderBook("bitbank", "BTC/JPY")
    book.apply_snapshot({"bids": [["99", "100000"]], "asks": [["101", "100000"]]}, 1, 1)
    fair = FairPriceEngine(max_spread_bps=10_000, stale_after_ms=1000).from_orderbook(book, 1)
    risk = RiskKernel(
        market_cfg={"max_spread_bps": 500, "min_depth_20bps_jpy": 0},
        risk_cfg={
            "block_on_pair_stop_flags": True,
            "max_abs_skew": 10,
            "initial_quote_qty": 1000,
            "max_quote_usage_jpy": 100,
        },
        shock_cfg={"min_activation_to_quote": 0.1},
        amm_cfg={"max_order_size": 1},
    )

    decision = risk.evaluate(
        book=book,
        fair_state=fair,
        shock_state=ShockState(1, 1, 0, 0, 1, 1, None),
        inventory=InventoryState(2, 950),
        pair_spec=fallback_btc_jpy_spec(),
        status=BitbankStatus("btc_jpy", "NORMAL", 0.0001),
        now_ms=1,
    )

    assert decision.allow_quote
    assert not decision.allow_buy
    assert decision.allow_sell
    assert decision.side_block_reasons["buy"] == "max_quote_usage_jpy"


def test_one_side_inventory_change_per_minute_blocks_and_expires() -> None:
    book = OrderBook("bitbank", "BTC/JPY")
    book.apply_snapshot({"bids": [["99", "100000"]], "asks": [["101", "100000"]]}, 1, 1)
    fair = FairPriceEngine(max_spread_bps=10_000, stale_after_ms=1000).from_orderbook(book, 1)
    risk = RiskKernel(
        market_cfg={"max_spread_bps": 500, "min_depth_20bps_jpy": 0},
        risk_cfg={
            "block_on_pair_stop_flags": True,
            "max_abs_skew": 10,
            "max_one_side_inventory_change_jpy_per_minute": 150,
        },
        shock_cfg={"min_activation_to_quote": 0.1},
        amm_cfg={"max_order_size": 1},
    )
    risk.record_fill(side="buy", ts_ms=1, price=100, amount=1)

    blocked = risk.evaluate(
        book=book,
        fair_state=fair,
        shock_state=ShockState(1, 1, 0, 0, 1, 1, None),
        inventory=InventoryState(2, 1000),
        pair_spec=fallback_btc_jpy_spec(),
        status=BitbankStatus("btc_jpy", "NORMAL", 0.0001),
        now_ms=2,
    )
    assert blocked.allow_quote
    assert not blocked.allow_buy
    assert blocked.allow_sell
    assert blocked.side_block_reasons["buy"] == "one_side_inventory_change_limit"

    expired = risk.evaluate(
        book=book,
        fair_state=fair,
        shock_state=ShockState(1, 1, 0, 0, 1, 1, None),
        inventory=InventoryState(2, 1000),
        pair_spec=fallback_btc_jpy_spec(),
        status=BitbankStatus("btc_jpy", "NORMAL", 0.0001),
        now_ms=61_002,
    )
    assert expired.allow_buy
    assert expired.allow_sell


def test_fair_drop_blocks_bid_side() -> None:
    book = OrderBook("bitbank", "BTC/JPY")
    book.apply_snapshot({"bids": [["99", "100000"]], "asks": [["101", "100000"]]}, 1, 1)
    risk = RiskKernel(
        market_cfg={"max_spread_bps": 500, "min_depth_20bps_jpy": 0},
        risk_cfg={"block_on_pair_stop_flags": True, "max_abs_skew": 10, "max_fair_drop_bps_1s_for_bid": 30},
        shock_cfg={"min_activation_to_quote": 0.1},
        amm_cfg={"max_order_size": 1},
    )
    base_args = {
        "book": book,
        "shock_state": ShockState(1, 1, 0, 0, 1, 1, None),
        "inventory": InventoryState(10, 10_000),
        "pair_spec": fallback_btc_jpy_spec(),
        "status": BitbankStatus("btc_jpy", "NORMAL", 0.0001),
    }
    risk.evaluate(fair_state=FairPriceState(100, 1, 10, True), now_ms=0, **base_args)

    decision = risk.evaluate(fair_state=FairPriceState(95, 1, 10, True), now_ms=1000, **base_args)

    assert decision.allow_quote
    assert not decision.allow_buy
    assert decision.allow_sell
    assert decision.reason == "fair_drift_too_large"
    assert decision.side_block_reasons["buy"] == "fair_drift_too_large"


def test_fair_rise_blocks_ask_side() -> None:
    book = OrderBook("bitbank", "BTC/JPY")
    book.apply_snapshot({"bids": [["99", "100000"]], "asks": [["101", "100000"]]}, 1, 1)
    risk = RiskKernel(
        market_cfg={"max_spread_bps": 500, "min_depth_20bps_jpy": 0},
        risk_cfg={"block_on_pair_stop_flags": True, "max_abs_skew": 10, "max_fair_rise_bps_1s_for_ask": 30},
        shock_cfg={"min_activation_to_quote": 0.1},
        amm_cfg={"max_order_size": 1},
    )
    base_args = {
        "book": book,
        "shock_state": ShockState(1, 1, 0, 0, 1, 1, None),
        "inventory": InventoryState(10, 10_000),
        "pair_spec": fallback_btc_jpy_spec(),
        "status": BitbankStatus("btc_jpy", "NORMAL", 0.0001),
    }
    risk.evaluate(fair_state=FairPriceState(100, 1, 10, True), now_ms=0, **base_args)

    decision = risk.evaluate(fair_state=FairPriceState(105, 1, 10, True), now_ms=1000, **base_args)

    assert decision.allow_quote
    assert decision.allow_buy
    assert not decision.allow_sell
    assert decision.side_block_reasons["sell"] == "fair_drift_too_large"


def test_fair_drift_5s_window_blocks_bid_side() -> None:
    book = OrderBook("bitbank", "BTC/JPY")
    book.apply_snapshot({"bids": [["99", "100000"]], "asks": [["101", "100000"]]}, 1, 1)
    risk = RiskKernel(
        market_cfg={"max_spread_bps": 500, "min_depth_20bps_jpy": 0},
        risk_cfg={"block_on_pair_stop_flags": True, "max_abs_skew": 10, "max_fair_drop_bps_5s_for_bid": 30},
        shock_cfg={"min_activation_to_quote": 0.1},
        amm_cfg={"max_order_size": 1},
    )
    base_args = {
        "book": book,
        "shock_state": ShockState(1, 1, 0, 0, 1, 1, None),
        "inventory": InventoryState(10, 10_000),
        "pair_spec": fallback_btc_jpy_spec(),
        "status": BitbankStatus("btc_jpy", "NORMAL", 0.0001),
    }
    risk.evaluate(fair_state=FairPriceState(100, 1, 10, True), now_ms=0, **base_args)

    decision = risk.evaluate(fair_state=FairPriceState(95, 1, 10, True), now_ms=5000, **base_args)

    assert not decision.allow_buy
    assert decision.allow_sell
    assert decision.side_block_reasons["buy"] == "fair_drift_too_large"


def test_last_trade_deviation_blocks_all_quotes() -> None:
    book = OrderBook("bitbank", "BTC/JPY")
    book.apply_snapshot({"bids": [["99", "100000"]], "asks": [["101", "100000"]]}, 1, 1)
    risk = RiskKernel(
        market_cfg={"max_spread_bps": 500, "min_depth_20bps_jpy": 0},
        risk_cfg={"block_on_pair_stop_flags": True, "max_abs_skew": 10, "max_last_trade_fair_deviation_bps": 500},
        shock_cfg={"min_activation_to_quote": 0.1},
        amm_cfg={"max_order_size": 1},
    )
    risk.record_trade(price=120, ts_ms=1000)

    decision = risk.evaluate(
        book=book,
        fair_state=FairPriceState(100, 1, 10, True),
        shock_state=ShockState(1, 1, 0, 0, 1, 1, None),
        inventory=InventoryState(10, 10_000),
        pair_spec=fallback_btc_jpy_spec(),
        status=BitbankStatus("btc_jpy", "NORMAL", 0.0001),
        now_ms=1000,
    )

    assert not decision.allow_quote
    assert not decision.allow_buy
    assert not decision.allow_sell
    assert decision.reason == "last_trade_fair_deviation_too_large"


def test_old_last_trade_deviation_is_ignored() -> None:
    book = OrderBook("bitbank", "BTC/JPY")
    book.apply_snapshot({"bids": [["99", "100000"]], "asks": [["101", "100000"]]}, 1, 1)
    risk = RiskKernel(
        market_cfg={"max_spread_bps": 500, "min_depth_20bps_jpy": 0},
        risk_cfg={
            "block_on_pair_stop_flags": True,
            "max_abs_skew": 10,
            "max_last_trade_fair_deviation_bps": 500,
            "last_trade_fair_deviation_max_age_ms": 1000,
        },
        shock_cfg={"min_activation_to_quote": 0.1},
        amm_cfg={"max_order_size": 1},
    )
    risk.record_trade(price=120, ts_ms=1000)

    decision = risk.evaluate(
        book=book,
        fair_state=FairPriceState(100, 1, 10, True),
        shock_state=ShockState(1, 1, 0, 0, 1, 1, None),
        inventory=InventoryState(10, 10_000),
        pair_spec=fallback_btc_jpy_spec(),
        status=BitbankStatus("btc_jpy", "NORMAL", 0.0001),
        now_ms=3001,
    )

    assert decision.allow_quote
    assert decision.allow_buy
    assert decision.allow_sell
