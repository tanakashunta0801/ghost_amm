from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from ghost_amm.market.orderbook import OrderBook


@dataclass(frozen=True)
class FairPriceState:
    fair: float | None
    source_count: int
    spread_bps: float | None
    is_valid: bool
    reason: str | None = None


class FairPriceEngine:
    def __init__(self, *, max_spread_bps: float, stale_after_ms: float) -> None:
        self.max_spread_bps = max_spread_bps
        self.stale_after_ms = stale_after_ms

    def from_orderbook(self, book: OrderBook, now_ms: float) -> FairPriceState:
        if book.stale:
            return FairPriceState(None, 0, None, False, book.stale_reason or "book_stale")
        bid = book.best_bid()
        ask = book.best_ask()
        if bid is None:
            return FairPriceState(None, 0, None, False, "missing_bid")
        if ask is None:
            return FairPriceState(None, 0, None, False, "missing_ask")
        if bid >= ask:
            return FairPriceState(None, 0, None, False, "crossed_or_locked_book")
        if book.last_ts is not None and now_ms - book.last_ts > self.stale_after_ms:
            return FairPriceState(None, 0, None, False, "stale_book_timestamp")
        spread = (ask - bid) / ((ask + bid) / 2) * 10_000
        if spread > self.max_spread_bps:
            return FairPriceState(None, 0, spread, False, "spread_too_wide")
        return FairPriceState((bid + ask) / 2, 1, spread, True, None)


def multi_source_median(states: list[FairPriceState]) -> FairPriceState:
    valid = [state for state in states if state.is_valid and state.fair is not None]
    if not valid:
        return FairPriceState(None, 0, None, False, "no_valid_sources")
    fair = median([state.fair for state in valid if state.fair is not None])
    spreads = [state.spread_bps for state in valid if state.spread_bps is not None]
    return FairPriceState(fair, len(valid), median(spreads) if spreads else None, True, None)
