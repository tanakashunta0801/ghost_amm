from ghost_amm.config import Config
from ghost_amm.recorder.mock_recorder import generate_synthetic_events
from ghost_amm.replay.engine import ReplayEngine


def test_replay_is_deterministic_and_produces_virtual_fills() -> None:
    events = generate_synthetic_events("sell_shock", "synthetic_bitbank", "btc_jpy")
    first = ReplayEngine(Config()).run(events)
    second = ReplayEngine(Config()).run(events)
    first_projection = [(event.event_type, event.ts_exchange, event.sequence, event.payload) for event in first]
    second_projection = [(event.event_type, event.ts_exchange, event.sequence, event.payload) for event in second]
    assert first_projection == second_projection
    assert any(event.event_type == "virtual_order_placed" for event in first)
    assert any(event.event_type == "virtual_fill" for event in first)
