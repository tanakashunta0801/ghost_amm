from __future__ import annotations

import math
from dataclasses import dataclass

from ghost_amm.exchange.bitbank_rules import BitbankPairSpec


@dataclass(frozen=True)
class Quote:
    side: str
    price: float
    size: float
    level: int
    activation: float
    inventory_skew: float
    fair: float
    shock_event_id: str | None = None
    shock_direction: str = "neutral"
    shock_age_ms: float | None = None


class QuoteSurface:
    def __init__(
        self,
        *,
        levels: int,
        base_order_size: float,
        half_spread_bps: float,
        step_bps: float,
        skew_strength_bps: float,
        size_skew_strength: float,
        min_order_size: float,
        max_order_size: float,
        tick_size: float,
        lot_size: float,
    ) -> None:
        self.levels = levels
        self.base_order_size = base_order_size
        self.half_spread_bps = half_spread_bps
        self.step_bps = step_bps
        self.skew_strength_bps = skew_strength_bps
        self.size_skew_strength = size_skew_strength
        self.min_order_size = min_order_size
        self.max_order_size = max_order_size
        self.tick_size = tick_size
        self.lot_size = lot_size

    @classmethod
    def from_config(cls, cfg: dict, pair_spec: BitbankPairSpec | None = None) -> "QuoteSurface":
        tick_size = pair_spec.tick_size if pair_spec else float(cfg.get("tick_size_fallback_jpy", 1))
        lot_size = pair_spec.lot_size if pair_spec else float(cfg.get("lot_size_fallback_btc", 0.0001))
        min_size = pair_spec.unit_amount if pair_spec else float(cfg.get("min_order_size_fallback", 0.0001))
        return cls(
            levels=int(cfg.get("levels", 6)),
            base_order_size=float(cfg.get("base_order_size", 0.0002)),
            half_spread_bps=float(cfg.get("half_spread_bps", 8)),
            step_bps=float(cfg.get("step_bps", 10)),
            skew_strength_bps=float(cfg.get("skew_strength_bps", 80)),
            size_skew_strength=float(cfg.get("size_skew_strength", 3.0)),
            min_order_size=min_size,
            max_order_size=float(cfg.get("max_order_size", 0.002)),
            tick_size=tick_size,
            lot_size=lot_size,
        )

    def generate(
        self,
        *,
        fair: float,
        inventory_skew: float,
        activation: float,
        bid_activation: float | None = None,
        ask_activation: float | None = None,
        shock_event_id: str | None = None,
        shock_direction: str = "neutral",
        shock_age_ms: float | None = None,
    ) -> list[Quote]:
        bid_activation = activation if bid_activation is None else bid_activation
        ask_activation = activation if ask_activation is None else ask_activation
        if fair <= 0 or (bid_activation <= 0 and ask_activation <= 0):
            return []
        half = self.half_spread_bps / 10_000
        step = self.step_bps / 10_000
        skew = self.skew_strength_bps * inventory_skew / 10_000
        bid_size_base = self.base_order_size * bid_activation * math.exp(-self.size_skew_strength * inventory_skew)
        ask_size_base = self.base_order_size * ask_activation * math.exp(self.size_skew_strength * inventory_skew)
        quotes: list[Quote] = []
        for level in range(self.levels):
            distance = half + level * step
            bid_price = _floor_to_step(fair * math.exp(-(distance + skew)), self.tick_size)
            ask_price = _ceil_to_step(fair * math.exp(distance - skew), self.tick_size)
            bid_size = _floor_quote_size(bid_size_base, min_order_size=self.min_order_size, max_order_size=self.max_order_size, lot_size=self.lot_size)
            ask_size = _floor_quote_size(ask_size_base, min_order_size=self.min_order_size, max_order_size=self.max_order_size, lot_size=self.lot_size)
            if bid_size is not None:
                quotes.append(Quote("buy", bid_price, bid_size, level, bid_activation, inventory_skew, fair, shock_event_id, shock_direction, shock_age_ms))
            if ask_size is not None:
                quotes.append(Quote("sell", ask_price, ask_size, level, ask_activation, inventory_skew, fair, shock_event_id, shock_direction, shock_age_ms))
        return quotes


def _floor_quote_size(value: float, *, min_order_size: float, max_order_size: float, lot_size: float) -> float | None:
    if value < min_order_size:
        return None
    size = _floor_to_step(min(value, max_order_size), lot_size)
    return size if size >= min_order_size else None


def _floor_to_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    decimals = max(0, int(round(-math.log10(step)))) if step < 1 else 0
    return round(math.floor((value + step * 1e-9) / step) * step, decimals)


def _ceil_to_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    decimals = max(0, int(round(-math.log10(step)))) if step < 1 else 0
    return round(math.ceil((value - step * 1e-9) / step) * step, decimals)
