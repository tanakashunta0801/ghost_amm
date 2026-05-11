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

    def generate(self, *, fair: float, inventory_skew: float, activation: float) -> list[Quote]:
        if fair <= 0 or activation <= 0:
            return []
        half = self.half_spread_bps / 10_000
        step = self.step_bps / 10_000
        skew = self.skew_strength_bps * inventory_skew / 10_000
        bid_size_base = self.base_order_size * activation * math.exp(-self.size_skew_strength * inventory_skew)
        ask_size_base = self.base_order_size * activation * math.exp(self.size_skew_strength * inventory_skew)
        quotes: list[Quote] = []
        for level in range(self.levels):
            distance = half + level * step
            bid_price = _floor_to_step(fair * math.exp(-(distance + skew)), self.tick_size)
            ask_price = _ceil_to_step(fair * math.exp(distance - skew), self.tick_size)
            bid_size = _floor_to_step(_clamp(bid_size_base, self.min_order_size, self.max_order_size), self.lot_size)
            ask_size = _floor_to_step(_clamp(ask_size_base, self.min_order_size, self.max_order_size), self.lot_size)
            if bid_size >= self.min_order_size:
                quotes.append(Quote("buy", bid_price, bid_size, level, activation, inventory_skew, fair))
            if ask_size >= self.min_order_size:
                quotes.append(Quote("sell", ask_price, ask_size, level, activation, inventory_skew, fair))
        return quotes


def _clamp(value: float, lo: float, hi: float) -> float:
    return min(max(value, lo), hi)


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
