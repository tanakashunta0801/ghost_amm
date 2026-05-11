from ghost_amm.recorder.bitbank_normalizer import normalize_bitbank_message


def test_bitbank_normalizer_unwraps_socketio_message_envelope() -> None:
    events = normalize_bitbank_message(
        "ticker_btc_jpy",
        {
            "room_name": "ticker_btc_jpy",
            "message": {
                "data": {
                    "sell": "12669112",
                    "buy": "12669111",
                    "last": "12669111",
                    "timestamp": 1778509980846,
                }
            },
        },
        ts_local=1778509982198,
    )
    ticker = [event for event in events if event.event_type == "bitbank_ticker"][0]
    assert ticker.payload["buy"] == 12669111
    assert ticker.payload["sell"] == 12669112
    assert ticker.payload["last"] == 12669111
    assert ticker.ts_exchange == 1778509980846


def test_bitbank_normalizer_unwraps_depth_diff_arrays() -> None:
    events = normalize_bitbank_message(
        "depth_diff_btc_jpy",
        {
            "room_name": "depth_diff_btc_jpy",
            "message": {
                "data": {
                    "a": [["12669112", "0.196"]],
                    "b": [["12653001", "0.6158"]],
                    "s": "32059629806",
                    "t": 1778509982561,
                }
            },
        },
        ts_local=1778509982310,
    )
    delta = [event for event in events if event.event_type == "order_book_delta"][0]
    assert delta.payload["asks"] == [["12669112", "0.196"]]
    assert delta.payload["bids"] == [["12653001", "0.6158"]]
    assert delta.sequence == "32059629806"
