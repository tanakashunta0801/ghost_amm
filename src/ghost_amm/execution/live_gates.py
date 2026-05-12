from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from ghost_amm.config import Config
from ghost_amm.events import Event, make_event
from ghost_amm.exchange.bitbank_rules import BitbankPairSpec, BitbankStatus
from ghost_amm.execution.order_state import OrderIntent
from ghost_amm.market.orderbook import OrderBook
from ghost_amm.risk.kernel import RiskDecision


@dataclass(frozen=True)
class LiveGateResult:
    allowed: bool
    reason: str | None


def evaluate_live_order_gates(
    *,
    config: Config,
    intent: OrderIntent,
    pair_spec: BitbankPairSpec | None,
    status: BitbankStatus | None,
    book: OrderBook | None,
    risk: RiskDecision,
    clock_drift_ms: float,
    env: Mapping[str, str] | None = None,
) -> LiveGateResult:
    env = env or os.environ
    if config.get("execution.mode") != "live":
        return LiveGateResult(False, "execution_mode_not_live")
    if config.get("execution.venue") != "bitbank" or intent.venue != "bitbank":
        return LiveGateResult(False, "venue_not_bitbank")
    if not config.get("execution.enable_live_orders", False):
        return LiveGateResult(False, "enable_live_orders_false")
    env_name = str(config.get("execution.live_env_var_name", "GHOST_AMM_ENABLE_LIVE"))
    env_value = str(config.get("execution.live_env_var_value", "I_ACCEPT_RISK"))
    if env.get(env_name) != env_value:
        return LiveGateResult(False, "live_env_var_missing")
    if not env.get("BITBANK_API_KEY") or not env.get("BITBANK_API_SECRET"):
        return LiveGateResult(False, "api_key_or_secret_missing")
    if pair_spec is None:
        return LiveGateResult(False, "pair_metadata_unfetched")
    if status is None or not status.is_normal:
        return LiveGateResult(False, "bitbank_status_not_normal")
    if intent.pair != "btc_jpy" or pair_spec.name != "btc_jpy":
        return LiveGateResult(False, "mvp_pair_must_be_btc_jpy")
    if not pair_spec.is_enabled:
        return LiveGateResult(False, "pair_disabled")
    if pair_spec.stop_order or pair_spec.stop_order_and_cancel:
        return LiveGateResult(False, "pair_order_stopped")
    if intent.side == "buy" and pair_spec.stop_buy_order:
        return LiveGateResult(False, "buy_stopped")
    if intent.side == "sell" and pair_spec.stop_sell_order:
        return LiveGateResult(False, "sell_stopped")
    if abs(clock_drift_ms) > float(config.get("bitbank.clock_drift_limit_ms", 1000)):
        return LiveGateResult(False, "clock_drift_too_high")
    if not risk.allow_quote or (intent.side == "buy" and not risk.allow_buy) or (intent.side == "sell" and not risk.allow_sell):
        return LiveGateResult(False, "risk_kernel_blocked")
    if intent.order_type != "limit" or not intent.post_only:
        return LiveGateResult(False, "order_must_be_post_only_limit")
    if book is not None:
        if intent.side == "buy" and book.best_ask() is not None and intent.price >= float(book.best_ask()):
            return LiveGateResult(False, "post_only_order_would_cross")
        if intent.side == "sell" and book.best_bid() is not None and intent.price <= float(book.best_bid()):
            return LiveGateResult(False, "post_only_order_would_cross")
    ok, reason = pair_spec.validate_order(side=intent.side, price=intent.price, amount=intent.amount)
    if not ok:
        return LiveGateResult(False, reason)
    return LiveGateResult(True, None)


def live_order_blocked_event(intent: OrderIntent, result: LiveGateResult, ts_ms: float) -> Event:
    return make_event(
        "live_order_blocked",
        ts_exchange=ts_ms,
        venue=intent.venue,
        symbol=intent.symbol,
        sequence=None,
        payload={
            "pair": intent.pair,
            "side": intent.side,
            "price": intent.price,
            "amount": intent.amount,
            "order_type": intent.order_type,
            "post_only": intent.post_only,
            "client_order_id": intent.client_order_id,
            "reason": result.reason,
        },
    )
