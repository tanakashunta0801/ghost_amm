from ghost_amm.events import make_event
from ghost_amm.market.fair_price import FairPriceEngine
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


def test_stale_book_ignores_deltas_until_snapshot_restores() -> None:
    book = OrderBook("bitbank", "BTC/JPY")
    book.apply_event(make_event("order_book_snapshot", ts_exchange=1, venue="bitbank", symbol="BTC/JPY", sequence=10, payload={"bids": [["100", "1"]], "asks": [["101", "1"]]}))
    book.apply_event(make_event("order_book_delta", ts_exchange=2, venue="bitbank", symbol="BTC/JPY", sequence=9, payload={"bids": [["99", "3"]], "asks": []}))
    assert book.stale

    book.apply_event(make_event("order_book_delta", ts_exchange=3, venue="bitbank", symbol="BTC/JPY", sequence=11, payload={"bids": [["99", "3"]], "asks": []}))
    assert 99.0 not in book.bids

    book.apply_event(make_event("order_book_snapshot", ts_exchange=4, venue="bitbank", symbol="BTC/JPY", sequence=20, payload={"bids": [["98", "2"]], "asks": [["102", "2"]]}))
    assert not book.stale
    assert book.mid() == 100


def test_stale_book_blocks_fair_until_snapshot_restores() -> None:
    book = OrderBook("bitbank", "BTC/JPY")
    fair = FairPriceEngine(max_spread_bps=500, stale_after_ms=3000)
    book.apply_event(make_event("order_book_snapshot", ts_exchange=1, venue="bitbank", symbol="BTC/JPY", sequence=10, payload={"bids": [["100", "1"]], "asks": [["102", "1"]]}))
    book.apply_event(make_event("order_book_delta", ts_exchange=2, venue="bitbank", symbol="BTC/JPY", sequence=9, payload={"bids": [], "asks": []}))

    state = fair.from_orderbook(book, 2)
    assert not state.is_valid
    assert state.reason == "sequence_not_monotonic"

    book.apply_event(make_event("order_book_snapshot", ts_exchange=3, venue="bitbank", symbol="BTC/JPY", sequence=20, payload={"bids": [["100", "1"]], "asks": [["102", "1"]]}))
    state = fair.from_orderbook(book, 3)
    assert state.is_valid


def test_depth_around_mid_uses_expected_price_band() -> None:
    book = OrderBook("bitbank", "BTC/JPY")
    book.apply_event(
        make_event(
            "order_book_snapshot",
            ts_exchange=1,
            venue="bitbank",
            symbol="BTC/JPY",
            sequence=1,
            payload={"bids": [["99", "2"], ["98", "5"]], "asks": [["101", "3"], ["102", "7"]]},
        )
    )

    assert book.depth_around_mid(150) == 99 * 2 + 101 * 3
