from ghost_amm.analytics.metrics import summarize
from ghost_amm.events import make_event


def _placed(order_id: str, ts: float):
    return make_event(
        "virtual_order_placed",
        ts_exchange=ts,
        venue="bitbank",
        symbol="BTC/JPY",
        payload={
            "order_id": order_id,
            "side": "buy",
            "price": 100.0,
            "size": 1.0,
            "created_at": ts,
            "fair_price_at_creation": 101.0,
            "activation": 1.0,
        },
    )


def _cancel(order_id: str, ts: float, reason: str):
    return make_event(
        "virtual_order_canceled",
        ts_exchange=ts,
        venue="bitbank",
        symbol="BTC/JPY",
        payload={"order_id": order_id, "side": "buy", "price": 100.0, "size": 1.0, "reason": reason},
    )


def _fill(order_id: str, ts: float):
    return make_event(
        "virtual_fill",
        ts_exchange=ts,
        venue="bitbank",
        symbol="BTC/JPY",
        payload={
            "order_id": order_id,
            "side": "buy",
            "fill_price": 100.0,
            "fill_size": 1.0,
            "fee": 0.0,
            "fair_at_fill": 101.0,
        },
    )


def test_quote_churn_metrics_count_cancels_replaces_and_active_time() -> None:
    events = [
        make_event("mark_price", ts_exchange=0, venue="bitbank", symbol="BTC/JPY", payload={"fair": 100.0}),
        _placed("o1", 0),
        _cancel("o1", 1000, "replaced"),
        _placed("o2", 2000),
        _fill("o2", 5000),
        _placed("o3", 6000),
        make_event("mark_price", ts_exchange=8000, venue="bitbank", symbol="BTC/JPY", payload={"fair": 100.0}),
    ]

    summary = summarize(events, initial_base=0.0, initial_quote=0.0, last_fair=100.0)

    assert summary.virtual_orders == 3
    assert summary.virtual_cancels == 1
    assert summary.virtual_replaces == 1
    assert summary.virtual_fills == 1
    assert summary.fill_per_placed_order == 1 / 3
    assert summary.average_quote_lifetime_ms == 2000.0
    assert summary.orders_per_minute == 22.5
    assert summary.cancels_per_minute == 7.5
    assert summary.fill_per_active_second == 1 / 6
