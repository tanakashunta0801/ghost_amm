from __future__ import annotations

from dataclasses import dataclass

from ghost_amm.amm.inventory import InventoryState
from ghost_amm.exchange.bitbank_rules import BitbankPairSpec, BitbankStatus
from ghost_amm.market.fair_price import FairPriceState
from ghost_amm.market.orderbook import OrderBook
from ghost_amm.market.shock import ShockState


@dataclass(frozen=True)
class RiskDecision:
    allow_quote: bool
    allow_buy: bool
    allow_sell: bool
    max_order_size: float
    reason: str | None = None


class RiskKernel:
    def __init__(self, *, market_cfg: dict, risk_cfg: dict, shock_cfg: dict, amm_cfg: dict) -> None:
        self.market_cfg = market_cfg
        self.risk_cfg = risk_cfg
        self.shock_cfg = shock_cfg
        self.amm_cfg = amm_cfg

    def evaluate(
        self,
        *,
        book: OrderBook,
        fair_state: FairPriceState,
        shock_state: ShockState,
        inventory: InventoryState,
        pair_spec: BitbankPairSpec | None,
        status: BitbankStatus | None,
        now_ms: float,
    ) -> RiskDecision:
        max_size = float(self.amm_cfg.get("max_order_size", 0.0))
        if not fair_state.is_valid or fair_state.fair is None:
            return RiskDecision(False, False, False, 0.0, fair_state.reason or "invalid_fair_price")
        spread = book.spread_bps()
        if spread is None:
            return RiskDecision(False, False, False, 0.0, "missing_spread")
        if spread > float(self.market_cfg.get("max_spread_bps", 50)):
            return RiskDecision(False, False, False, 0.0, "spread_too_wide")
        min_depth = float(self.market_cfg.get("min_depth_20bps_jpy", 0))
        if book.depth_around_mid(20) < min_depth:
            return RiskDecision(False, False, False, 0.0, "book_too_thin")
        if shock_state.activation < float(self.shock_cfg.get("min_activation_to_quote", 0.0)):
            return RiskDecision(False, False, False, 0.0, "activation_too_low")
        snapshot = inventory.snapshot(fair_state.fair)
        skew = snapshot["skew"]
        if skew is None:
            return RiskDecision(False, False, False, 0.0, "invalid_inventory_equity")
        if abs(float(skew)) > float(self.risk_cfg.get("max_abs_skew", self.market_cfg.get("max_abs_skew", 10))):
            return RiskDecision(False, False, False, 0.0, "inventory_too_skewed")
        if self.risk_cfg.get("block_on_unfetched_pair_spec", True) and pair_spec is None:
            return RiskDecision(False, False, False, 0.0, "pair_spec_unfetched")
        if status is not None and self.risk_cfg.get("block_on_bitbank_status_not_normal", True) and not status.is_normal:
            return RiskDecision(False, False, False, 0.0, "bitbank_status_not_normal")
        if pair_spec is not None and self.risk_cfg.get("block_on_pair_stop_flags", True):
            if not pair_spec.is_enabled or pair_spec.stop_order or pair_spec.stop_order_and_cancel:
                return RiskDecision(False, False, False, 0.0, "pair_stop_flag")
        if book.stale and self.risk_cfg.get("block_on_sequence_ordering_violation", True):
            return RiskDecision(False, False, False, 0.0, book.stale_reason or "book_stale")
        allow_buy = not (pair_spec and pair_spec.stop_buy_order)
        allow_sell = not (pair_spec and pair_spec.stop_sell_order)
        return RiskDecision(allow_buy or allow_sell, allow_buy, allow_sell, max_size, None)
