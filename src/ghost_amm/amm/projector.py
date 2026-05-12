from __future__ import annotations

from dataclasses import dataclass

from ghost_amm.amm.quote_surface import Quote
from ghost_amm.events import Event, make_event
from ghost_amm.market.orderbook import OrderBook
from ghost_amm.risk.kernel import RiskDecision


@dataclass
class ActiveVirtualOrder:
    order_id: str
    side: str
    price: float
    size: float
    level: int
    created_at: float
    expires_at: float
    activation: float
    inventory_skew: float
    fair_price_at_creation: float
    shock_event_id: str | None = None
    shock_direction: str = "neutral"
    shock_age_ms: float | None = None


class OrderProjector:
    def __init__(
        self,
        *,
        max_active_orders: int = 20,
        ttl_ms: float = 3000,
        min_replace_interval_ms: float = 0,
        replace_threshold_bps: float = 0,
        size_replace_threshold_ratio: float = 0,
    ) -> None:
        self.max_active_orders = max_active_orders
        self.ttl_ms = ttl_ms
        self.min_replace_interval_ms = min_replace_interval_ms
        self.replace_threshold_bps = replace_threshold_bps
        self.size_replace_threshold_ratio = size_replace_threshold_ratio
        self.active: dict[str, ActiveVirtualOrder] = {}
        self.counter = 0

    def sync(
        self,
        *,
        quotes: list[Quote],
        book: OrderBook,
        risk: RiskDecision,
        now_ms: float,
        venue: str,
        symbol: str,
    ) -> list[Event]:
        if not risk.allow_quote:
            return self.cancel_all(now_ms, venue, symbol, risk.reason or "risk_block")
        desired = [q for q in quotes if self._post_only_safe(q, book, risk)]
        desired = desired[: self.max_active_orders]
        desired_keys = {_key(q) for q in desired}
        events: list[Event] = []
        for key, order in list(self.active.items()):
            if key not in desired_keys or now_ms >= order.expires_at or not self._active_post_only_safe(order, book, risk):
                events.append(self._cancel_event(order, now_ms, venue, symbol, "stale_or_replaced"))
                del self.active[key]
        for quote in desired:
            key = _key(quote)
            existing = self.active.get(key)
            if existing and self._should_keep_existing(existing, quote, now_ms):
                continue
            if existing:
                events.append(self._cancel_event(existing, now_ms, venue, symbol, "replaced"))
                del self.active[key]
            self.counter += 1
            order_id = f"v-{int(now_ms)}-{self.counter:06d}"
            order = ActiveVirtualOrder(
                order_id=order_id,
                side=quote.side,
                price=quote.price,
                size=quote.size,
                level=quote.level,
                created_at=now_ms,
                expires_at=now_ms + self.ttl_ms,
                activation=quote.activation,
                inventory_skew=quote.inventory_skew,
                fair_price_at_creation=quote.fair,
                shock_event_id=quote.shock_event_id,
                shock_direction=quote.shock_direction,
                shock_age_ms=quote.shock_age_ms,
            )
            self.active[key] = order
            events.append(
                make_event(
                    "virtual_order_placed",
                    ts_exchange=now_ms,
                    venue=venue,
                    symbol=symbol,
                    sequence=self.counter,
                    payload={
                        "order_id": order.order_id,
                        "side": order.side,
                        "price": order.price,
                        "size": order.size,
                        "post_only": True,
                        "created_at": order.created_at,
                        "expires_at": order.expires_at,
                        "reason": "ghost_amm_quote",
                        "quote_level": order.level,
                        "activation": order.activation,
                        "shock_event_id": order.shock_event_id,
                        "shock_direction": order.shock_direction,
                        "shock_age_ms": order.shock_age_ms,
                        "inventory_skew": order.inventory_skew,
                        "fair_price_at_creation": order.fair_price_at_creation,
                    },
                )
            )
        return events

    def remove_filled(self, order_id: str) -> None:
        for key, order in list(self.active.items()):
            if order.order_id == order_id:
                del self.active[key]
                return

    def cancel_all(self, now_ms: float, venue: str, symbol: str, reason: str) -> list[Event]:
        events = [self._cancel_event(order, now_ms, venue, symbol, reason) for order in self.active.values()]
        self.active.clear()
        return events

    def _post_only_safe(self, quote: Quote, book: OrderBook, risk: RiskDecision) -> bool:
        if quote.side == "buy":
            ask = book.best_ask()
            return risk.allow_buy and ask is not None and quote.price < ask
        bid = book.best_bid()
        return risk.allow_sell and bid is not None and quote.price > bid

    def _active_post_only_safe(self, order: ActiveVirtualOrder, book: OrderBook, risk: RiskDecision) -> bool:
        if order.side == "buy":
            ask = book.best_ask()
            return risk.allow_buy and ask is not None and order.price < ask
        bid = book.best_bid()
        return risk.allow_sell and bid is not None and order.price > bid

    def _should_keep_existing(self, order: ActiveVirtualOrder, quote: Quote, now_ms: float) -> bool:
        if now_ms >= order.expires_at:
            return False
        if order.price == quote.price and order.size == quote.size:
            return True
        if now_ms - order.created_at < self.min_replace_interval_ms:
            return True
        price_bps = abs(quote.price - order.price) / max(order.price, 1e-12) * 10_000
        size_ratio = abs(quote.size - order.size) / max(order.size, 1e-12)
        return price_bps <= self.replace_threshold_bps and size_ratio <= self.size_replace_threshold_ratio

    def _cancel_event(self, order: ActiveVirtualOrder, now_ms: float, venue: str, symbol: str, reason: str) -> Event:
        self.counter += 1
        return make_event(
            "virtual_order_canceled",
            ts_exchange=now_ms,
            venue=venue,
            symbol=symbol,
            sequence=self.counter,
            payload={"order_id": order.order_id, "reason": reason, "side": order.side, "price": order.price, "size": order.size},
        )


def _key(quote: Quote) -> str:
    return f"{quote.side}:{quote.level}"
