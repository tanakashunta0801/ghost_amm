from ghost_amm.events import make_event
from ghost_amm.market.fair_price import FairPriceState
from ghost_amm.market.orderbook import OrderBook
from ghost_amm.replay.fill_model import ConservativeQueueFillModel


def _order(order_id: str, side: str, price: float, size: float = 1.0, created_at: float = 0.0):
    return make_event(
        "virtual_order_placed",
        ts_exchange=created_at,
        venue="bitbank",
        symbol="BTC/JPY",
        sequence=order_id,
        payload={
            "order_id": order_id,
            "side": side,
            "price": price,
            "size": size,
            "created_at": created_at,
            "fair_price_at_creation": price,
            "activation": 1,
        },
    )


def _trade(side: str, price: float, amount: float, ts_exchange: float = 1000.0):
    return make_event(
        "trade",
        ts_exchange=ts_exchange,
        venue="bitbank",
        symbol="BTC/JPY",
        sequence=f"{side}-{price}-{amount}-{ts_exchange}",
        payload={"side": side, "price": price, "amount": amount},
    )


def _fair() -> FairPriceState:
    return FairPriceState(101, 1, 1, True)


def test_fill_model_does_not_fill_on_touch_or_insufficient_queue_consumption() -> None:
    book = OrderBook("bitbank", "BTC/JPY")
    book.apply_snapshot({"bids": [["100", "1"]], "asks": [["102", "1"]]}, 1, 0)
    model = ConservativeQueueFillModel(queue_ahead_multiplier=2, maker_fee_bps=0, min_resting_time_ms=500)
    order = make_event("virtual_order_placed", ts_exchange=0, venue="bitbank", symbol="BTC/JPY", sequence=1, payload={"order_id": "o1", "side": "buy", "price": 100, "size": 1, "created_at": 0, "fair_price_at_creation": 101, "activation": 1})
    model.on_virtual_order(order, book)
    delta = make_event("order_book_delta", ts_exchange=1000, venue="bitbank", symbol="BTC/JPY", sequence=2, payload={"bids": [["100", "0"]], "asks": []})
    assert model.on_market_event(delta, FairPriceState(101, 1, 1, True)) == []
    small_trade = make_event("trade", ts_exchange=1000, venue="bitbank", symbol="BTC/JPY", sequence=3, payload={"side": "sell", "price": 100, "amount": 1})
    assert model.on_market_event(small_trade, FairPriceState(101, 1, 1, True)) == []
    big_trade = make_event("trade", ts_exchange=1500, venue="bitbank", symbol="BTC/JPY", sequence=4, payload={"side": "sell", "price": 100, "amount": 2})
    fills = model.on_market_event(big_trade, FairPriceState(101, 1, 1, True))
    assert len(fills) == 1
    assert fills[0].payload["fill_size"] == 1


def test_single_trade_volume_is_shared_across_orders() -> None:
    book = OrderBook("bitbank", "BTC/JPY")
    book.apply_snapshot({"bids": [], "asks": [["102", "1"]]}, 1, 0)
    model = ConservativeQueueFillModel(queue_ahead_multiplier=0, maker_fee_bps=0, min_resting_time_ms=0)
    model.on_virtual_order(_order("o1", "buy", 100, size=1, created_at=0), book)
    model.on_virtual_order(_order("o2", "buy", 100, size=1, created_at=1), book)

    fills = model.on_market_event(_trade("sell", 100, 1.5), _fair())

    assert [fill.payload["order_id"] for fill in fills] == ["o1", "o2"]
    assert sum(float(fill.payload["fill_size"]) for fill in fills) == 1.5
    assert model.orders["o2"].remaining_size == 0.5


def test_queue_ahead_blocks_fill_until_consumed() -> None:
    book = OrderBook("bitbank", "BTC/JPY")
    book.apply_snapshot({"bids": [["100", "2"]], "asks": [["102", "1"]]}, 1, 0)
    model = ConservativeQueueFillModel(queue_ahead_multiplier=1, maker_fee_bps=0, min_resting_time_ms=0)
    model.on_virtual_order(_order("o1", "buy", 100, size=1), book)

    assert model.on_market_event(_trade("sell", 100, 2), _fair()) == []
    fills = model.on_market_event(_trade("sell", 100, 1, ts_exchange=1001), _fair())

    assert len(fills) == 1
    assert fills[0].payload["order_id"] == "o1"
    assert fills[0].payload["fill_size"] == 1


def test_price_priority_for_buy_orders() -> None:
    book = OrderBook("bitbank", "BTC/JPY")
    book.apply_snapshot({"bids": [], "asks": [["103", "1"]]}, 1, 0)
    model = ConservativeQueueFillModel(queue_ahead_multiplier=0, maker_fee_bps=0, min_resting_time_ms=0)
    model.on_virtual_order(_order("low_bid", "buy", 100, created_at=0), book)
    model.on_virtual_order(_order("high_bid", "buy", 101, created_at=1), book)

    fills = model.on_market_event(_trade("sell", 100, 1), _fair())

    assert [fill.payload["order_id"] for fill in fills] == ["high_bid"]
    assert "low_bid" in model.orders


def test_price_priority_for_sell_orders() -> None:
    book = OrderBook("bitbank", "BTC/JPY")
    book.apply_snapshot({"bids": [["99", "1"]], "asks": []}, 1, 0)
    model = ConservativeQueueFillModel(queue_ahead_multiplier=0, maker_fee_bps=0, min_resting_time_ms=0)
    model.on_virtual_order(_order("high_ask", "sell", 102, created_at=0), book)
    model.on_virtual_order(_order("low_ask", "sell", 101, created_at=1), book)

    fills = model.on_market_event(_trade("buy", 102, 1), _fair())

    assert [fill.payload["order_id"] for fill in fills] == ["low_ask"]
    assert "high_ask" in model.orders


def test_min_resting_time_blocks_early_fill() -> None:
    book = OrderBook("bitbank", "BTC/JPY")
    book.apply_snapshot({"bids": [], "asks": [["102", "1"]]}, 1, 0)
    model = ConservativeQueueFillModel(queue_ahead_multiplier=0, maker_fee_bps=0, min_resting_time_ms=500)
    model.on_virtual_order(_order("o1", "buy", 100, created_at=0), book)

    assert model.on_market_event(_trade("sell", 100, 1, ts_exchange=499), _fair()) == []
    fills = model.on_market_event(_trade("sell", 100, 1, ts_exchange=500), _fair())

    assert len(fills) == 1
    assert fills[0].payload["order_id"] == "o1"


def test_maker_fee_is_applied_to_fill_payload() -> None:
    book = OrderBook("bitbank", "BTC/JPY")
    book.apply_snapshot({"bids": [], "asks": [["102", "1"]]}, 1, 0)
    model = ConservativeQueueFillModel(queue_ahead_multiplier=0, maker_fee_bps=10, min_resting_time_ms=0)
    model.on_virtual_order(_order("o1", "buy", 100, size=2), book)

    fills = model.on_market_event(_trade("sell", 100, 2), _fair())

    assert len(fills) == 1
    assert fills[0].payload["fee"] == 0.2
    assert fills[0].payload["fee_asset"] == "quote"
    assert fills[0].payload["maker_fee_bps"] == 10
