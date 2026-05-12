from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

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
    blocked_sides: list[str] = field(default_factory=list)
    cooldown_until_ms: float | None = None
    side_block_reasons: dict[str, str] = field(default_factory=dict)


class RiskKernel:
    def __init__(self, *, market_cfg: dict, risk_cfg: dict, shock_cfg: dict, amm_cfg: dict) -> None:
        self.market_cfg = market_cfg
        self.risk_cfg = risk_cfg
        self.shock_cfg = shock_cfg
        self.amm_cfg = amm_cfg
        self.fill_history: deque[tuple[float, str]] = deque()
        self.inventory_change_history: deque[tuple[float, str, float]] = deque()
        self.fill_burst_cooldown_until: dict[str, float] = {}

    def record_fill(self, *, side: str, ts_ms: float, price: float | None = None, amount: float | None = None) -> None:
        side = str(side)
        if side not in {"buy", "sell"}:
            return
        if price is not None and amount is not None:
            notional = max(0.0, float(price) * float(amount))
            self.inventory_change_history.append((ts_ms, side, notional))
        max_fills = int(self.risk_cfg.get("max_same_side_fills_per_window", 0))
        if max_fills <= 0:
            return
        window_ms = float(self.risk_cfg.get("fill_burst_window_ms", 10_000))
        cooldown_ms = float(self.risk_cfg.get("fill_burst_cooldown_ms", 60_000))
        self.fill_history.append((ts_ms, side))
        self._expire_fill_history(ts_ms, window_ms)
        same_side_count = sum(1 for _, fill_side in self.fill_history if fill_side == side)
        if same_side_count >= max_fills:
            self.fill_burst_cooldown_until[side] = ts_ms + cooldown_ms

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
        fill_burst_blocked = self._fill_burst_blocked_sides(now_ms)
        if "buy" in fill_burst_blocked:
            allow_buy = False
        if "sell" in fill_burst_blocked:
            allow_sell = False
        side_block_reasons = {side: "fill_burst_cooldown" for side in fill_burst_blocked}
        inventory_blocks = self._inventory_blocked_sides(inventory, fair_state.fair, max_size, now_ms)
        for side, reason in inventory_blocks.items():
            side_block_reasons.setdefault(side, reason)
        if "buy" in side_block_reasons:
            allow_buy = False
        if "sell" in side_block_reasons:
            allow_sell = False
        blocked_sides = [side for side in ["buy", "sell"] if side in side_block_reasons]
        reason = side_block_reasons[blocked_sides[0]] if blocked_sides else None
        cooldown_until = max((self.fill_burst_cooldown_until[side] for side in fill_burst_blocked), default=None)
        return RiskDecision(allow_buy or allow_sell, allow_buy, allow_sell, max_size, reason, blocked_sides, cooldown_until, side_block_reasons)

    def _expire_fill_history(self, now_ms: float, window_ms: float) -> None:
        while self.fill_history and now_ms - self.fill_history[0][0] > window_ms:
            self.fill_history.popleft()

    def _fill_burst_blocked_sides(self, now_ms: float) -> list[str]:
        blocked: list[str] = []
        for side in ["buy", "sell"]:
            cooldown_until = self.fill_burst_cooldown_until.get(side)
            if cooldown_until is None:
                continue
            if now_ms < cooldown_until:
                blocked.append(side)
            else:
                self.fill_burst_cooldown_until.pop(side, None)
        return blocked

    def _inventory_blocked_sides(self, inventory: InventoryState, fair: float, max_size: float, now_ms: float) -> dict[str, str]:
        blocked: dict[str, str] = {}
        buy_notional = max_size * fair
        if not self.risk_cfg.get("negative_balances_allowed", False):
            if inventory.quote_qty < buy_notional:
                blocked["buy"] = "quote_balance_insufficient"
            if inventory.base_qty < max_size:
                blocked["sell"] = "base_balance_insufficient"

        max_base = float(self.risk_cfg.get("max_base_qty", 0) or 0)
        if max_base > 0 and inventory.base_qty + max_size > max_base:
            blocked["buy"] = "max_base_qty"

        max_quote_usage = float(self.risk_cfg.get("max_quote_usage_jpy", 0) or 0)
        if max_quote_usage > 0:
            initial_quote = float(self.risk_cfg.get("initial_quote_qty", inventory.quote_qty))
            quote_used = max(0.0, initial_quote - inventory.quote_qty)
            if quote_used + buy_notional > max_quote_usage:
                blocked["buy"] = "max_quote_usage_jpy"

        max_notional = float(self.risk_cfg.get("max_inventory_notional_jpy", 0) or 0)
        if max_notional > 0 and (inventory.base_qty + max_size) * fair > max_notional:
            blocked["buy"] = "max_inventory_notional_jpy"

        max_one_side = float(self.risk_cfg.get("max_one_side_inventory_change_jpy_per_minute", 0) or 0)
        if max_one_side > 0:
            self._expire_inventory_change_history(now_ms)
            recent_by_side = {
                side: sum(notional for _, fill_side, notional in self.inventory_change_history if fill_side == side)
                for side in ["buy", "sell"]
            }
            for side in ["buy", "sell"]:
                if recent_by_side[side] + buy_notional > max_one_side:
                    blocked[side] = "one_side_inventory_change_limit"
        return blocked

    def _expire_inventory_change_history(self, now_ms: float) -> None:
        while self.inventory_change_history and now_ms - self.inventory_change_history[0][0] > 60_000:
            self.inventory_change_history.popleft()
