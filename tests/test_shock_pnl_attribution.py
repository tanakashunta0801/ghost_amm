from ghost_amm.analytics.metrics import summarize
from ghost_amm.config import Config
from ghost_amm.recorder.mock_recorder import generate_synthetic_events
from ghost_amm.replay.engine import ReplayEngine


def test_forced_flow_event_id_is_carried_to_fills_and_summary() -> None:
    events = generate_synthetic_events("sell_shock", "synthetic_bitbank", "btc_jpy")
    engine = ReplayEngine(Config())
    output = engine.run(events)
    forced = [event for event in output if event.event_type == "forced_flow"]
    fills = [event for event in output if event.event_type == "virtual_fill"]

    assert forced
    assert fills
    shock_id = forced[0].event_id
    assert all(fill.payload["shock_event_id"] == shock_id for fill in fills)
    assert all(fill.payload["shock_direction"] == "sell_shock" for fill in fills)
    assert all(fill.payload["shock_age_ms"] is not None and fill.payload["shock_age_ms"] >= 0 for fill in fills)

    summary = summarize(
        output,
        initial_base=0.01,
        initial_quote=150_000,
        last_fair=engine.pipeline.last_fair.fair,
    )

    assert summary.shock_event_fill_count == len(fills)
    assert summary.shock_fill_count_by_event[shock_id] == len(fills)
    assert summary.shock_direction_by_event[shock_id] == "sell_shock"
    assert shock_id in summary.shock_total_spread_capture_by_event
    assert shock_id in summary.shock_average_adverse_5s_by_event
