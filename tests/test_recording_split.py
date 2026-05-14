import json

from ghost_amm.cli import main
from ghost_amm.events import make_event, read_jsonl, write_jsonl
from ghost_amm.exchange.bitbank_public import pair_spec_event, status_event
from ghost_amm.exchange.bitbank_rules import BitbankStatus, fallback_btc_jpy_spec
from ghost_amm.recorder.inspection import inspect_recording


def test_split_recording_cli_writes_metadata_adjusted_time_splits(tmp_path, capsys) -> None:
    recording = tmp_path / "recording.jsonl"
    out_prefix = tmp_path / "split"
    write_jsonl(recording, _two_period_recording())

    code = main(["split-recording", "--events", str(recording), "--out-prefix", str(out_prefix), "--parts", "2"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["ok"] is True
    assert payload["parts"] == 2
    assert payload["metadata_events"] == 2
    assert len(payload["splits"]) == 2

    first_path = tmp_path / "split_01.jsonl"
    second_path = tmp_path / "split_02.jsonl"
    assert first_path.exists()
    assert second_path.exists()

    first = read_jsonl(first_path)
    second = read_jsonl(second_path)
    assert [event.event_type for event in first[:2]] == ["bitbank_pair_spec", "bitbank_status"]
    assert [event.event_type for event in second[:2]] == ["bitbank_pair_spec", "bitbank_status"]
    assert first[0].ts_exchange < first[2].ts_exchange
    assert second[0].ts_exchange < second[2].ts_exchange
    assert first[0].event_id != second[0].event_id

    first_inspection = inspect_recording([first_path], strict=True)
    second_inspection = inspect_recording([second_path], strict=True)
    assert first_inspection.ok_for_replay
    assert second_inspection.ok_for_replay
    assert first_inspection.sequence_violations == 0
    assert second_inspection.sequence_violations == 0
    assert first_inspection.duration_hours is not None
    assert second_inspection.duration_hours is not None
    assert first_inspection.duration_hours < 1
    assert second_inspection.duration_hours < 1


def test_split_recording_cli_rejects_invalid_part_count(tmp_path, capsys) -> None:
    recording = tmp_path / "recording.jsonl"
    write_jsonl(recording, _two_period_recording())

    code = main(["split-recording", "--events", str(recording), "--out-prefix", str(tmp_path / "split"), "--parts", "1"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload == {"ok": False, "reason": "parts_must_be_at_least_2"}


def _two_period_recording():
    return [
        pair_spec_event(fallback_btc_jpy_spec(), ts_ms=1000),
        status_event(BitbankStatus(pair="btc_jpy", status="NORMAL", min_amount=0.0001), ts_ms=1001),
        make_event("bitbank_ticker", ts_exchange=2000, venue="bitbank", symbol="BTC/JPY", payload={"last": 100}),
        make_event(
            "order_book_snapshot",
            ts_exchange=2001,
            venue="bitbank",
            symbol="BTC/JPY",
            sequence=10,
            payload={"bids": [["99", "1"]], "asks": [["101", "1"]]},
        ),
        make_event(
            "order_book_delta",
            ts_exchange=2002,
            venue="bitbank",
            symbol="BTC/JPY",
            sequence=11,
            payload={"bids": [["99", "2"]], "asks": []},
        ),
        make_event("trade", ts_exchange=2003, venue="bitbank", symbol="BTC/JPY", payload={"side": "buy", "price": 100, "amount": 1}),
        make_event("bitbank_ticker", ts_exchange=5000, venue="bitbank", symbol="BTC/JPY", payload={"last": 101}),
        make_event(
            "order_book_snapshot",
            ts_exchange=5001,
            venue="bitbank",
            symbol="BTC/JPY",
            sequence=20,
            payload={"bids": [["100", "1"]], "asks": [["102", "1"]]},
        ),
        make_event(
            "order_book_delta",
            ts_exchange=5002,
            venue="bitbank",
            symbol="BTC/JPY",
            sequence=21,
            payload={"bids": [["100", "2"]], "asks": []},
        ),
        make_event("trade", ts_exchange=5003, venue="bitbank", symbol="BTC/JPY", payload={"side": "sell", "price": 101, "amount": 1}),
    ]
