from ghost_amm.events import make_event
from ghost_amm.market.fair_price import FairPriceEngine
from ghost_amm.market.orderbook import OrderBook
from ghost_amm.market.shock import ShockActivator


def test_activation_waits_after_first_shock_tick() -> None:
    book = OrderBook("bitbank", "BTC/JPY")
    book.apply_snapshot({"bids": [["9990", "10"]], "asks": [["10010", "10"]]}, 1, 1000)
    fair = FairPriceEngine(max_spread_bps=100, stale_after_ms=10_000).from_orderbook(book, 1000)
    shock = ShockActivator(window_ms=5000, depth_bps=20, threshold=0.1, temperature=2, minimum_wait_after_shock_ms=1000, activation_decay_ms=30_000)
    trade = make_event("trade", ts_exchange=1100, venue="bitbank", symbol="BTC/JPY", sequence=2, payload={"side": "sell", "price": 9990, "amount": 10})
    state, forced = shock.update(trade, book, fair)
    assert forced is not None
    assert state.activation == 0
    later = make_event("trade", ts_exchange=2300, venue="bitbank", symbol="BTC/JPY", sequence=3, payload={"side": "sell", "price": 9990, "amount": 10})
    state, _ = shock.update(later, book, fair)
    assert state.activation > 0
