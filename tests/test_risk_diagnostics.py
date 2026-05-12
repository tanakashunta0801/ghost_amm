from ghost_amm.analytics.risk_diagnostics import analyze_risk_blocks
from ghost_amm.events import make_event


def test_risk_diagnostics_counts_reasons_and_percentiles() -> None:
    events = [
        make_event(
            "risk_state",
            ts_exchange=1,
            venue="bitbank",
            symbol="BTC/JPY",
            payload={"allow_quote": False, "reason": "activation_too_low", "activation": 0.0, "bid_activation": 0.0, "ask_activation": 0.0, "force_ratio": 0.1, "depth_20bps": 100},
        ),
        make_event(
            "risk_state",
            ts_exchange=2,
            venue="bitbank",
            symbol="BTC/JPY",
            payload={"allow_quote": False, "reason": "activation_too_low", "activation": 0.05, "bid_activation": 0.05, "ask_activation": 0.0, "force_ratio": 0.2, "depth_20bps": 200},
        ),
        make_event(
            "risk_state",
            ts_exchange=3,
            venue="bitbank",
            symbol="BTC/JPY",
            payload={"allow_quote": True, "reason": None, "activation": 0.2, "bid_activation": 0.2, "ask_activation": 0.0, "force_ratio": 0.4, "depth_20bps": 300},
        ),
    ]
    result = analyze_risk_blocks(events)
    assert result.total_risk_events == 3
    assert result.allow_quote_events == 1
    assert result.reason_counts["activation_too_low"] == 2
    assert result.percentiles["activation"]["max"] == 0.2
    assert result.percentiles["bid_activation"]["max"] == 0.2
    assert result.percentiles["ask_activation"]["max"] == 0.0
    assert result.recommendations
