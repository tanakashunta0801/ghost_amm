from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ghost_amm.events import Event


@dataclass
class Bbo:
    bid: float | None
    ask: float | None


@dataclass
class OrderBook:
    venue: str
    symbol: str
    bids: dict[float, float] = field(default_factory=dict)
    asks: dict[float, float] = field(default_factory=dict)
    last_sequence: int | None = None
    last_ts: float | None = None
    stale: bool = True
    stale_reason: str | None = "no_snapshot"

    def apply_event(self, event: Event) -> None:
        if event.event_type == "order_book_snapshot":
            self.apply_snapshot(event.payload, event.sequence, event.ts_exchange)
        elif event.event_type == "order_book_delta":
            self.apply_delta(event.payload, event.sequence, event.ts_exchange)

    def apply_snapshot(self, payload: dict[str, Any], sequence: int | str | None, ts: float) -> None:
        self.bids = {float(price): float(amount) for price, amount in payload.get("bids", []) if float(amount) > 0}
        self.asks = {float(price): float(amount) for price, amount in payload.get("asks", []) if float(amount) > 0}
        self.last_sequence = _to_int(sequence)
        self.last_ts = ts
        self.stale = False
        self.stale_reason = None

    def apply_delta(self, payload: dict[str, Any], sequence: int | str | None, ts: float) -> None:
        seq = _to_int(sequence)
        if self.stale:
            return
        if seq is not None and self.last_sequence is not None and seq <= self.last_sequence:
            self.stale = True
            self.stale_reason = "sequence_not_monotonic"
            return
        for price_raw, amount_raw in payload.get("bids", []):
            self._set_level(self.bids, float(price_raw), float(amount_raw))
        for price_raw, amount_raw in payload.get("asks", []):
            self._set_level(self.asks, float(price_raw), float(amount_raw))
        if seq is not None:
            self.last_sequence = seq
        self.last_ts = ts

    def _set_level(self, side: dict[float, float], price: float, amount: float) -> None:
        if amount == 0:
            side.pop(price, None)
        else:
            side[price] = amount

    def best_bid(self) -> float | None:
        return max(self.bids) if self.bids else None

    def best_ask(self) -> float | None:
        return min(self.asks) if self.asks else None

    def bbo(self) -> Bbo:
        return Bbo(self.best_bid(), self.best_ask())

    def mid(self) -> float | None:
        bid = self.best_bid()
        ask = self.best_ask()
        if bid is None or ask is None or bid >= ask:
            return None
        return (bid + ask) / 2

    def spread_bps(self) -> float | None:
        bid = self.best_bid()
        ask = self.best_ask()
        if bid is None or ask is None:
            return None
        mid = (bid + ask) / 2
        if mid <= 0:
            return None
        return (ask - bid) / mid * 10_000

    def depth_around_mid(self, bps: float) -> float:
        mid = self.mid()
        if mid is None:
            return 0.0
        bid_floor = mid * (1 - bps / 10_000)
        ask_ceiling = mid * (1 + bps / 10_000)
        bid_notional = sum(price * amount for price, amount in self.bids.items() if price >= bid_floor)
        ask_notional = sum(price * amount for price, amount in self.asks.items() if price <= ask_ceiling)
        return bid_notional + ask_notional

    def queue_at(self, side: str, price: float) -> float:
        book = self.bids if side == "buy" else self.asks
        return book.get(price, 0.0)


def _to_int(value: int | str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
