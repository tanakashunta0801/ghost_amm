from __future__ import annotations

from dataclasses import dataclass


@dataclass
class InventoryState:
    base_qty: float
    quote_qty: float
    target_base_ratio: float = 0.5
    negative_balances_allowed: bool = False

    def snapshot(self, fair: float | None) -> dict[str, float | None]:
        if fair is None or fair <= 0:
            return {
                "base_qty": self.base_qty,
                "quote_qty": self.quote_qty,
                "equity": None,
                "base_ratio": None,
                "skew": None,
            }
        equity = self.base_qty * fair + self.quote_qty
        if equity <= 0:
            return {
                "base_qty": self.base_qty,
                "quote_qty": self.quote_qty,
                "equity": equity,
                "base_ratio": None,
                "skew": None,
            }
        base_ratio = self.base_qty * fair / equity
        return {
            "base_qty": self.base_qty,
            "quote_qty": self.quote_qty,
            "equity": equity,
            "base_ratio": base_ratio,
            "skew": base_ratio - self.target_base_ratio,
        }

    def skew(self, fair: float | None) -> float | None:
        value = self.snapshot(fair)["skew"]
        return float(value) if value is not None else None

    def apply_fill(self, *, side: str, price: float, amount: float, fee: float) -> None:
        if side == "buy":
            self.base_qty += amount
            self.quote_qty -= price * amount + fee
        elif side == "sell":
            self.base_qty -= amount
            self.quote_qty += price * amount - fee
        else:
            raise ValueError(f"unknown fill side: {side}")
        if not self.negative_balances_allowed and (self.base_qty < -1e-12 or self.quote_qty < -1e-6):
            raise ValueError("negative balances are disabled")
