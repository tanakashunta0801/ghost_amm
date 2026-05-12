import json
import os

from ghost_amm.cli import main
from ghost_amm.events import make_event, write_jsonl
from ghost_amm.exchange.bitbank_public import pair_spec_event, status_event
from ghost_amm.exchange.bitbank_rules import BitbankStatus, fallback_btc_jpy_spec
from ghost_amm.recorder.status import recording_status


def test_recording_status_reports_healthy_recent_strict_recording(tmp_path) -> None:
    path = tmp_path / "recording.jsonl"
    write_jsonl(path, _strict_recording_events())
    os.utime(path, (1000, 1000))

    result = recording_status([path], strict=True, max_stale_sec=60, now=1010)

    assert result.ok
    assert not result.stale
    assert result.total_bytes > 0
    assert result.latest_write_age_sec == 10
    assert result.inspection is not None
    assert result.inspection["ok_for_replay"] is True


def test_recording_status_fails_stale_recording(tmp_path) -> None:
    path = tmp_path / "recording.jsonl"
    write_jsonl(path, _strict_recording_events())
    os.utime(path, (1000, 1000))

    result = recording_status([path], strict=True, max_stale_sec=60, now=1200)

    assert not result.ok
    assert result.stale
    assert result.reason == "recording_stale:200.0>60"


def test_recording_status_fails_below_min_duration(tmp_path) -> None:
    path = tmp_path / "recording.jsonl"
    write_jsonl(path, _strict_recording_events())
    os.utime(path, (1000, 1000))

    result = recording_status([path], strict=True, max_stale_sec=60, min_duration_hours=24.0, now=1010)

    assert not result.ok
    assert result.duration_hours == 5 / 3_600_000
    assert result.duration_ok is False
    assert result.min_duration_hours == 24.0
    assert result.reason == f"recording_duration_below_min:{5 / 3_600_000}<24.0"


def test_recording_status_requires_inspection_for_min_duration(tmp_path) -> None:
    path = tmp_path / "recording.jsonl"
    write_jsonl(path, _strict_recording_events())
    os.utime(path, (1000, 1000))

    result = recording_status([path], inspect=False, max_stale_sec=60, min_duration_hours=24.0, now=1010)

    assert not result.ok
    assert result.duration_ok is False
    assert result.reason == "inspection_required_for_min_duration"


def test_recording_status_cli_returns_failure_for_missing_file(tmp_path, capsys) -> None:
    missing = tmp_path / "missing.jsonl"

    code = main(["recording-status", str(missing), "--no-inspect"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["ok"] is False
    assert payload["reason"] == f"missing_files:{missing}"


def test_recording_status_cli_checks_min_duration(tmp_path, capsys) -> None:
    path = tmp_path / "recording.jsonl"
    write_jsonl(path, _strict_recording_events())

    code = main(["recording-status", str(path), "--strict", "--min-duration-hours", "24"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["duration_ok"] is False
    assert payload["reason"].startswith("recording_duration_below_min:")


def _strict_recording_events():
    return [
        pair_spec_event(fallback_btc_jpy_spec(), ts_ms=1),
        status_event(BitbankStatus(pair="btc_jpy", status="NORMAL", min_amount=0.0001), ts_ms=2),
        make_event("bitbank_ticker", ts_exchange=3, venue="bitbank", symbol="BTC/JPY", payload={"last": 100}),
        make_event(
            "order_book_snapshot",
            ts_exchange=4,
            venue="bitbank",
            symbol="BTC/JPY",
            sequence=10,
            payload={"bids": [["99", "1"]], "asks": [["101", "1"]]},
        ),
        make_event(
            "order_book_delta",
            ts_exchange=5,
            venue="bitbank",
            symbol="BTC/JPY",
            sequence=11,
            payload={"bids": [["99", "2"]], "asks": []},
        ),
        make_event("trade", ts_exchange=6, venue="bitbank", symbol="BTC/JPY", payload={"side": "buy", "price": 100, "amount": 1}),
    ]
