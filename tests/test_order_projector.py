from ghost_amm.amm.projector import OrderProjector
from ghost_amm.amm.quote_surface import Quote
from ghost_amm.market.orderbook import OrderBook
from ghost_amm.risk.kernel import RiskDecision


def _book() -> OrderBook:
    book = OrderBook("bitbank", "BTC/JPY")
    book.apply_snapshot({"bids": [["99", "10"]], "asks": [["101", "10"]]}, 1, 0)
    return book


def _risk() -> RiskDecision:
    return RiskDecision(True, True, True, 1.0)


def test_projector_keeps_small_quote_changes_until_replace_threshold() -> None:
    projector = OrderProjector(
        max_active_orders=2,
        ttl_ms=30_000,
        min_replace_interval_ms=10_000,
        replace_threshold_bps=5,
        size_replace_threshold_ratio=0.5,
    )
    first = projector.sync(
        quotes=[Quote("buy", 100, 0.1, 0, 0.1, 0, 100.5)],
        book=_book(),
        risk=_risk(),
        now_ms=1_000,
        venue="bitbank",
        symbol="BTC/JPY",
    )
    assert [event.event_type for event in first] == ["virtual_order_placed"]
    second = projector.sync(
        quotes=[Quote("buy", 100.02, 0.11, 0, 0.11, 0, 100.5)],
        book=_book(),
        risk=_risk(),
        now_ms=2_000,
        venue="bitbank",
        symbol="BTC/JPY",
    )
    assert second == []


def test_projector_replaces_after_large_price_move() -> None:
    projector = OrderProjector(max_active_orders=2, ttl_ms=30_000, replace_threshold_bps=5, size_replace_threshold_ratio=0.5)
    projector.sync(
        quotes=[Quote("buy", 100, 0.1, 0, 0.1, 0, 100.5)],
        book=_book(),
        risk=_risk(),
        now_ms=1_000,
        venue="bitbank",
        symbol="BTC/JPY",
    )
    events = projector.sync(
        quotes=[Quote("buy", 99.9, 0.1, 0, 0.1, 0, 100.5)],
        book=_book(),
        risk=_risk(),
        now_ms=12_000,
        venue="bitbank",
        symbol="BTC/JPY",
    )
    assert [event.event_type for event in events] == ["virtual_order_canceled", "virtual_order_placed"]


def test_projector_cancels_if_active_order_would_cross_book() -> None:
    projector = OrderProjector(max_active_orders=2, ttl_ms=30_000, min_replace_interval_ms=10_000)
    projector.sync(
        quotes=[Quote("buy", 100, 0.1, 0, 0.1, 0, 100.5)],
        book=_book(),
        risk=_risk(),
        now_ms=1_000,
        venue="bitbank",
        symbol="BTC/JPY",
    )
    crossed = OrderBook("bitbank", "BTC/JPY")
    crossed.apply_snapshot({"bids": [["98", "10"]], "asks": [["99.5", "10"]]}, 2, 2_000)
    events = projector.sync(
        quotes=[],
        book=crossed,
        risk=_risk(),
        now_ms=2_000,
        venue="bitbank",
        symbol="BTC/JPY",
    )
    assert [event.event_type for event in events] == ["virtual_order_canceled"]
