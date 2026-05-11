from __future__ import annotations

from ghost_amm.config import Config
from ghost_amm.events import Event, now_ms
from ghost_amm.exchange.bitbank_rules import BitbankPairSpec, BitbankStatus
from ghost_amm.execution.live_gates import evaluate_live_order_gates, live_order_blocked_event
from ghost_amm.execution.order_state import OrderIntent
from ghost_amm.market.orderbook import OrderBook
from ghost_amm.risk.kernel import RiskDecision


class BitbankPrivateClient:
    """Post-MVP interface. MVP never submits real private REST orders."""

    def __init__(self, config: Config) -> None:
        self.config = config

    def create_spot_limit_order(
        self,
        *,
        intent: OrderIntent,
        pair_spec: BitbankPairSpec | None,
        status: BitbankStatus | None,
        book: OrderBook | None,
        risk: RiskDecision,
        clock_drift_ms: float = 0.0,
    ) -> Event:
        result = evaluate_live_order_gates(
            config=self.config,
            intent=intent,
            pair_spec=pair_spec,
            status=status,
            book=book,
            risk=risk,
            clock_drift_ms=clock_drift_ms,
        )
        return live_order_blocked_event(intent, result, now_ms())

    def fetch_assets(self) -> Event:
        raise RuntimeError("bitbank private asset reads are post-MVP and disabled")

    def fetch_active_orders(self) -> Event:
        raise RuntimeError("bitbank private order reads are post-MVP and disabled")

    def cancel_order(self) -> Event:
        raise RuntimeError("bitbank private cancels are post-MVP and disabled")
