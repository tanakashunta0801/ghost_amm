import json

from ghost_amm.cli import main
from ghost_amm.events import make_event, write_jsonl
from ghost_amm.exchange.bitbank_public import pair_spec_event, status_event
from ghost_amm.exchange.bitbank_rules import BitbankStatus, fallback_btc_jpy_spec


def test_validate_public_recording_writes_inspection_and_replay_report(tmp_path, capsys) -> None:
    recording = tmp_path / "recording.jsonl"
    out = tmp_path / "report"
    write_jsonl(recording, _valid_recording_events())

    code = main(
        [
            "validate-public-recording",
            "--events",
            str(recording),
            "--out",
            str(out),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["ok"] is True
    assert payload["source_events"] == 6
    assert payload["replay_order"] == "arrival_order"
    assert (out / "recording_inspection.json").exists()
    assert (out / "summary.json").exists()
    assert (out / "report.md").exists()
    inspection = json.loads((out / "recording_inspection.json").read_text(encoding="utf-8"))
    assert inspection["ok_for_replay"] is True


def test_validate_public_recording_stops_before_replay_when_strict_inspection_fails(tmp_path, capsys) -> None:
    recording = tmp_path / "quiet.jsonl"
    out = tmp_path / "report"
    write_jsonl(recording, _valid_recording_events(include_ticker=False, include_trade=False))

    code = main(
        [
            "validate-public-recording",
            "--events",
            str(recording),
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
    assert not (out / "summary.json").exists()


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
