import json
from pathlib import Path

from ghost_amm.recorder.bitbank_normalizer import normalize_bitbank_message


FIXTURES = Path(__file__).parent / "fixtures" / "bitbank_public"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _normalize(name: str):
    payload = _load(name)
    return normalize_bitbank_message(str(payload["room_name"]), payload, ts_local=1778509989999)


def test_ticker_fixture_preserves_raw_and_normalizes_prices() -> None:
    events = _normalize("ticker_btc_jpy.json")

    assert [event.event_type for event in events] == ["bitbank_raw", "bitbank_ticker"]
    ticker = events[1]
    assert ticker.ts_exchange == 1778509980846
    assert ticker.payload["buy"] == 12669111
    assert ticker.payload["sell"] == 12669112
    assert ticker.payload["last"] == 12669111
    assert ticker.raw_payload is not None


def test_transactions_fixture_normalizes_each_trade() -> None:
    events = _normalize("transactions_btc_jpy.json")

    assert events[0].event_type == "bitbank_raw"
    trades = [event for event in events if event.event_type == "trade"]
    assert len(trades) == 2
    assert trades[0].sequence == 32059629801
    assert trades[0].payload["side"] == "buy"
    assert trades[0].payload["price"] == 12669111
    assert trades[0].payload["amount"] == 0.0123
    assert trades[0].ts_exchange == 1778509981000
    assert trades[1].payload["side"] == "sell"


def test_depth_whole_fixture_normalizes_snapshot() -> None:
    events = _normalize("depth_whole_btc_jpy.json")

    snapshot = [event for event in events if event.event_type == "order_book_snapshot"][0]
    assert snapshot.sequence == "32059629805"
    assert snapshot.ts_exchange == 1778509982000
    assert snapshot.payload["bids"] == [["12669111", "0.5"], ["12669110", "1.2"]]
    assert snapshot.payload["asks"] == [["12669112", "0.4"], ["12669113", "0.8"]]
    assert snapshot.payload["source"] == "bitbank_depth_whole"
    assert snapshot.raw_payload is not None


def test_depth_diff_fixture_normalizes_delta() -> None:
    events = _normalize("depth_diff_btc_jpy.json")

    delta = [event for event in events if event.event_type == "order_book_delta"][0]
    assert delta.sequence == "32059629806"
    assert delta.ts_exchange == 1778509982561
    assert delta.payload["asks"] == [["12669112", "0.196"]]
    assert delta.payload["bids"] == [["12653001", "0.6158"]]
    assert delta.payload["source"] == "bitbank_depth_diff"
    assert delta.raw_payload is not None


def test_circuit_break_info_fixture_normalizes_status_event() -> None:
    events = _normalize("circuit_break_info_btc_jpy.json")

    status = [event for event in events if event.event_type == "bitbank_status"][0]
    assert status.ts_exchange == 1778509983000
    assert status.payload["pair"] == "btc_jpy"
    assert status.payload["circuit_break"]["mode"] == "NONE"
    assert status.raw_payload is not None
