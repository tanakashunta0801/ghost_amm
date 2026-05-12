from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

from ghost_amm.events import Event, make_event
from ghost_amm.market.fair_price import FairPriceState
from ghost_amm.market.orderbook import OrderBook


@dataclass(frozen=True)
class ShockState:
    activation: float
    force_ratio: float
    recent_taker_buy_notional: float
    recent_taker_sell_notional: float
    depth_20bps: float
    last_shock_ts: float | None
    reason: str | None
    direction: str = "neutral"
    bid_activation: float = 0.0
    ask_activation: float = 0.0


class ShockActivator:
    def __init__(
        self,
        *,
        window_ms: float,
        depth_bps: float,
        threshold: float,
        temperature: float,
        minimum_wait_after_shock_ms: float,
        activation_decay_ms: float,
        opposite_side_activation_ratio: float = 0.0,
    ) -> None:
        self.window_ms = window_ms
        self.depth_bps = depth_bps
        self.threshold = threshold
        self.temperature = temperature
        self.minimum_wait_after_shock_ms = minimum_wait_after_shock_ms
        self.activation_decay_ms = activation_decay_ms
        self.opposite_side_activation_ratio = opposite_side_activation_ratio
        self.trades: deque[tuple[float, str, float]] = deque()
        self.last_shock_ts: float | None = None
        self.last_shock_direction = "neutral"
        self.last_state = ShockState(0.0, 0.0, 0.0, 0.0, 0.0, None, "not_initialized")

    @classmethod
    def from_config(cls, cfg: dict) -> "ShockActivator":
        return cls(
            window_ms=float(cfg.get("forced_flow_window_ms", 5000)),
            depth_bps=float(cfg.get("depth_bps", 20)),
            threshold=float(cfg.get("threshold", 1.0)),
            temperature=float(cfg.get("temperature", 1.5)),
            minimum_wait_after_shock_ms=float(cfg.get("minimum_wait_after_shock_ms", 2000)),
            activation_decay_ms=float(cfg.get("activation_decay_ms", 30000)),
            opposite_side_activation_ratio=float(cfg.get("opposite_side_activation_ratio", 0.0)),
        )

    def update(self, event: Event, book: OrderBook, fair_state: FairPriceState) -> tuple[ShockState, Event | None]:
        now = event.ts_exchange
        if event.event_type == "trade":
            notional = float(event.payload["price"]) * float(event.payload["amount"])
            self.trades.append((now, str(event.payload["side"]), notional))
        self._expire(now)
        buy = sum(n for _, side, n in self.trades if side == "buy")
        sell = sum(n for _, side, n in self.trades if side == "sell")
        depth = book.depth_around_mid(self.depth_bps)
        pressure = max(buy, sell)
        force_ratio = pressure / max(depth, 1.0)
        observed_direction = _pressure_direction(buy, sell)
        shock_event = None
        if force_ratio >= self.threshold:
            if self.last_shock_ts is None or now - self.last_shock_ts > self.window_ms:
                shock_event = make_event(
                    "forced_flow",
                    ts_exchange=now,
                    venue=event.venue,
                    symbol=event.symbol,
                    sequence=event.sequence,
                    payload={
                        "force_ratio": force_ratio,
                        "recent_taker_buy_notional": buy,
                        "recent_taker_sell_notional": sell,
                        "depth_20bps": depth,
                        "direction": observed_direction,
                        "inferred": True,
                    },
                )
                self.last_shock_ts = now
                self.last_shock_direction = observed_direction

        activation = 0.0
        direction = "neutral"
        reason = "no_recent_shock"
        if self.last_shock_ts is not None:
            age = now - self.last_shock_ts
            if age < self.minimum_wait_after_shock_ms:
                reason = "waiting_after_shock"
                direction = self.last_shock_direction
            else:
                raw = 1 / (1 + math.exp(-self.temperature * (force_ratio - self.threshold)))
                decay = math.exp(-age / max(self.activation_decay_ms, 1.0))
                activation = max(0.0, min(1.0, raw * decay))
                direction = self.last_shock_direction
                reason = "aftershock_rebuild"
        if not fair_state.is_valid:
            activation = 0.0
            direction = "neutral"
            reason = fair_state.reason or "invalid_fair"
        bid_activation, ask_activation = _side_activations(
            activation,
            direction,
            opposite_ratio=self.opposite_side_activation_ratio,
        )
        self.last_state = ShockState(
            activation=activation,
            force_ratio=force_ratio,
            recent_taker_buy_notional=buy,
            recent_taker_sell_notional=sell,
            depth_20bps=depth,
            last_shock_ts=self.last_shock_ts,
            reason=reason,
            direction=direction,
            bid_activation=bid_activation,
            ask_activation=ask_activation,
        )
        return self.last_state, shock_event

    def _expire(self, now: float) -> None:
        while self.trades and now - self.trades[0][0] > self.window_ms:
            self.trades.popleft()


def _pressure_direction(buy: float, sell: float) -> str:
    if sell > buy:
        return "sell_shock"
    if buy > sell:
        return "buy_shock"
    return "neutral"


def _side_activations(activation: float, direction: str, *, opposite_ratio: float) -> tuple[float, float]:
    opposite = max(0.0, min(1.0, opposite_ratio)) * activation
    if direction == "sell_shock":
        return activation, opposite
    if direction == "buy_shock":
        return opposite, activation
    return 0.0, 0.0
