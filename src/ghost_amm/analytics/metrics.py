from __future__ import annotations

from dataclasses import dataclass

from ghost_amm.events import Event


@dataclass(frozen=True)
class MetricsSummary:
    total_pnl: float
    baseline_no_trade_pnl: float
    strategy_alpha_pnl: float
    start_equity: float
    end_equity: float
    baseline_end_equity: float
    realized_pnl: float
    unrealized_pnl: float
    fees_paid: float
    virtual_orders: int
    virtual_fills: int
    fill_rate: float
    average_spread_captured: float | None
    average_adverse_1s: float | None
    average_adverse_5s: float | None
    average_adverse_30s: float | None
    pnl_by_shock_event: float
    pnl_outside_shock_events: float
    max_inventory_skew: float | None
    max_drawdown: float
    worst_fill: float | None
    best_fill: float | None
    risk_blocked_quote_count: int


def summarize(events: list[Event], *, initial_base: float, initial_quote: float, last_fair: float | None) -> MetricsSummary:
    virtual_orders = sum(1 for event in events if event.event_type == "virtual_order_placed")
    fills = [event for event in events if event.event_type == "virtual_fill"]
    fees = sum(float(fill.payload.get("fee", 0)) for fill in fills)
    cash = initial_quote
    base = initial_base
    realized = 0.0
    adverse_1s: list[float] = []
    adverse_5s: list[float] = []
    adverse_30s: list[float] = []
    spread_capture: list[float] = []
    fill_values: list[float] = []
    for fill in fills:
        side = str(fill.payload["side"])
        price = float(fill.payload["fill_price"])
        size = float(fill.payload["fill_size"])
        fee = float(fill.payload.get("fee", 0))
        fair_at_fill = fill.payload.get("fair_at_fill")
        if fair_at_fill:
            if side == "buy":
                spread_capture.append(float(fair_at_fill) - price)
            else:
                spread_capture.append(price - float(fair_at_fill))
        if side == "buy":
            base += size
            cash -= price * size + fee
            realized -= fee
        else:
            base -= size
            cash += price * size - fee
            realized -= fee
        for horizon, bucket in [("fair_after_1s", adverse_1s), ("fair_after_5s", adverse_5s), ("fair_after_30s", adverse_30s)]:
            fair_after = fill.payload.get(horizon)
            if fair_after is None:
                continue
            bucket.append((float(fair_after) - price) if side == "buy" else (price - float(fair_after)))
        value = (last_fair or price) * base + cash
        fill_values.append(value)

    start_fair = _first_fair(events) or last_fair or 0.0
    start_equity = initial_base * start_fair + initial_quote
    end_fair = last_fair or start_fair
    end_equity = base * end_fair + cash
    baseline_end_equity = initial_base * end_fair + initial_quote
    baseline_no_trade_pnl = baseline_end_equity - start_equity
    total_pnl = end_equity - start_equity
    strategy_alpha_pnl = end_equity - baseline_end_equity
    unrealized = total_pnl - realized
    drawdown = _max_drawdown(fill_values)
    risk_blocked = sum(1 for event in events if event.event_type == "risk_state" and not event.payload.get("allow_quote"))
    skews = [event.payload.get("inventory_skew") for event in events if event.event_type == "virtual_order_placed"]
    skews_f = [abs(float(x)) for x in skews if x is not None]
    return MetricsSummary(
        total_pnl=total_pnl,
        baseline_no_trade_pnl=baseline_no_trade_pnl,
        strategy_alpha_pnl=strategy_alpha_pnl,
        start_equity=start_equity,
        end_equity=end_equity,
        baseline_end_equity=baseline_end_equity,
        realized_pnl=realized,
        unrealized_pnl=unrealized,
        fees_paid=fees,
        virtual_orders=virtual_orders,
        virtual_fills=len(fills),
        fill_rate=(len(fills) / virtual_orders) if virtual_orders else 0.0,
        average_spread_captured=_avg(spread_capture),
        average_adverse_1s=_avg(adverse_1s),
        average_adverse_5s=_avg(adverse_5s),
        average_adverse_30s=_avg(adverse_30s),
        pnl_by_shock_event=total_pnl if any(event.event_type == "forced_flow" for event in events) else 0.0,
        pnl_outside_shock_events=0.0 if any(event.event_type == "forced_flow" for event in events) else total_pnl,
        max_inventory_skew=max(skews_f) if skews_f else None,
        max_drawdown=drawdown,
        worst_fill=min(spread_capture) if spread_capture else None,
        best_fill=max(spread_capture) if spread_capture else None,
        risk_blocked_quote_count=risk_blocked,
    )


def _first_fair(events: list[Event]) -> float | None:
    for event in events:
        if event.event_type == "mark_price" and event.payload.get("fair") is not None:
            return float(event.payload["fair"])
    return None


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _max_drawdown(values: list[float]) -> float:
    peak: float | None = None
    drawdown = 0.0
    for value in values:
        peak = value if peak is None else max(peak, value)
        drawdown = max(drawdown, peak - value)
    return drawdown
