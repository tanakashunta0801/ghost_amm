from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BitbankPairSpec:
    name: str
    base_asset: str
    quote_asset: str
    unit_amount: float
    limit_max_amount: float
    price_digits: int
    amount_digits: int
    maker_fee_rate_base: float = 0.0
    maker_fee_rate_quote: float = 0.0
    taker_fee_rate_base: float = 0.0
    taker_fee_rate_quote: float = 0.0
    is_enabled: bool = True
    stop_order: bool = False
    stop_order_and_cancel: bool = False
    stop_buy_order: bool = False
    stop_sell_order: bool = False

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "BitbankPairSpec":
        return cls(
            name=str(data["name"]),
            base_asset=str(data.get("base_asset", "")),
            quote_asset=str(data.get("quote_asset", "")),
            unit_amount=float(data["unit_amount"]),
            limit_max_amount=float(data["limit_max_amount"]),
            price_digits=int(data["price_digits"]),
            amount_digits=int(data["amount_digits"]),
            maker_fee_rate_base=float(data.get("maker_fee_rate_base") or 0),
            maker_fee_rate_quote=float(data.get("maker_fee_rate_quote") or 0),
            taker_fee_rate_base=float(data.get("taker_fee_rate_base") or 0),
            taker_fee_rate_quote=float(data.get("taker_fee_rate_quote") or 0),
            is_enabled=bool(data.get("is_enabled", False)),
            stop_order=bool(data.get("stop_order", False)),
            stop_order_and_cancel=bool(data.get("stop_order_and_cancel", False)),
            stop_buy_order=bool(data.get("stop_buy_order", False)),
            stop_sell_order=bool(data.get("stop_sell_order", False)),
        )

    @property
    def tick_size(self) -> float:
        return 10.0 ** (-self.price_digits)

    @property
    def lot_size(self) -> float:
        return 10.0 ** (-self.amount_digits)

    @property
    def maker_fee_bps_quote(self) -> float:
        return self.maker_fee_rate_quote * 10_000

    def round_price(self, price: float) -> float:
        return floor_to_step(price, self.tick_size)

    def round_amount(self, amount: float) -> float:
        return floor_to_step(amount, self.lot_size)

    def validate_order(self, *, side: str, price: float, amount: float) -> tuple[bool, str | None]:
        if self.name != "btc_jpy":
            return False, "mvp_pair_must_be_btc_jpy"
        if not self.is_enabled:
            return False, "pair_disabled"
        if self.stop_order or self.stop_order_and_cancel:
            return False, "pair_order_stopped"
        if side == "buy" and self.stop_buy_order:
            return False, "buy_stopped"
        if side == "sell" and self.stop_sell_order:
            return False, "sell_stopped"
        if amount < self.unit_amount:
            return False, "amount_below_unit_amount"
        if amount > self.limit_max_amount:
            return False, "amount_above_limit_max_amount"
        if self.round_amount(amount) != amount:
            return False, "amount_precision_invalid"
        if self.round_price(price) != price:
            return False, "price_precision_invalid"
        return True, None


@dataclass(frozen=True)
class BitbankStatus:
    pair: str
    status: str
    min_amount: float

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "BitbankStatus":
        return cls(pair=str(data["pair"]), status=str(data["status"]), min_amount=float(data.get("min_amount") or 0))

    @property
    def is_normal(self) -> bool:
        return self.status == "NORMAL"


def floor_to_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    scaled = math.floor((value + step * 1e-9) / step) * step
    decimals = max(0, int(round(-math.log10(step)))) if step < 1 else 0
    return round(scaled, decimals)


def fallback_btc_jpy_spec() -> BitbankPairSpec:
    return BitbankPairSpec(
        name="btc_jpy",
        base_asset="btc",
        quote_asset="jpy",
        unit_amount=0.0001,
        limit_max_amount=1000.0,
        price_digits=0,
        amount_digits=4,
        is_enabled=True,
    )
