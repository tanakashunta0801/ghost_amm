from ghost_amm.events import make_event
from ghost_amm.market.orderbook import OrderBook


def test_bitbank_orderbook_reconstruction_monotonic_not_consecutive_and_zero_removes() -> None:
    book = OrderBook("bitbank", "BTC/JPY")
    book.apply_event(make_event("order_book_snapshot", ts_exchange=1, venue="bitbank", symbol="BTC/JPY", sequence=10, payload={"bids": [["100", "1"]], "asks": [["101", "1"]]}))
    book.apply_event(make_event("order_book_delta", ts_exchange=2, venue="bitbank", symbol="BTC/JPY", sequence=15, payload={"bids": [["99", "2"], ["100", "0"]], "asks": []}))
    assert not book.stale
    assert 100.0 not in book.bids
    assert book.bids[99.0] == 2
    book.apply_event(make_event("order_book_delta", ts_exchange=3, venue="bitbank", symbol="BTC/JPY", sequence=14, payload={"bids": [], "asks": []}))
    assert book.stale
    assert book.stale_reason == "sequence_not_monotonic"
