from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

from ghost_amm.events import Event
from ghost_amm.market.orderbook import OrderBook


@dataclass(frozen=True)
class FairPriceSource:
    name: str
    fair: float
    ts_ms: float
    spread_bps: float | None = None
    confidence: float = 1.0


@dataclass(frozen=True)
class FairPriceState:
    fair: float | None
    source_count: int
    spread_bps: float | None
    is_valid: bool
    reason: str | None = None
    sources: list[str] = field(default_factory=list)
    deviation_bps: float | None = None


class FairPriceEngine:
    def __init__(
        self,
        *,
        max_spread_bps: float,
        stale_after_ms: float,
        min_source_count: int = 1,
        max_source_age_ms: float | None = None,
        max_source_deviation_bps: float = 80,
        use_median: bool = True,
    ) -> None:
        self.max_spread_bps = max_spread_bps
        self.stale_after_ms = stale_after_ms
        self.min_source_count = min_source_count
        self.max_source_age_ms = stale_after_ms if max_source_age_ms is None else max_source_age_ms
        self.max_source_deviation_bps = max_source_deviation_bps
        self.use_median = use_median
        self.sources: dict[str, FairPriceSource] = {}

    @classmethod
    def from_config(cls, *, market_cfg: dict, fair_cfg: dict) -> "FairPriceEngine":
        return cls(
            max_spread_bps=float(market_cfg.get("max_spread_bps", 50)),
            stale_after_ms=float(market_cfg.get("stale_after_ms", 3000)),
            min_source_count=int(fair_cfg.get("min_source_count", 1)),
            max_source_age_ms=float(fair_cfg.get("max_source_age_ms", market_cfg.get("stale_after_ms", 3000))),
            max_source_deviation_bps=float(fair_cfg.get("max_source_deviation_bps", 80)),
            use_median=bool(fair_cfg.get("use_median", True)),
        )

    def from_market_event(self, book: OrderBook, event: Event, now_ms: float) -> FairPriceState:
        if event.event_type == "bitbank_ticker":
            ticker_source = _source_from_ticker(event)
            if ticker_source is not None:
                self.sources[ticker_source.name] = ticker_source
        elif event.event_type == "external_fair_price":
            external_source = _source_from_external_fair(event)
            if external_source is not None:
                self.sources[external_source.name] = external_source
        book_source = self._source_from_orderbook(book, now_ms)
        if book_source is not None:
            self.sources[book_source.name] = book_source
        else:
            self.sources.pop("bitbank_orderbook_mid", None)
        return self.from_sources(list(self.sources.values()), now_ms=now_ms)

    def from_orderbook(self, book: OrderBook, now_ms: float) -> FairPriceState:
        source = self._source_from_orderbook(book, now_ms)
        if source is None:
            return _invalid_orderbook_state(book, self.max_spread_bps, self.stale_after_ms, now_ms)
        return FairPriceState(
            source.fair,
            1,
            source.spread_bps,
            True,
            None,
            sources=[source.name],
            deviation_bps=0.0,
        )

    def from_sources(self, sources: list[FairPriceSource], *, now_ms: float) -> FairPriceState:
        fresh = [source for source in sources if now_ms - source.ts_ms <= self.max_source_age_ms]
        if not fresh:
            return FairPriceState(None, 0, None, False, "no_fresh_fair_sources")
        reference = median([source.fair for source in fresh])
        filtered = [source for source in fresh if _deviation_bps(source.fair, reference) <= self.max_source_deviation_bps]
        if len(filtered) < self.min_source_count:
            return FairPriceState(
                None,
                len(filtered),
                _median_optional([source.spread_bps for source in filtered]),
                False,
                "insufficient_fair_sources",
                sources=[source.name for source in filtered],
                deviation_bps=_max_deviation(filtered, reference),
            )
        fair = median([source.fair for source in filtered]) if self.use_median else sum(source.fair for source in filtered) / len(filtered)
        return FairPriceState(
            fair,
            len(filtered),
            _median_optional([source.spread_bps for source in filtered]),
            True,
            None,
            sources=[source.name for source in filtered],
            deviation_bps=_max_deviation(filtered, fair),
        )

    def _source_from_orderbook(self, book: OrderBook, now_ms: float) -> FairPriceSource | None:
        if book.stale:
            return None
        bid = book.best_bid()
        ask = book.best_ask()
        if bid is None or ask is None or bid >= ask:
            return None
        if book.last_ts is not None and now_ms - book.last_ts > self.stale_after_ms:
            return None
        spread = (ask - bid) / ((ask + bid) / 2) * 10_000
        if spread > self.max_spread_bps:
            return None
        return FairPriceSource("bitbank_orderbook_mid", (bid + ask) / 2, book.last_ts or now_ms, spread)


def multi_source_median(states: list[FairPriceState]) -> FairPriceState:
    valid = [state for state in states if state.is_valid and state.fair is not None]
    if not valid:
        return FairPriceState(None, 0, None, False, "no_valid_sources")
    fair = median([state.fair for state in valid if state.fair is not None])
    spreads = [state.spread_bps for state in valid if state.spread_bps is not None]
    sources = [source for state in valid for source in state.sources]
    return FairPriceState(fair, len(valid), median(spreads) if spreads else None, True, None, sources=sources, deviation_bps=_max_state_deviation(valid, fair))


def _invalid_orderbook_state(book: OrderBook, max_spread_bps: float, stale_after_ms: float, now_ms: float) -> FairPriceState:
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
    if book.last_ts is not None and now_ms - book.last_ts > stale_after_ms:
        return FairPriceState(None, 0, None, False, "stale_book_timestamp")
    spread = (ask - bid) / ((ask + bid) / 2) * 10_000
    if spread > max_spread_bps:
        return FairPriceState(None, 0, spread, False, "spread_too_wide")
    return FairPriceState(None, 0, spread, False, "invalid_orderbook")


def _source_from_ticker(event: Event) -> FairPriceSource | None:
    buy = event.payload.get("buy")
    sell = event.payload.get("sell")
    last = event.payload.get("last")
    if buy is not None and sell is not None:
        bid = float(buy)
        ask = float(sell)
        if bid > 0 and ask > 0 and bid < ask:
            mid = (bid + ask) / 2
            spread = (ask - bid) / mid * 10_000
            return FairPriceSource("bitbank_ticker_mid", mid, event.ts_exchange, spread)
    if last is not None and float(last) > 0:
        return FairPriceSource("bitbank_ticker_last", float(last), event.ts_exchange, None, 0.5)
    return None


def _source_from_external_fair(event: Event) -> FairPriceSource | None:
    fair = _external_fair_jpy(event.payload)
    if fair is None:
        return None
    source_name = str(event.payload.get("source") or "external_btc_usd_jpy")
    spread = event.payload.get("spread_bps")
    confidence = event.payload.get("confidence", 0.8)
    return FairPriceSource(
        source_name,
        fair,
        float(event.payload.get("ts_ms", event.ts_exchange)),
        float(spread) if spread is not None else None,
        float(confidence),
    )


def _external_fair_jpy(payload: dict) -> float | None:
    direct = _positive_payload_float(payload.get("fair_jpy", payload.get("fair")))
    if direct is not None:
        return direct
    btc_usd = _positive_payload_float(payload.get("btc_usd", payload.get("btc_price")))
    usd_jpy = _positive_payload_float(payload.get("usd_jpy", payload.get("fx_rate_jpy")))
    if btc_usd is None or usd_jpy is None:
        return None
    fair = btc_usd * usd_jpy
    return fair if fair > 0 else None


def _positive_payload_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _median_optional(values: list[float | None]) -> float | None:
    filtered = [value for value in values if value is not None]
    return median(filtered) if filtered else None


def _deviation_bps(value: float, reference: float) -> float:
    if reference <= 0:
        return 0.0
    return abs(value - reference) / reference * 10_000


def _max_deviation(sources: list[FairPriceSource], fair: float) -> float | None:
    if not sources:
        return None
    return max(_deviation_bps(source.fair, fair) for source in sources)


def _max_state_deviation(states: list[FairPriceState], fair: float) -> float | None:
    prices = [state.fair for state in states if state.fair is not None]
    if not prices:
        return None
    return max(_deviation_bps(price, fair) for price in prices)
