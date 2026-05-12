from __future__ import annotations

from collections import Counter, defaultdict
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
    virtual_cancels: int
    virtual_replaces: int
    virtual_fills: int
    fill_rate: float
    fill_per_placed_order: float
    average_quote_lifetime_ms: float | None
    orders_per_minute: float
    cancels_per_minute: float
    fill_per_active_second: float
    average_spread_captured: float | None
    average_adverse_1s: float | None
    average_adverse_5s: float | None
    average_adverse_30s: float | None
    average_adverse_1s_buy: float | None
    average_adverse_1s_sell: float | None
    average_adverse_5s_buy: float | None
    average_adverse_5s_sell: float | None
    average_adverse_30s_buy: float | None
    average_adverse_30s_sell: float | None
    worst_adverse_buy: float | None
    worst_adverse_sell: float | None
    shock_event_fill_count: int
    shock_fill_count_by_event: dict[str, int]
    shock_direction_by_event: dict[str, str]
    shock_total_spread_capture_by_event: dict[str, float]
    shock_average_adverse_5s_by_event: dict[str, float | None]
    pnl_by_shock_event: float
    pnl_outside_shock_events: float
    max_inventory_skew: float | None
    max_drawdown: float
    worst_fill: float | None
    best_fill: float | None
    risk_blocked_quote_count: int


def summarize(events: list[Event], *, initial_base: float, initial_quote: float, last_fair: float | None) -> MetricsSummary:
    virtual_orders = sum(1 for event in events if event.event_type == "virtual_order_placed")
    virtual_cancels = sum(1 for event in events if event.event_type == "virtual_order_canceled")
    virtual_replaces = sum(1 for event in events if event.event_type == "virtual_order_canceled" and event.payload.get("reason") == "replaced")
    fills = [event for event in events if event.event_type == "virtual_fill"]
    fees = sum(float(fill.payload.get("fee", 0)) for fill in fills)
    cash = initial_quote
    base = initial_base
    realized = 0.0
    adverse_1s: list[float] = []
    adverse_5s: list[float] = []
    adverse_30s: list[float] = []
    adverse_by_side: dict[str, dict[str, list[float]]] = {
        "buy": {"1s": [], "5s": [], "30s": []},
        "sell": {"1s": [], "5s": [], "30s": []},
    }
    spread_capture: list[float] = []
    fill_values: list[float] = []
    shock_fill_counts: Counter[str] = Counter()
    shock_direction_by_event: dict[str, str] = {}
    shock_spread_capture: defaultdict[str, float] = defaultdict(float)
    shock_adverse_5s: defaultdict[str, list[float]] = defaultdict(list)
    for fill in fills:
        side = str(fill.payload["side"])
        price = float(fill.payload["fill_price"])
        size = float(fill.payload["fill_size"])
        fee = float(fill.payload.get("fee", 0))
        shock_event_id = fill.payload.get("shock_event_id")
        shock_id = str(shock_event_id) if shock_event_id else None
        if shock_id is not None:
            shock_fill_counts[shock_id] += 1
            direction = fill.payload.get("shock_direction")
            if direction:
                shock_direction_by_event.setdefault(shock_id, str(direction))
        fair_at_fill = fill.payload.get("fair_at_fill")
        spread_value: float | None = None
        if fair_at_fill:
            if side == "buy":
                spread_value = float(fair_at_fill) - price
            else:
                spread_value = price - float(fair_at_fill)
            spread_capture.append(spread_value)
            if shock_id is not None:
                shock_spread_capture[shock_id] += spread_value * size
        if side == "buy":
            base += size
            cash -= price * size + fee
            realized -= fee
        else:
            base -= size
            cash += price * size - fee
            realized -= fee
        for horizon, label, bucket in [
            ("fair_after_1s", "1s", adverse_1s),
            ("fair_after_5s", "5s", adverse_5s),
            ("fair_after_30s", "30s", adverse_30s),
        ]:
            fair_after = fill.payload.get(horizon)
            if fair_after is None:
                continue
            adverse = (float(fair_after) - price) if side == "buy" else (price - float(fair_after))
            bucket.append(adverse)
            if side in adverse_by_side:
                adverse_by_side[side][label].append(adverse)
            if shock_id is not None and label == "5s":
                shock_adverse_5s[shock_id].append(adverse)
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
    churn = _quote_churn(events)
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
        virtual_cancels=virtual_cancels,
        virtual_replaces=virtual_replaces,
        virtual_fills=len(fills),
        fill_rate=(len(fills) / virtual_orders) if virtual_orders else 0.0,
        fill_per_placed_order=(len(fills) / virtual_orders) if virtual_orders else 0.0,
        average_quote_lifetime_ms=churn["average_quote_lifetime_ms"],
        orders_per_minute=churn["orders_per_minute"],
        cancels_per_minute=churn["cancels_per_minute"],
        fill_per_active_second=churn["fill_per_active_second"],
        average_spread_captured=_avg(spread_capture),
        average_adverse_1s=_avg(adverse_1s),
        average_adverse_5s=_avg(adverse_5s),
        average_adverse_30s=_avg(adverse_30s),
        average_adverse_1s_buy=_avg(adverse_by_side["buy"]["1s"]),
        average_adverse_1s_sell=_avg(adverse_by_side["sell"]["1s"]),
        average_adverse_5s_buy=_avg(adverse_by_side["buy"]["5s"]),
        average_adverse_5s_sell=_avg(adverse_by_side["sell"]["5s"]),
        average_adverse_30s_buy=_avg(adverse_by_side["buy"]["30s"]),
        average_adverse_30s_sell=_avg(adverse_by_side["sell"]["30s"]),
        worst_adverse_buy=_min_nested(adverse_by_side["buy"].values()),
        worst_adverse_sell=_min_nested(adverse_by_side["sell"].values()),
        shock_event_fill_count=sum(shock_fill_counts.values()),
        shock_fill_count_by_event=dict(shock_fill_counts),
        shock_direction_by_event=shock_direction_by_event,
        shock_total_spread_capture_by_event=dict(shock_spread_capture),
        shock_average_adverse_5s_by_event={shock_id: _avg(values) for shock_id, values in shock_adverse_5s.items()},
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


def _min_nested(groups) -> float | None:
    values = [value for group in groups for value in group]
    return min(values) if values else None


def _quote_churn(events: list[Event]) -> dict[str, float | None]:
    if not events:
        return {
            "average_quote_lifetime_ms": None,
            "orders_per_minute": 0.0,
            "cancels_per_minute": 0.0,
            "fill_per_active_second": 0.0,
        }
    first_ts = min(event.ts_exchange for event in events)
    last_ts = max(event.ts_exchange for event in events)
    duration_min = max((last_ts - first_ts) / 60_000, 1e-12)
    placed: dict[str, float] = {}
    closed_at: dict[str, float] = {}
    fills = 0
    cancels = 0
    orders = 0
    for event in events:
        if event.event_type == "virtual_order_placed":
            order_id = str(event.payload["order_id"])
            placed[order_id] = float(event.payload.get("created_at", event.ts_exchange))
            orders += 1
        elif event.event_type == "virtual_order_canceled":
            order_id = str(event.payload["order_id"])
            closed_at.setdefault(order_id, event.ts_exchange)
            cancels += 1
        elif event.event_type == "virtual_fill":
            order_id = str(event.payload["order_id"])
            closed_at.setdefault(order_id, event.ts_exchange)
            fills += 1
    lifetimes = [max(0.0, closed_at.get(order_id, last_ts) - created_at) for order_id, created_at in placed.items()]
    active_seconds = sum(lifetimes) / 1000
    return {
        "average_quote_lifetime_ms": _avg(lifetimes),
        "orders_per_minute": orders / duration_min,
        "cancels_per_minute": cancels / duration_min,
        "fill_per_active_second": (fills / active_seconds) if active_seconds > 0 else 0.0,
    }
