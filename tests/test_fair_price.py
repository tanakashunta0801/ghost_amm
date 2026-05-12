from ghost_amm.events import make_event
from ghost_amm.config import Config
from ghost_amm.market.fair_price import FairPriceEngine, FairPriceSource
from ghost_amm.market.orderbook import OrderBook
from ghost_amm.replay.engine import ReplayEngine


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


def test_multi_source_median() -> None:
    engine = FairPriceEngine(max_spread_bps=500, stale_after_ms=3000, min_source_count=2, max_source_deviation_bps=250)

    state = engine.from_sources(
        [
            FairPriceSource("book", 100.0, 1000),
            FairPriceSource("ticker", 102.0, 1000),
            FairPriceSource("external", 101.0, 1000),
        ],
        now_ms=1000,
    )

    assert state.is_valid
    assert state.fair == 101.0
    assert state.source_count == 3
    assert state.sources == ["book", "ticker", "external"]
    assert state.deviation_bps is not None


def test_stale_source_is_ignored() -> None:
    engine = FairPriceEngine(max_spread_bps=500, stale_after_ms=3000, min_source_count=1, max_source_age_ms=100)

    state = engine.from_sources(
        [
            FairPriceSource("fresh", 100.0, 1000),
            FairPriceSource("stale", 120.0, 800),
        ],
        now_ms=1000,
    )

    assert state.is_valid
    assert state.fair == 100.0
    assert state.sources == ["fresh"]


def test_deviated_source_is_ignored() -> None:
    engine = FairPriceEngine(max_spread_bps=500, stale_after_ms=3000, min_source_count=2, max_source_deviation_bps=100)

    state = engine.from_sources(
        [
            FairPriceSource("book", 100.0, 1000),
            FairPriceSource("ticker", 101.0, 1000),
            FairPriceSource("bad_external", 150.0, 1000),
        ],
        now_ms=1000,
    )

    assert state.is_valid
    assert state.fair == 100.5
    assert state.sources == ["book", "ticker"]


def test_min_source_count_blocks_quote() -> None:
    book = OrderBook("bitbank", "BTC/JPY")
    book.apply_snapshot({"bids": [["99", "1"]], "asks": [["101", "1"]]}, 1, 1000)
    engine = FairPriceEngine(max_spread_bps=500, stale_after_ms=3000, min_source_count=2)

    state = engine.from_market_event(book, make_event("order_book_snapshot", ts_exchange=1000, venue="bitbank", symbol="BTC/JPY", sequence=1), 1000)

    assert not state.is_valid
    assert state.reason == "insufficient_fair_sources"
    assert state.source_count == 1
    assert state.sources == ["bitbank_orderbook_mid"]


def test_ticker_mid_can_join_book_source() -> None:
    book = OrderBook("bitbank", "BTC/JPY")
    book.apply_snapshot({"bids": [["99", "1"]], "asks": [["101", "1"]]}, 1, 1000)
    engine = FairPriceEngine(max_spread_bps=500, stale_after_ms=3000, min_source_count=2)
    ticker = make_event(
        "bitbank_ticker",
        ts_exchange=1000,
        venue="bitbank",
        symbol="BTC/JPY",
        sequence=2,
        payload={"buy": 99.5, "sell": 100.5, "last": 100.0},
    )

    state = engine.from_market_event(book, ticker, 1000)

    assert state.is_valid
    assert state.fair == 100.0
    assert state.sources == ["bitbank_ticker_mid", "bitbank_orderbook_mid"]


def test_external_btc_usd_jpy_source_can_join_book_source() -> None:
    book = OrderBook("bitbank", "BTC/JPY")
    book.apply_snapshot({"bids": [["7499000", "1"]], "asks": [["7501000", "1"]]}, 1, 1000)
    engine = FairPriceEngine(max_spread_bps=500, stale_after_ms=3000, min_source_count=2)
    external = make_event(
        "external_fair_price",
        ts_exchange=1000,
        venue="ccxt:external",
        symbol="BTC/JPY",
        sequence=2,
        payload={"btc_usd": 50000, "usd_jpy": 150, "source": "external_btc_usd_jpy", "spread_bps": 5},
    )

    state = engine.from_market_event(book, external, 1000)

    assert state.is_valid
    assert state.fair == 7500000
    assert state.source_count == 2
    assert state.sources == ["external_btc_usd_jpy", "bitbank_orderbook_mid"]


def test_deviated_external_source_is_ignored() -> None:
    book = OrderBook("bitbank", "BTC/JPY")
    book.apply_snapshot({"bids": [["7499000", "1"]], "asks": [["7501000", "1"]]}, 1, 1000)
    engine = FairPriceEngine(max_spread_bps=500, stale_after_ms=3000, min_source_count=2, max_source_deviation_bps=100)
    ticker = make_event(
        "bitbank_ticker",
        ts_exchange=1000,
        venue="bitbank",
        symbol="BTC/JPY",
        sequence=2,
        payload={"buy": 7499500, "sell": 7500500, "last": 7500000},
    )
    external = make_event(
        "external_fair_price",
        ts_exchange=1000,
        venue="ccxt:external",
        symbol="BTC/JPY",
        sequence=3,
        payload={"fair_jpy": 8000000, "source": "external_btc_usd_jpy"},
    )

    engine.from_market_event(book, ticker, 1000)
    state = engine.from_market_event(book, external, 1000)

    assert state.is_valid
    assert state.sources == ["bitbank_ticker_mid", "bitbank_orderbook_mid"]
    assert "external_btc_usd_jpy" not in state.sources


def test_malformed_external_source_is_ignored() -> None:
    book = OrderBook("bitbank", "BTC/JPY")
    book.apply_snapshot({"bids": [["7499000", "1"]], "asks": [["7501000", "1"]]}, 1, 1000)
    engine = FairPriceEngine(max_spread_bps=500, stale_after_ms=3000, min_source_count=2)
    external = make_event(
        "external_fair_price",
        ts_exchange=1000,
        venue="ccxt:external",
        symbol="BTC/JPY",
        sequence=2,
        payload={"fair_jpy": "bad", "source": "external_btc_usd_jpy"},
    )

    state = engine.from_market_event(book, external, 1000)

    assert not state.is_valid
    assert state.reason == "insufficient_fair_sources"
    assert state.sources == ["bitbank_orderbook_mid"]


def test_min_source_count_blocks_pipeline_risk_state() -> None:
    event = make_event(
        "order_book_snapshot",
        ts_exchange=1000,
        venue="bitbank",
        symbol="BTC/JPY",
        sequence=1,
        payload={"bids": [["99", "1"]], "asks": [["101", "1"]]},
    )

    output = ReplayEngine(Config({"fair": {"min_source_count": 2}, "market": {"max_spread_bps": 500}})).run([event])
    risk_state = next(item for item in output if item.event_type == "risk_state")

    assert risk_state.payload["reason"] == "insufficient_fair_sources"
    assert risk_state.payload["fair_sources"] == ["bitbank_orderbook_mid"]
    assert risk_state.payload["fair_source_count"] == 1


def test_external_fair_event_keeps_internal_events_on_execution_venue() -> None:
    events = [
        make_event(
            "order_book_snapshot",
            ts_exchange=1000,
            venue="bitbank",
            symbol="BTC/JPY",
            sequence=1,
            payload={"bids": [["7499000", "1"]], "asks": [["7501000", "1"]]},
        ),
        make_event(
            "external_fair_price",
            ts_exchange=1001,
            venue="ccxt:external",
            symbol="BTC/JPY",
            sequence=2,
            payload={"fair_jpy": 7500000, "source": "external_btc_usd_jpy"},
        ),
    ]

    output = ReplayEngine(Config({"fair": {"min_source_count": 2}, "market": {"max_spread_bps": 500}})).run(events)
    mark_prices = [item for item in output if item.event_type == "mark_price"]
    risk_states = [item for item in output if item.event_type == "risk_state"]

    assert mark_prices[-1].venue == "bitbank"
    assert risk_states[-1].venue == "bitbank"
    assert set(risk_states[-1].payload["fair_sources"]) == {"external_btc_usd_jpy", "bitbank_orderbook_mid"}
