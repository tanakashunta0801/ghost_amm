from __future__ import annotations

from dataclasses import dataclass

from ghost_amm.events import Event, make_event
from ghost_amm.market.fair_price import FairPriceState
from ghost_amm.market.orderbook import OrderBook


@dataclass
class TrackedOrder:
    order_id: str
    side: str
    price: float
    remaining_size: float
    created_at: float
    queue_ahead: float
    fair_at_creation: float
    activation: float


class ConservativeQueueFillModel:
    def __init__(self, *, queue_ahead_multiplier: float, maker_fee_bps: float, min_resting_time_ms: float) -> None:
        self.queue_ahead_multiplier = queue_ahead_multiplier
        self.maker_fee_bps = maker_fee_bps
        self.min_resting_time_ms = min_resting_time_ms
        self.orders: dict[str, TrackedOrder] = {}
        self.counter = 0

    @classmethod
    def from_config(cls, cfg: dict) -> "ConservativeQueueFillModel":
        return cls(
            queue_ahead_multiplier=float(cfg.get("queue_ahead_multiplier", 1.5)),
            maker_fee_bps=float(cfg.get("maker_fee_bps_fallback", 0.0)),
            min_resting_time_ms=float(cfg.get("min_resting_time_ms", 500)),
        )

    def on_virtual_order(self, event: Event, book: OrderBook) -> None:
        payload = event.payload
        side = str(payload["side"])
        price = float(payload["price"])
        visible_queue = book.queue_at(side, price)
        queue_ahead = max(visible_queue * self.queue_ahead_multiplier, float(payload["size"]) * self.queue_ahead_multiplier)
        self.orders[str(payload["order_id"])] = TrackedOrder(
            order_id=str(payload["order_id"]),
            side=side,
            price=price,
            remaining_size=float(payload["size"]),
            created_at=float(payload["created_at"]),
            queue_ahead=queue_ahead,
            fair_at_creation=float(payload["fair_price_at_creation"]),
            activation=float(payload["activation"]),
        )

    def on_cancel(self, event: Event) -> None:
        self.orders.pop(str(event.payload["order_id"]), None)

    def on_market_event(self, event: Event, fair_state: FairPriceState) -> list[Event]:
        if event.event_type != "trade":
            return []
        trade_side = str(event.payload["side"])
        trade_price = float(event.payload["price"])
        trade_amount = float(event.payload["amount"])
        fills: list[Event] = []
        for order in list(self.orders.values()):
            if event.ts_exchange - order.created_at < self.min_resting_time_ms:
                continue
            if order.side == "buy" and trade_side == "sell" and trade_price <= order.price:
                fills.extend(self._consume(order, trade_amount, event, fair_state))
            elif order.side == "sell" and trade_side == "buy" and trade_price >= order.price:
                fills.extend(self._consume(order, trade_amount, event, fair_state))
        return fills

    def _consume(self, order: TrackedOrder, trade_amount: float, event: Event, fair_state: FairPriceState) -> list[Event]:
        remaining_flow = trade_amount
        if order.queue_ahead > 0:
            reduction = min(order.queue_ahead, remaining_flow)
            order.queue_ahead -= reduction
            remaining_flow -= reduction
        if order.queue_ahead > 0 or remaining_flow <= 0:
            return []
        fill_size = min(order.remaining_size, remaining_flow)
        if fill_size <= 0:
            return []
        order.remaining_size -= fill_size
        fee = order.price * fill_size * self.maker_fee_bps / 10_000
        self.counter += 1
        fill = make_event(
            "virtual_fill",
            ts_exchange=event.ts_exchange,
            venue=event.venue,
            symbol=event.symbol,
            sequence=f"fill-{self.counter}",
            payload={
                "order_id": order.order_id,
                "side": order.side,
                "fill_price": order.price,
                "fill_size": fill_size,
                "fill_ts": event.ts_exchange,
                "fee": fee,
                "queue_ahead_estimate": order.queue_ahead,
                "fair_at_fill": fair_state.fair,
                "fair_after_1s": None,
                "fair_after_5s": None,
                "fair_after_30s": None,
                "activation": order.activation,
            },
        )
        if order.remaining_size <= 1e-12:
            self.orders.pop(order.order_id, None)
        return [fill]
