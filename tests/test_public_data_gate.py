import json
from pathlib import Path

from ghost_amm.cli import main
from ghost_amm.events import make_event, write_jsonl
from ghost_amm.exchange.bitbank_public import pair_spec_event, status_event
from ghost_amm.exchange.bitbank_rules import BitbankStatus, fallback_btc_jpy_spec


def test_run_public_data_gate_writes_inspection_replays_and_quality_gate(tmp_path, capsys) -> None:
    recording = tmp_path / "recording.jsonl"
    recording_rotated = tmp_path / "recording_0001.jsonl"
    out = tmp_path / "gate"
    config = Path("configs/default.yaml")
    events = _valid_recording_events()
    write_jsonl(recording, events[:3])
    write_jsonl(recording_rotated, events[3:])

    code = main(
        [
            "run-public-data-gate",
            "--events",
            str(tmp_path / "recording*.jsonl"),
            "--configs",
            str(config),
            str(config),
            "--out",
            str(out),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["ok"] is False
    assert payload["recording_inspection"] == str(out / "recording_inspection.json")
    assert payload["quality_gate"] == str(out / "quality_gate.json")
    assert len(payload["replays"]) == 2
    assert (out / "01_default" / "summary.json").exists()
    assert (out / "02_default" / "summary.json").exists()
    assert json.loads((out / "quality_gate.json").read_text(encoding="utf-8"))["ok"] is False
    assert any(failure.startswith("recording_duration_below_min:") for failure in payload["quality_failures"])


def test_run_public_data_gate_stops_before_replay_when_inspection_fails(tmp_path, capsys) -> None:
    recording = tmp_path / "quiet.jsonl"
    out = tmp_path / "gate"
    write_jsonl(recording, _valid_recording_events(include_ticker=False, include_trade=False))

    code = main(
        [
            "run-public-data-gate",
            "--events",
            str(recording),
            "--configs",
            "configs/default.yaml",
            "--out",
            str(out),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["ok"] is False
    assert payload["stage"] == "inspect_recording"
    assert payload["reason"] == "missing:bitbank_ticker,trade"
    assert (out / "recording_inspection.json").exists()
    assert not (out / "quality_gate.json").exists()
    assert not (out / "01_default" / "summary.json").exists()


def _valid_recording_events(*, include_ticker: bool = True, include_trade: bool = True):
    events = [
        pair_spec_event(fallback_btc_jpy_spec(), ts_ms=1000),
        status_event(BitbankStatus(pair="btc_jpy", status="NORMAL", min_amount=0.0001), ts_ms=1001),
    ]
    if include_ticker:
        events.append(
            make_event(
                "bitbank_ticker",
                ts_exchange=1002,
                venue="bitbank",
                symbol="BTC/JPY",
                sequence=1,
                payload={"buy": 9_999_500, "sell": 10_000_500, "last": 10_000_000},
                raw_payload={"room_name": "ticker_btc_jpy"},
            )
        )
    events.extend(
        [
            make_event(
                "order_book_snapshot",
                ts_exchange=1003,
                venue="bitbank",
                symbol="BTC/JPY",
                sequence=10,
                payload={"bids": [["9999000", "1"]], "asks": [["10001000", "1"]]},
                raw_payload={"room_name": "depth_whole_btc_jpy"},
            ),
            make_event(
                "order_book_delta",
                ts_exchange=1004,
                venue="bitbank",
                symbol="BTC/JPY",
                sequence=11,
                payload={"bids": [["9999000", "1.5"]], "asks": [["10001000", "1.5"]]},
                raw_payload={"room_name": "depth_diff_btc_jpy"},
            ),
        ]
    )
    if include_trade:
        events.append(
            make_event(
                "trade",
                ts_exchange=1005,
                venue="bitbank",
                symbol="BTC/JPY",
                sequence=1,
                payload={"side": "buy", "price": 10_000_000, "amount": 0.01},
                raw_payload={"room_name": "transactions_btc_jpy"},
            )
        )
    return events
