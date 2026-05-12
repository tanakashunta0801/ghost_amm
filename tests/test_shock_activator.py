from ghost_amm.events import make_event
from ghost_amm.market.fair_price import FairPriceEngine
from ghost_amm.market.orderbook import OrderBook
from ghost_amm.market.shock import ShockActivator


def _book_and_fair():
    book = OrderBook("bitbank", "BTC/JPY")
    book.apply_snapshot({"bids": [["9990", "10"]], "asks": [["10010", "10"]]}, 1, 1000)
    fair = FairPriceEngine(max_spread_bps=100, stale_after_ms=10_000).from_orderbook(book, 1000)
    return book, fair


def _shock() -> ShockActivator:
    return ShockActivator(
        window_ms=5000,
        depth_bps=20,
        threshold=0.1,
        temperature=2,
        minimum_wait_after_shock_ms=1000,
        activation_decay_ms=30_000,
        opposite_side_activation_ratio=0,
    )


def test_sell_pressure_activates_bid_side() -> None:
    book, fair = _book_and_fair()
    shock = _shock()
    trade = make_event("trade", ts_exchange=1100, venue="bitbank", symbol="BTC/JPY", sequence=2, payload={"side": "sell", "price": 9990, "amount": 10})
    state, forced = shock.update(trade, book, fair)
    assert forced is not None
    assert forced.payload["direction"] == "sell_shock"

    later = make_event("trade", ts_exchange=2300, venue="bitbank", symbol="BTC/JPY", sequence=3, payload={"side": "sell", "price": 9990, "amount": 1})
    state, _ = shock.update(later, book, fair)
    assert state.direction == "sell_shock"
    assert state.bid_activation > 0
    assert state.ask_activation == 0
    assert state.activation == state.bid_activation


def test_buy_pressure_activates_ask_side() -> None:
    book, fair = _book_and_fair()
    shock = _shock()
    trade = make_event("trade", ts_exchange=1100, venue="bitbank", symbol="BTC/JPY", sequence=2, payload={"side": "buy", "price": 10010, "amount": 10})
    state, forced = shock.update(trade, book, fair)
    assert forced is not None
    assert forced.payload["direction"] == "buy_shock"

    later = make_event("trade", ts_exchange=2300, venue="bitbank", symbol="BTC/JPY", sequence=3, payload={"side": "buy", "price": 10010, "amount": 1})
    state, _ = shock.update(later, book, fair)
    assert state.direction == "buy_shock"
    assert state.ask_activation > 0
    assert state.bid_activation == 0
    assert state.activation == state.ask_activation


def test_minimum_wait_after_shock_blocks_immediate_quote() -> None:
    book, fair = _book_and_fair()
    shock = _shock()
    trade = make_event("trade", ts_exchange=1100, venue="bitbank", symbol="BTC/JPY", sequence=2, payload={"side": "sell", "price": 9990, "amount": 10})
    state, _ = shock.update(trade, book, fair)
    assert state.reason == "waiting_after_shock"
    assert state.bid_activation == 0
    assert state.ask_activation == 0


def test_activation_decays() -> None:
    book, fair = _book_and_fair()
    shock = _shock()
    shock.update(make_event("trade", ts_exchange=1100, venue="bitbank", symbol="BTC/JPY", sequence=2, payload={"side": "sell", "price": 9990, "amount": 10}), book, fair)
    early, _ = shock.update(make_event("trade", ts_exchange=2300, venue="bitbank", symbol="BTC/JPY", sequence=3, payload={"side": "sell", "price": 9990, "amount": 1}), book, fair)
    late, _ = shock.update(make_event("trade", ts_exchange=20_000, venue="bitbank", symbol="BTC/JPY", sequence=4, payload={"side": "sell", "price": 9990, "amount": 0.1}), book, fair)

    assert early.bid_activation > late.bid_activation
