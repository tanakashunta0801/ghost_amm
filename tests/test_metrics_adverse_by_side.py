from ghost_amm.analytics.metrics import summarize
from ghost_amm.events import make_event


def _fill(order_id: str, side: str, price: float, fair_after_1s: float, fair_after_5s: float, fair_after_30s: float):
    return make_event(
        "virtual_fill",
        ts_exchange=1,
        venue="bitbank",
        symbol="BTC/JPY",
        payload={
            "order_id": order_id,
            "side": side,
            "fill_price": price,
            "fill_size": 1.0,
            "fee": 0.0,
            "fair_at_fill": price,
            "fair_after_1s": fair_after_1s,
            "fair_after_5s": fair_after_5s,
            "fair_after_30s": fair_after_30s,
        },
    )


def test_adverse_selection_is_split_by_side() -> None:
    events = [
        make_event("mark_price", ts_exchange=0, venue="bitbank", symbol="BTC/JPY", payload={"fair": 100.0}),
        _fill("buy_good", "buy", 100.0, fair_after_1s=101.0, fair_after_5s=102.0, fair_after_30s=103.0),
        _fill("sell_good", "sell", 110.0, fair_after_1s=109.0, fair_after_5s=108.0, fair_after_30s=107.0),
        _fill("buy_bad", "buy", 100.0, fair_after_1s=99.0, fair_after_5s=98.0, fair_after_30s=97.0),
    ]

    summary = summarize(events, initial_base=0.0, initial_quote=0.0, last_fair=100.0)

    assert summary.average_adverse_1s_buy == 0.0
    assert summary.average_adverse_5s_buy == 0.0
    assert summary.average_adverse_30s_buy == 0.0
    assert summary.average_adverse_1s_sell == 1.0
    assert summary.average_adverse_5s_sell == 2.0
    assert summary.average_adverse_30s_sell == 3.0
    assert summary.worst_adverse_buy == -3.0
    assert summary.worst_adverse_sell == 1.0
