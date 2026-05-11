from ghost_amm.events import make_event
from ghost_amm.recorder.inspection import inspect_recording
from ghost_amm.recorder.jsonl_writer import RotatingJsonlEventWriter


def test_rotating_jsonl_writer_flushes_and_rotates(tmp_path) -> None:
    out = tmp_path / "recording.jsonl"
    with RotatingJsonlEventWriter(out, rotate_every_events=2, flush_every_events=1) as writer:
        for idx in range(5):
            writer.write(make_event("bitbank_ticker", ts_exchange=idx, venue="bitbank", symbol="BTC/JPY", sequence=idx, payload={"last": idx}))
    assert [path.name for path in writer.paths] == ["recording.jsonl", "recording_0001.jsonl", "recording_0002.jsonl"]
    assert sum(1 for path in writer.paths for _ in path.open(encoding="utf-8")) == 5


def test_recording_inspection_requires_metadata_and_market_events(tmp_path) -> None:
    out = tmp_path / "recording.jsonl"
    events = [
        make_event("bitbank_pair_spec", ts_exchange=1, venue="bitbank", symbol="BTC/JPY", payload={"name": "btc_jpy"}),
        make_event("bitbank_status", ts_exchange=2, venue="bitbank", symbol="BTC/JPY", payload={"pair": "btc_jpy", "status": "NORMAL"}),
        make_event("bitbank_ticker", ts_exchange=3, venue="bitbank", symbol="BTC/JPY", payload={"last": 100}),
        make_event("order_book_snapshot", ts_exchange=4, venue="bitbank", symbol="BTC/JPY", sequence=10, payload={"bids": [["99", "1"]], "asks": [["101", "1"]]}),
        make_event("order_book_delta", ts_exchange=5, venue="bitbank", symbol="BTC/JPY", sequence=12, payload={"bids": [["99", "2"]], "asks": []}),
        make_event("trade", ts_exchange=6, venue="bitbank", symbol="BTC/JPY", payload={"side": "buy", "price": 100, "amount": 1}),
    ]
    with RotatingJsonlEventWriter(out) as writer:
        for event in events:
            writer.write(event)
    result = inspect_recording([out])
    assert result.ok_for_replay
    assert result.events == 6
    assert result.sequence_violations == 0


def test_recording_inspection_allows_quiet_period_without_trades_unless_strict(tmp_path) -> None:
    out = tmp_path / "quiet.jsonl"
    events = [
        make_event("bitbank_pair_spec", ts_exchange=1, venue="bitbank", symbol="BTC/JPY", payload={"name": "btc_jpy"}),
        make_event("bitbank_status", ts_exchange=2, venue="bitbank", symbol="BTC/JPY", payload={"pair": "btc_jpy", "status": "NORMAL"}),
        make_event("order_book_snapshot", ts_exchange=3, venue="bitbank", symbol="BTC/JPY", sequence=10, payload={"bids": [["99", "1"]], "asks": [["101", "1"]]}),
        make_event("order_book_delta", ts_exchange=4, venue="bitbank", symbol="BTC/JPY", sequence=11, payload={"bids": [["99", "2"]], "asks": []}),
    ]
    with RotatingJsonlEventWriter(out) as writer:
        for event in events:
            writer.write(event)
    assert inspect_recording([out]).ok_for_replay
    strict = inspect_recording([out], strict=True)
    assert not strict.ok_for_replay
    assert strict.reason == "missing:bitbank_ticker,trade"
