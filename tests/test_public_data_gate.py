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
            "--diagnostic-configs",
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
    assert payload["quality_gate_report"] == str(out / "quality_gate.md")
    assert payload["prevent_sleep"]["enabled"] is False
    assert len(payload["replays"]) == 2
    assert len(payload["diagnostic_replays"]) == 1
    assert (out / "01_default" / "summary.json").exists()
    assert (out / "02_default" / "summary.json").exists()
    assert (out / "diagnostic_01_default" / "summary.json").exists()
    quality = json.loads((out / "quality_gate.json").read_text(encoding="utf-8"))
    assert quality["ok"] is False
    assert len(quality["reports"]) == 2
    assert "Status: FAIL" in (out / "quality_gate.md").read_text(encoding="utf-8")
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
    assert payload["prevent_sleep"]["enabled"] is False
    assert (out / "recording_inspection.json").exists()
    assert not (out / "quality_gate.json").exists()
    assert not (out / "01_default" / "summary.json").exists()


def test_run_public_data_gate_can_stop_before_replay_when_recording_is_short(tmp_path, capsys) -> None:
    recording = tmp_path / "recording.jsonl"
    out = tmp_path / "gate"
    write_jsonl(recording, _valid_recording_events())

    code = main(
        [
            "run-public-data-gate",
            "--events",
            str(recording),
            "--configs",
            "configs/default.yaml",
            "--out",
            str(out),
            "--require-min-duration-before-replay",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["ok"] is False
    assert payload["stage"] == "recording_duration"
    assert payload["reason"].startswith("recording_duration_below_min:")
    assert (out / "recording_inspection.json").exists()
    assert not (out / "quality_gate.json").exists()
    assert not (out / "01_default" / "summary.json").exists()


def test_run_public_data_gate_can_write_split_replays(tmp_path, capsys) -> None:
    recording = tmp_path / "recording.jsonl"
    out = tmp_path / "gate"
    config = Path("configs/default.yaml")
    write_jsonl(recording, _valid_split_recording_events())

    code = main(
        [
            "run-public-data-gate",
            "--events",
            str(recording),
            "--configs",
            str(config),
            "--out",
            str(out),
            "--split-parts",
            "2",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["ok"] is False
    assert payload["recording_splits"]["parts"] == 2
    assert len(payload["recording_splits"]["splits"]) == 2
    assert len(payload["split_replays"]) == 2
    assert payload["split_replays"][0]["role"] == "split_sanity"
    assert payload["split_replays"][0]["split_index"] == 1
    assert (out / "recording_splits" / "recording_split_01.jsonl").exists()
    assert (out / "recording_splits" / "recording_split_02.jsonl").exists()
    assert (out / "split_01_01_default" / "summary.json").exists()
    assert (out / "split_02_01_default" / "summary.json").exists()


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


def _valid_split_recording_events():
    events = [
        pair_spec_event(fallback_btc_jpy_spec(), ts_ms=1000),
        status_event(BitbankStatus(pair="btc_jpy", status="NORMAL", min_amount=0.0001), ts_ms=1001),
    ]
    for index, base_ts in enumerate((1002, 11002), start=1):
        events.extend(
            [
                make_event(
                    "bitbank_ticker",
                    ts_exchange=base_ts,
                    venue="bitbank",
                    symbol="BTC/JPY",
                    sequence=index,
                    payload={"buy": 9_999_500, "sell": 10_000_500, "last": 10_000_000},
                    raw_payload={"room_name": "ticker_btc_jpy"},
                ),
                make_event(
                    "order_book_snapshot",
                    ts_exchange=base_ts + 1,
                    venue="bitbank",
                    symbol="BTC/JPY",
                    sequence=100 * index + 10,
                    payload={"bids": [["9999000", "1"]], "asks": [["10001000", "1"]]},
                    raw_payload={"room_name": "depth_whole_btc_jpy"},
                ),
                make_event(
                    "order_book_delta",
                    ts_exchange=base_ts + 2,
                    venue="bitbank",
                    symbol="BTC/JPY",
                    sequence=100 * index + 20,
                    payload={"bids": [["9999000", "1.5"]], "asks": [["10001000", "1.5"]]},
                    raw_payload={"room_name": "depth_diff_btc_jpy"},
                ),
                make_event(
                    "trade",
                    ts_exchange=base_ts + 3,
                    venue="bitbank",
                    symbol="BTC/JPY",
                    sequence=30 + index,
                    payload={"side": "buy", "price": 10_000_000, "amount": 0.01},
                    raw_payload={"room_name": "transactions_btc_jpy"},
                ),
            ]
        )
    return events
