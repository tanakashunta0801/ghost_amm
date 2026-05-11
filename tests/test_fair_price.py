from ghost_amm.market.fair_price import FairPriceEngine
from ghost_amm.market.orderbook import OrderBook


def test_fair_price_mid_and_invalid_crossed_book() -> None:
    book = OrderBook("bitbank", "BTC/JPY")
    book.apply_snapshot({"bids": [["99", "1"]], "asks": [["101", "1"]]}, 1, 1000)
    state = FairPriceEngine(max_spread_bps=500, stale_after_ms=3000).from_orderbook(book, 1000)
    assert state.is_valid
    assert state.fair == 100

    book.apply_snapshot({"bids": [["101", "1"]], "asks": [["101", "1"]]}, 2, 1001)
    state = FairPriceEngine(max_spread_bps=500, stale_after_ms=3000).from_orderbook(book, 1001)
    assert not state.is_valid
    assert state.reason == "crossed_or_locked_book"
