from ghost_amm.config import Config
from ghost_amm.events import write_jsonl
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


def test_replay_accepts_rotated_event_files(tmp_path) -> None:
    events = generate_synthetic_events("sell_shock", "synthetic_bitbank", "btc_jpy")
    first_path = tmp_path / "recording.jsonl"
    second_path = tmp_path / "recording_0001.jsonl"
    write_jsonl(first_path, events[:8])
    write_jsonl(second_path, events[8:])
    output = ReplayEngine(Config()).run_files([first_path, second_path], tmp_path / "report")
    assert any(event.event_type == "virtual_order_placed" for event in output)
    assert any(event.event_type == "virtual_fill" for event in output)
