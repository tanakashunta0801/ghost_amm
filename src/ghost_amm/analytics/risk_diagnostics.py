from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from ghost_amm.events import Event, write_jsonl


@dataclass(frozen=True)
class RiskDiagnostics:
    total_risk_events: int
    allow_quote_events: int
    blocked_events: int
    reason_counts: dict[str, int]
    percentiles: dict[str, dict[str, float | None]]
    recommendations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def analyze_risk_blocks(events: Iterable[Event]) -> RiskDiagnostics:
    risk_events = [event for event in events if event.event_type == "risk_state"]
    reason_counts: Counter[str] = Counter()
    allow_quote = 0
    series: dict[str, list[float]] = {
        "activation": [],
        "bid_activation": [],
        "ask_activation": [],
        "force_ratio": [],
        "depth_20bps": [],
        "spread_bps": [],
        "book_spread_bps": [],
        "inventory_skew": [],
    }
    for event in risk_events:
        payload = event.payload
        if payload.get("allow_quote"):
            allow_quote += 1
        else:
            reason_counts[str(payload.get("reason") or "unknown")] += 1
        for key in series:
            value = payload.get(key)
            if value is not None:
                try:
                    series[key].append(float(value))
                except (TypeError, ValueError):
                    pass

    pct = {key: _percentiles(values) for key, values in series.items()}
    recommendations = _recommend(reason_counts, pct)
    return RiskDiagnostics(
        total_risk_events=len(risk_events),
        allow_quote_events=allow_quote,
        blocked_events=len(risk_events) - allow_quote,
        reason_counts=dict(reason_counts.most_common()),
        percentiles=pct,
        recommendations=recommendations,
    )


def write_risk_diagnostics(out: str | Path, diagnostics: RiskDiagnostics) -> tuple[Path, Path]:
    out_path = Path(out)
    if out_path.suffix.lower() == ".json":
        json_path = out_path
        md_path = out_path.with_suffix(".md")
    else:
        json_path = out_path / "risk_diagnostics.json"
        md_path = out_path / "risk_diagnostics.md"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(diagnostics.to_dict(), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_render_markdown(diagnostics), encoding="utf-8")
    return json_path, md_path


def _percentiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"count": 0, "p0": None, "p10": None, "p25": None, "p50": None, "p75": None, "p90": None, "p95": None, "p99": None, "max": None}
    ordered = sorted(values)
    return {
        "count": float(len(ordered)),
        "p0": ordered[0],
        "p10": _pick(ordered, 0.10),
        "p25": _pick(ordered, 0.25),
        "p50": _pick(ordered, 0.50),
        "p75": _pick(ordered, 0.75),
        "p90": _pick(ordered, 0.90),
        "p95": _pick(ordered, 0.95),
        "p99": _pick(ordered, 0.99),
        "max": ordered[-1],
    }


def _pick(ordered: list[float], q: float) -> float:
    idx = min(max(round((len(ordered) - 1) * q), 0), len(ordered) - 1)
    return ordered[idx]


def _recommend(reason_counts: Counter[str], percentiles: dict[str, dict[str, float | None]]) -> list[str]:
    recommendations: list[str] = []
    total = sum(reason_counts.values())
    if total == 0:
        return ["Risk kernel allowed at least one quote; inspect order/fill behavior next."]
    top_reason, top_count = reason_counts.most_common(1)[0]
    share = top_count / total
    if top_reason == "activation_too_low":
        activation = percentiles.get("activation", {})
        force = percentiles.get("force_ratio", {})
        p95_activation = activation.get("p95")
        p99_activation = activation.get("p99")
        max_activation = activation.get("max")
        recommendations.append(
            "Dominant block is activation_too_low. Calibrate shock.threshold and shock.min_activation_to_quote before changing AMM sizing."
        )
        if p99_activation is not None and max_activation is not None:
            recommendations.append(
                f"Try min_activation_to_quote below observed high-end activation: p95={p95_activation}, p99={p99_activation}, max={max_activation}."
            )
        if force.get("p95") is not None:
            recommendations.append(
                f"Use force_ratio percentiles for threshold sweep candidates: p75={force.get('p75')}, p90={force.get('p90')}, p95={force.get('p95')}, p99={force.get('p99')}."
            )
    elif top_reason == "book_too_thin":
        depth = percentiles.get("depth_20bps", {})
        recommendations.append(
            "Dominant block is book_too_thin. Set market.min_depth_20bps_jpy from observed depth percentiles rather than a fixed guess."
        )
        recommendations.append(
            f"Depth candidates: p10={depth.get('p10')}, p25={depth.get('p25')}, p50={depth.get('p50')}, p75={depth.get('p75')}."
        )
    elif top_reason == "spread_too_wide":
        spread = percentiles.get("book_spread_bps", {}) or percentiles.get("spread_bps", {})
        recommendations.append("Dominant block is spread_too_wide. Compare market.max_spread_bps to observed spread percentiles.")
        recommendations.append(f"Spread candidates: p90={spread.get('p90')}, p95={spread.get('p95')}, p99={spread.get('p99')}.")
    else:
        recommendations.append(f"Dominant block is {top_reason} ({share:.1%} of blocked events). Inspect that gate before parameter sweeping.")
    if share > 0.95:
        recommendations.append("One gate dominates more than 95% of blocks; tune that gate first and avoid broad multi-parameter optimization.")
    recommendations.append("After selecting 2-4 candidate configs, rerun on split periods and compare stability instead of picking the single best in-sample result.")
    return recommendations


def _render_markdown(diagnostics: RiskDiagnostics) -> str:
    lines = [
        "# Risk Diagnostics",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| total_risk_events | {diagnostics.total_risk_events} |",
        f"| allow_quote_events | {diagnostics.allow_quote_events} |",
        f"| blocked_events | {diagnostics.blocked_events} |",
        "",
        "## Block Reasons",
        "",
        "| Reason | Count |",
        "|---|---:|",
    ]
    for reason, count in diagnostics.reason_counts.items():
        lines.append(f"| {reason} | {count} |")
    lines.extend(["", "## Percentiles", ""])
    for name, values in diagnostics.percentiles.items():
        lines.append(f"### {name}")
        lines.append("")
        lines.append("| Percentile | Value |")
        lines.append("|---|---:|")
        for key, value in values.items():
            lines.append(f"| {key} | {value} |")
        lines.append("")
    lines.extend(["## Recommendations", ""])
    for item in diagnostics.recommendations:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"
