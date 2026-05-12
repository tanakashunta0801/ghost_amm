from __future__ import annotations

from dataclasses import asdict

from ghost_amm.amm.inventory import InventoryState
from ghost_amm.amm.projector import OrderProjector
from ghost_amm.amm.quote_surface import QuoteSurface
from ghost_amm.config import Config
from ghost_amm.events import Event, make_event
from ghost_amm.exchange.bitbank_rules import BitbankPairSpec, BitbankStatus
from ghost_amm.execution.live_gates import LiveGateResult, evaluate_live_order_gates, live_order_blocked_event
from ghost_amm.execution.order_state import OrderIntent
from ghost_amm.market.fair_price import FairPriceEngine, FairPriceState
from ghost_amm.market.orderbook import OrderBook
from ghost_amm.market.shock import ShockActivator, ShockState
from ghost_amm.replay.fill_model import ConservativeQueueFillModel
from ghost_amm.risk.kernel import RiskDecision, RiskKernel


class GhostAmmPipeline:
    """Shared replay/dry-run processing path."""

    def __init__(self, config: Config) -> None:
        self.config = config
        symbol = str(config.get("symbol", "BTC/JPY"))
        venue = str(config.get("execution.venue", "bitbank"))
        self.symbol = symbol
        self.venue = venue
        inv_cfg = config.section("inventory")
        self.inventory = InventoryState(
            base_qty=float(inv_cfg.get("initial_base_qty", 0.01)),
            quote_qty=float(inv_cfg.get("initial_quote_qty", 150_000)),
            target_base_ratio=float(inv_cfg.get("target_base_ratio", 0.5)),
            negative_balances_allowed=bool(inv_cfg.get("negative_balances_allowed", False)),
        )
        self.book = OrderBook(venue=venue, symbol=symbol)
        self.fair_engine = FairPriceEngine.from_config(market_cfg=config.section("market"), fair_cfg=config.section("fair"))
        risk_cfg = dict(config.section("risk"))
        risk_cfg["max_abs_skew"] = inv_cfg.get("max_abs_skew", 10)
        risk_cfg["initial_base_qty"] = inv_cfg.get("initial_base_qty", 0.01)
        risk_cfg["initial_quote_qty"] = inv_cfg.get("initial_quote_qty", 150_000)
        risk_cfg["negative_balances_allowed"] = inv_cfg.get("negative_balances_allowed", False)
        self.risk = RiskKernel(
            market_cfg=config.section("market"),
            risk_cfg=risk_cfg,
            shock_cfg=config.section("shock"),
            amm_cfg=config.section("amm"),
        )
        self.shock = ShockActivator.from_config(config.section("shock"))
        self.projector = OrderProjector(
            max_active_orders=int(config.get("execution.max_active_orders_per_pair", 20)),
            ttl_ms=float(config.get("execution.quote_ttl_ms", 3000)),
            min_replace_interval_ms=float(config.get("execution.min_quote_replace_interval_ms", 0)),
            replace_threshold_bps=float(config.get("execution.quote_replace_threshold_bps", 0)),
            size_replace_threshold_ratio=float(config.get("execution.size_replace_threshold_ratio", 0)),
        )
        self.fill_model = ConservativeQueueFillModel.from_config(config.section("fill_model"))
        self.pair_spec: BitbankPairSpec | None = None
        self.status: BitbankStatus | None = None
        self.last_fair = FairPriceState(None, 0, None, False, "not_initialized")
        self.last_shock = ShockState(0.0, 0.0, 0.0, 0.0, 0.0, None, "not_initialized")
        self.last_risk = RiskDecision(False, False, False, 0.0, "not_initialized")

    def process(self, event: Event) -> list[Event]:
        emitted: list[Event] = []
        self._ingest_metadata(event)
        if event.event_type in {"order_book_snapshot", "order_book_delta"}:
            self.book.apply_event(event)
        elif event.event_type == "trade":
            self.risk.record_trade(price=float(event.payload["price"]), ts_ms=event.ts_exchange)

        fair_state = self.fair_engine.from_market_event(self.book, event, event.ts_exchange)
        self.last_fair = fair_state
        if fair_state.fair is not None:
            emitted.append(
                make_event(
                    "mark_price",
                    ts_exchange=event.ts_exchange,
                    venue=self.venue,
                    symbol=self.symbol,
                    sequence=event.sequence,
                    payload=asdict(fair_state),
                )
            )

        shock_state, shock_event = self.shock.update(event, self.book, fair_state)
        self.last_shock = shock_state
        if shock_event:
            emitted.append(shock_event)

        fill_events = self.fill_model.on_market_event(event, fair_state)
        for fill in fill_events:
            self.inventory.apply_fill(
                side=str(fill.payload["side"]),
                price=float(fill.payload["fill_price"]),
                amount=float(fill.payload["fill_size"]),
                fee=float(fill.payload["fee"]),
            )
            self.risk.record_fill(
                side=str(fill.payload["side"]),
                ts_ms=float(fill.payload["fill_ts"]),
                price=float(fill.payload["fill_price"]),
                amount=float(fill.payload["fill_size"]),
            )
            self.projector.remove_filled(str(fill.payload["order_id"]))
            emitted.append(fill)

        risk_decision = self.risk.evaluate(
            book=self.book,
            fair_state=fair_state,
            shock_state=shock_state,
            inventory=self.inventory,
            pair_spec=self.pair_spec,
            status=self.status,
            now_ms=event.ts_exchange,
        )
        self.last_risk = risk_decision
        emitted.append(
            make_event(
                "risk_state",
                ts_exchange=event.ts_exchange,
                venue=self.venue,
                symbol=self.symbol,
                sequence=event.sequence,
                payload=asdict(risk_decision)
                | {
                    "activation": shock_state.activation,
                    "direction": shock_state.direction,
                    "bid_activation": shock_state.bid_activation,
                    "ask_activation": shock_state.ask_activation,
                    "shock_event_id": shock_state.last_shock_event_id,
                    "shock_age_ms": shock_state.shock_age_ms,
                    "force_ratio": shock_state.force_ratio,
                    "recent_taker_buy_notional": shock_state.recent_taker_buy_notional,
                    "recent_taker_sell_notional": shock_state.recent_taker_sell_notional,
                    "depth_20bps": shock_state.depth_20bps,
                    "shock_reason": shock_state.reason,
                    "fair": fair_state.fair,
                    "fair_is_valid": fair_state.is_valid,
                    "fair_reason": fair_state.reason,
                    "fair_sources": fair_state.sources,
                    "fair_source_count": fair_state.source_count,
                    "fair_deviation_bps": fair_state.deviation_bps,
                    "spread_bps": fair_state.spread_bps,
                    "book_spread_bps": self.book.spread_bps(),
                    "book_depth_20bps": self.book.depth_around_mid(20),
                    "book_stale": self.book.stale,
                    "book_stale_reason": self.book.stale_reason,
                    "inventory_skew": self.inventory.skew(fair_state.fair),
                },
            )
        )

        quotes = []
        if fair_state.is_valid and fair_state.fair is not None:
            surface = QuoteSurface.from_config(self.config.section("amm"), self.pair_spec)
            skew = self.inventory.skew(fair_state.fair) or 0.0
            quotes = surface.generate(
                fair=fair_state.fair,
                inventory_skew=skew,
                activation=shock_state.activation,
                bid_activation=shock_state.bid_activation,
                ask_activation=shock_state.ask_activation,
                shock_event_id=shock_state.last_shock_event_id,
                shock_direction=shock_state.direction,
                shock_age_ms=shock_state.shock_age_ms,
            )

        projector_events = self.projector.sync(
            quotes=quotes,
            book=self.book,
            risk=risk_decision,
            now_ms=event.ts_exchange,
            venue=self.venue,
            symbol=self.symbol,
        )
        emitted.extend(projector_events)
        for out in projector_events:
            if out.event_type == "virtual_order_placed":
                self.fill_model.on_virtual_order(out, self.book)
                emitted.extend(self._live_order_observation_events(out, risk_decision))
            elif out.event_type == "virtual_order_canceled":
                self.fill_model.on_cancel(out)
        return emitted

    def _ingest_metadata(self, event: Event) -> None:
        if event.event_type == "bitbank_pair_spec":
            self.pair_spec = BitbankPairSpec.from_api(event.payload)
            if self.config.get("fee.maker_fee_source", "bitbank_pair_spec") == "bitbank_pair_spec":
                self.fill_model.set_maker_fee_bps(_maker_fee_bps_from_pair_spec(self.pair_spec, self.config.section("fee")))
        elif event.event_type == "bitbank_status":
            if "status" in event.payload and "min_amount" in event.payload:
                self.status = BitbankStatus.from_api(event.payload)

    def _live_order_observation_events(self, virtual_order: Event, risk_decision: RiskDecision) -> list[Event]:
        payload = virtual_order.payload
        intent = OrderIntent(
            venue=virtual_order.venue,
            pair=str(self.config.get("pair", "btc_jpy")),
            symbol=virtual_order.symbol,
            side=str(payload["side"]),
            price=float(payload["price"]),
            amount=float(payload["size"]),
            order_type="limit",
            post_only=bool(payload.get("post_only", True)),
            client_order_id=str(payload["order_id"]),
        )
        intent_event = make_event(
            "live_order_intent",
            ts_exchange=virtual_order.ts_exchange,
            venue=intent.venue,
            symbol=intent.symbol,
            payload={
                "pair": intent.pair,
                "side": intent.side,
                "price": intent.price,
                "amount": intent.amount,
                "order_type": intent.order_type,
                "post_only": intent.post_only,
                "client_order_id": intent.client_order_id,
                "source_event_id": virtual_order.event_id,
            },
        )
        result = evaluate_live_order_gates(
            config=self.config,
            intent=intent,
            pair_spec=self.pair_spec,
            status=self.status,
            book=self.book,
            risk=risk_decision,
            clock_drift_ms=0,
        )
        if result.allowed:
            result = LiveGateResult(False, "mvp_live_submission_disabled")
        return [intent_event, live_order_blocked_event(intent, result, virtual_order.ts_exchange)]


def _maker_fee_bps_from_pair_spec(pair_spec: BitbankPairSpec, fee_cfg: dict) -> float:
    maker_fee_bps = pair_spec.maker_fee_bps_quote
    if maker_fee_bps < 0 and fee_cfg.get("negative_maker_fee_policy", "clamp_to_zero") == "clamp_to_zero":
        return 0.0
    return maker_fee_bps
