from __future__ import annotations

from typing import Any

from ghost_amm.events import Event, make_event, now_ms


def normalize_bitbank_message(room_name: str, message: dict[str, Any], *, ts_local: float | None = None) -> list[Event]:
    ts_local = now_ms() if ts_local is None else ts_local
    envelope = message.get("message", message)
    if not isinstance(envelope, dict):
        envelope = message
    data = envelope.get("data", envelope)
    if not isinstance(data, dict):
        data = {}
    pair = _pair_from_room(room_name)
    symbol = pair.upper().replace("_", "/")
    raw = {"room_name": room_name, "message": message}

    raw_event = make_event(
        "bitbank_raw",
        ts_exchange=float(data.get("timestamp") or data.get("t") or ts_local),
        ts_local=ts_local,
        venue="bitbank",
        symbol=symbol,
        sequence=data.get("sequenceId") or data.get("s") or message.get("pid"),
        payload={"room_name": room_name},
        raw_payload=raw,
    )

    if room_name.startswith("ticker_"):
        normalized = make_event(
            "bitbank_ticker",
            ts_exchange=float(data.get("timestamp") or ts_local),
            ts_local=ts_local,
            venue="bitbank",
            symbol=symbol,
            sequence=message.get("pid"),
            payload={
                "sell": _float_or_none(data.get("sell")),
                "buy": _float_or_none(data.get("buy")),
                "last": _float_or_none(data.get("last")),
                "open": _float_or_none(data.get("open")),
                "high": _float_or_none(data.get("high")),
                "low": _float_or_none(data.get("low")),
                "vol": _float_or_none(data.get("vol")),
            },
            raw_payload=raw,
        )
        return [raw_event, normalized]

    if room_name.startswith("transactions_"):
        events = [raw_event]
        for trade in data.get("transactions", []):
            events.append(
                make_event(
                    "trade",
                    ts_exchange=float(trade.get("executed_at") or ts_local),
                    ts_local=ts_local,
                    venue="bitbank",
                    symbol=symbol,
                    sequence=trade.get("transaction_id"),
                    payload={
                        "trade_id": trade.get("transaction_id"),
                        "side": trade.get("side"),
                        "price": float(trade["price"]),
                        "amount": float(trade["amount"]),
                    },
                    raw_payload=raw,
                )
            )
        return events

    if room_name.startswith("depth_whole_"):
        normalized = make_event(
            "order_book_snapshot",
            ts_exchange=float(data.get("timestamp") or ts_local),
            ts_local=ts_local,
            venue="bitbank",
            symbol=symbol,
            sequence=data.get("sequenceId"),
            payload={
                "bids": data.get("bids", []),
                "asks": data.get("asks", []),
                "source": "bitbank_depth_whole",
            },
            raw_payload=raw,
        )
        return [raw_event, normalized]

    if room_name.startswith("depth_diff_"):
        normalized = make_event(
            "order_book_delta",
            ts_exchange=float(data.get("t") or ts_local),
            ts_local=ts_local,
            venue="bitbank",
            symbol=symbol,
            sequence=data.get("s"),
            payload={
                "bids": data.get("b", data.get("bids", [])),
                "asks": data.get("a", data.get("asks", [])),
                "source": "bitbank_depth_diff",
            },
            raw_payload=raw,
        )
        return [raw_event, normalized]

    if room_name.startswith("circuit_break_info_"):
        normalized = make_event(
            "bitbank_status",
            ts_exchange=float(data.get("timestamp") or ts_local),
            ts_local=ts_local,
            venue="bitbank",
            symbol=symbol,
            sequence=message.get("pid"),
            payload={"pair": pair, "circuit_break": data},
            raw_payload=raw,
        )
        return [raw_event, normalized]

    return [raw_event]


def _pair_from_room(room_name: str) -> str:
    for prefix in ["depth_whole_", "depth_diff_", "transactions_", "ticker_", "circuit_break_info_"]:
        if room_name.startswith(prefix):
            return room_name[len(prefix) :]
    return room_name


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)
