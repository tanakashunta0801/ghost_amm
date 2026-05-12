import json

import pytest

from ghost_amm.config import Config
from ghost_amm.events import make_event, write_jsonl
from ghost_amm.replay.engine import ReplayEngine


def _trade(tag: str, *, ts_exchange: float, sequence: int):
    return make_event(
        "trade",
        ts_exchange=ts_exchange,
        venue="bitbank",
        symbol="BTC/JPY",
        sequence=sequence,
        payload={"tag": tag, "side": "sell", "price": 100.0, "amount": 1.0},
    )


def _trade_tags(events):
    return [event.payload["tag"] for event in events if event.event_type == "trade"]


def test_replay_preserves_arrival_order_by_default(tmp_path) -> None:
    events = [_trade("arrived_first", ts_exchange=2, sequence=1), _trade("arrived_second", ts_exchange=1, sequence=2)]
    out = tmp_path / "report"
    events_path = tmp_path / "events.jsonl"
    write_jsonl(events_path, events)

    output = ReplayEngine(Config()).run_files([events_path], out)

    assert _trade_tags(output) == ["arrived_first", "arrived_second"]
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["replay_order"] == "arrival_order"
    assert "| replay_order | arrival_order |" in (out / "report.md").read_text(encoding="utf-8")


def test_exchange_time_sort_is_opt_in() -> None:
    events = [_trade("arrived_first", ts_exchange=2, sequence=1), _trade("arrived_second", ts_exchange=1, sequence=2)]

    output = ReplayEngine(Config()).run(events, replay_order="exchange_time_sort", strict_sequence=False)

    assert _trade_tags(output) == ["arrived_second", "arrived_first"]


def test_config_exchange_time_sort_requires_explicit_allow() -> None:
    events = [_trade("arrived_first", ts_exchange=2, sequence=1), _trade("arrived_second", ts_exchange=1, sequence=2)]

    with pytest.raises(ValueError, match="exchange_time_sort"):
        ReplayEngine(Config({"replay": {"order": "exchange_time_sort"}})).run(events)

    output = ReplayEngine(Config({"replay": {"order": "exchange_time_sort", "allow_exchange_time_sort": True}})).run(events, strict_sequence=False)
    assert _trade_tags(output) == ["arrived_second", "arrived_first"]


def test_sequence_violation_is_detected() -> None:
    events = [_trade("seq_two", ts_exchange=1, sequence=2), _trade("seq_one", ts_exchange=2, sequence=1)]

    with pytest.raises(ValueError, match="Sequence violation"):
        ReplayEngine(Config()).run(events)
