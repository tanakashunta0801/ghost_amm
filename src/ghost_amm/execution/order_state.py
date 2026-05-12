from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OrderIntent:
    venue: str
    pair: str
    symbol: str
    side: str
    price: float
    amount: float
    order_type: str = "limit"
    post_only: bool = True
    client_order_id: str | None = None
