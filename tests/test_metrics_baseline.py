from ghost_amm.analytics.metrics import summarize
from ghost_amm.events import make_event


def test_metrics_separates_no_trade_baseline_from_strategy_alpha() -> None:
    events = [
        make_event("mark_price", ts_exchange=1, venue="bitbank", symbol="BTC/JPY", payload={"fair": 100.0}),
        make_event(
            "virtual_fill",
            ts_exchange=2,
            venue="bitbank",
            symbol="BTC/JPY",
            payload={
                "order_id": "o1",
                "side": "buy",
                "fill_price": 90.0,
                "fill_size": 1.0,
                "fee": 0.0,
                "fair_at_fill": 100.0,
            },
        ),
        make_event("mark_price", ts_exchange=3, venue="bitbank", symbol="BTC/JPY", payload={"fair": 110.0}),
    ]
    summary = summarize(events, initial_base=1.0, initial_quote=0.0, last_fair=110.0)
    assert summary.total_pnl == 30.0
    assert summary.baseline_no_trade_pnl == 10.0
    assert summary.strategy_alpha_pnl == 20.0
    assert summary.baseline_end_equity == 110.0
    assert summary.end_equity == 130.0
