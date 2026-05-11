from ghost_amm.events import make_event
from ghost_amm.market.fair_price import FairPriceState
from ghost_amm.market.orderbook import OrderBook
from ghost_amm.replay.fill_model import ConservativeQueueFillModel


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
