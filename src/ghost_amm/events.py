from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator


Payload = dict[str, Any]


@dataclass(frozen=True)
class Event:
    event_id: str
    ts_exchange: float
    ts_local: float
    venue: str
    symbol: str
    event_type: str
    sequence: int | str | None
    payload: Payload
    raw_payload: Payload | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Event":
        event_type = data.get("event_type", "")
        cls_for_type = EVENT_TYPES.get(event_type, Event)
        return cls_for_type(**data)


class OrderBookSnapshot(Event):
    pass


class OrderBookDelta(Event):
    pass


class TradeEvent(Event):
    pass


class ForcedFlowEvent(Event):
    pass


class BitbankTickerEvent(Event):
    pass


class BitbankStatusEvent(Event):
    pass


class BitbankPairSpecEvent(Event):
    pass


class ExternalFairPriceEvent(Event):
    pass


class BitbankRawEvent(Event):
    pass


class MarkPriceEvent(Event):
    pass


class VirtualOrderPlaced(Event):
    pass


class VirtualOrderCanceled(Event):
    pass


class VirtualFill(Event):
    pass


class LiveOrderIntent(Event):
    pass


class LiveOrderBlocked(Event):
    pass


class DryRunHeartbeat(Event):
    pass


class CcxtRestCallBlocked(Event):
    pass


class RiskStateEvent(Event):
    pass


EVENT_TYPES: dict[str, type[Event]] = {
    "order_book_snapshot": OrderBookSnapshot,
    "order_book_delta": OrderBookDelta,
    "trade": TradeEvent,
    "forced_flow": ForcedFlowEvent,
    "bitbank_ticker": BitbankTickerEvent,
    "bitbank_status": BitbankStatusEvent,
    "bitbank_pair_spec": BitbankPairSpecEvent,
    "external_fair_price": ExternalFairPriceEvent,
    "bitbank_raw": BitbankRawEvent,
    "mark_price": MarkPriceEvent,
    "virtual_order_placed": VirtualOrderPlaced,
    "virtual_order_canceled": VirtualOrderCanceled,
    "virtual_fill": VirtualFill,
    "live_order_intent": LiveOrderIntent,
    "live_order_blocked": LiveOrderBlocked,
    "dry_run_heartbeat": DryRunHeartbeat,
    "ccxt_rest_call_blocked": CcxtRestCallBlocked,
    "risk_state": RiskStateEvent,
}


def now_ms() -> int:
    return int(time.time() * 1000)


def deterministic_event_id(*parts: Any) -> str:
    text = "|".join(json.dumps(part, sort_keys=True, default=str) for part in parts)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


def make_event(
    event_type: str,
    *,
    ts_exchange: float,
    ts_local: float | None = None,
    venue: str,
    symbol: str,
    sequence: int | str | None = None,
    payload: Payload | None = None,
    raw_payload: Payload | None = None,
    event_id: str | None = None,
) -> Event:
    payload = payload or {}
    ts_local = ts_exchange if ts_local is None else ts_local
    event_id = event_id or deterministic_event_id(event_type, ts_exchange, venue, symbol, sequence, payload)
    cls = EVENT_TYPES.get(event_type, Event)
    return cls(
        event_id=event_id,
        ts_exchange=ts_exchange,
        ts_local=ts_local,
        venue=venue,
        symbol=symbol,
        event_type=event_type,
        sequence=sequence,
        payload=payload,
        raw_payload=raw_payload,
    )


def read_jsonl(path: str | Path) -> list[Event]:
    events: list[Event] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                events.append(Event.from_dict(json.loads(line)))
    return events


def iter_jsonl(path: str | Path) -> Iterator[Event]:
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield Event.from_dict(json.loads(line))


def write_jsonl(path: str | Path, events: Iterable[Event]) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        for event in events:
            fh.write(event.to_json())
            fh.write("\n")
