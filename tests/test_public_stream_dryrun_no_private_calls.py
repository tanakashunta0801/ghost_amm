from dataclasses import asdict

from ghost_amm.config import Config
from ghost_amm.dryrun.public_stream_engine import PublicStreamDryRunEngine
from ghost_amm.events import make_event
from ghost_amm.exchange.bitbank_rules import BitbankStatus, fallback_btc_jpy_spec
from ghost_amm.replay.engine import ReplayEngine


def test_public_stream_dryrun_requires_no_api_keys_and_uses_public_channels() -> None:
    engine = PublicStreamDryRunEngine(config=Config(), pair="btc_jpy", out="data/reports/test", max_events=1)
    assert "transactions_btc_jpy" in engine.channels
    assert "depth_whole_btc_jpy" in engine.channels
    assert "depth_diff_btc_jpy" in engine.channels
    assert engine.config.get("execution.enable_live_orders") is False


def test_public_stream_dryrun_writes_replay_shaped_report(tmp_path) -> None:
    engine = PublicStreamDryRunEngine(config=Config(), pair="btc_jpy", out=tmp_path / "dryrun", max_events=1)
    spec = fallback_btc_jpy_spec()
    source_events = [
        make_event("bitbank_pair_spec", ts_exchange=1, venue="bitbank", symbol="BTC/JPY", payload=asdict(spec)),
        make_event("bitbank_status", ts_exchange=2, venue="bitbank", symbol="BTC/JPY", payload=asdict(BitbankStatus("btc_jpy", "NORMAL", spec.unit_amount))),
        make_event(
            "bitbank_ticker",
            ts_exchange=3,
            venue="bitbank",
            symbol="BTC/JPY",
            payload={"buy": 99, "sell": 101, "last": 100},
            raw_payload={"room_name": "ticker_btc_jpy"},
        ),
        make_event(
            "order_book_snapshot",
            ts_exchange=4,
            venue="bitbank",
            symbol="BTC/JPY",
            sequence=10,
            payload={"bids": [["99", "1"]], "asks": [["101", "1"]]},
            raw_payload={"room_name": "depth_whole_btc_jpy"},
        ),
        make_event(
            "order_book_delta",
            ts_exchange=5,
            venue="bitbank",
            symbol="BTC/JPY",
            sequence=11,
            payload={"bids": [["99", "2"]], "asks": []},
            raw_payload={"room_name": "depth_diff_btc_jpy"},
        ),
        make_event(
            "trade",
            ts_exchange=6,
            venue="bitbank",
            symbol="BTC/JPY",
            payload={"side": "buy", "price": 100, "amount": 1},
            raw_payload={"room_name": "transactions_btc_jpy"},
        ),
    ]
    for event in source_events:
        engine.source_events.append(event)
        engine.events.append(event)
        engine.events.extend(engine.pipeline.process(event))

    engine._write_outputs()

    out = tmp_path / "dryrun"
    assert (out / "events.jsonl").exists()
    assert (out / "source_events.jsonl").exists()
    assert (out / "summary.json").exists()
    assert (out / "report.md").exists()
    assert (out / "fills.csv").exists()
    assert (out / "risk_diagnostics.md").exists()
    assert (out / "recording_inspection.json").exists()

    replayed = ReplayEngine(Config()).run_files([out / "source_events.jsonl"], tmp_path / "replay")
    assert any(event.event_type == "risk_state" for event in replayed)
