from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ghost_amm.analytics.metrics import summarize
from ghost_amm.config import Config, deep_merge
from ghost_amm.events import Event
from ghost_amm.replay.engine import ReplayEngine


def run_activation_sweep(
    *,
    base_config: Config,
    events: list[Event],
    thresholds: list[float],
    min_activations: list[float],
    out_dir: str | Path,
) -> list[dict[str, Any]]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for threshold in thresholds:
        for min_activation in min_activations:
            override = {"shock": {"threshold": threshold, "min_activation_to_quote": min_activation}}
            config = Config(deep_merge(base_config.data, override))
            engine = ReplayEngine(config)
            output = engine.run(events)
            inv_cfg = config.section("inventory")
            summary = summarize(
                output,
                initial_base=float(inv_cfg.get("initial_base_qty", 0.01)),
                initial_quote=float(inv_cfg.get("initial_quote_qty", 150_000)),
                last_fair=engine.pipeline.last_fair.fair,
            )
            row = {
                "shock_threshold": threshold,
                "min_activation_to_quote": min_activation,
                **asdict(summary),
            }
            row["orders_per_fill"] = (row["virtual_orders"] / row["virtual_fills"]) if row["virtual_fills"] else None
            rows.append(row)
    rows.sort(key=_rank_key)
    _write_outputs(out, rows)
    return rows


def run_churn_sweep(
    *,
    base_config: Config,
    events: list[Event],
    shock_threshold: float,
    min_activation: float,
    max_active_orders: list[int],
    quote_ttls_ms: list[float],
    min_replace_intervals_ms: list[float],
    replace_threshold_bps: float,
    size_replace_threshold_ratio: float,
    out_dir: str | Path,
) -> list[dict[str, Any]]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for max_orders in max_active_orders:
        for ttl_ms in quote_ttls_ms:
            for min_replace_ms in min_replace_intervals_ms:
                override = {
                    "shock": {"threshold": shock_threshold, "min_activation_to_quote": min_activation},
                    "execution": {
                        "max_active_orders_per_pair": max_orders,
                        "quote_ttl_ms": ttl_ms,
                        "min_quote_replace_interval_ms": min_replace_ms,
                        "quote_replace_threshold_bps": replace_threshold_bps,
                        "size_replace_threshold_ratio": size_replace_threshold_ratio,
                    },
                }
                config = Config(deep_merge(base_config.data, override))
                engine = ReplayEngine(config)
                output = engine.run(events)
                inv_cfg = config.section("inventory")
                summary = summarize(
                    output,
                    initial_base=float(inv_cfg.get("initial_base_qty", 0.01)),
                    initial_quote=float(inv_cfg.get("initial_quote_qty", 150_000)),
                    last_fair=engine.pipeline.last_fair.fair,
                )
                row = {
                    "shock_threshold": shock_threshold,
                    "min_activation_to_quote": min_activation,
                    "max_active_orders": max_orders,
                    "quote_ttl_ms": ttl_ms,
                    "min_replace_interval_ms": min_replace_ms,
                    "replace_threshold_bps": replace_threshold_bps,
                    "size_replace_threshold_ratio": size_replace_threshold_ratio,
                    **asdict(summary),
                }
                row["orders_per_fill"] = (row["virtual_orders"] / row["virtual_fills"]) if row["virtual_fills"] else None
                rows.append(row)
    rows.sort(key=_rank_key)
    _write_outputs(out, rows, stem="churn_sweep")
    return rows


def _rank_key(row: dict[str, Any]) -> tuple[int, float, float, float]:
    fills = int(row["virtual_fills"])
    orders = int(row["virtual_orders"])
    adverse = row.get("average_adverse_5s")
    adverse_value = float(adverse) if adverse is not None else -1e18
    alpha = float(row.get("strategy_alpha_pnl") or 0.0)
    # Prefer configs with any fills, better 5s adverse selection, fewer orders, and better alpha.
    return (0 if fills else 1, -adverse_value, orders, -alpha)


def _write_outputs(out: Path, rows: list[dict[str, Any]], *, stem: str = "activation_sweep") -> None:
    json_path = out / f"{stem}.json"
    csv_path = out / f"{stem}.csv"
    md_path = out / f"{stem}.md"
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    if rows:
        fields = list(rows[0].keys())
        with csv_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    md_path.write_text(_render_markdown(rows, title=stem.replace("_", " ").title()), encoding="utf-8")


def _render_markdown(rows: list[dict[str, Any]], *, title: str = "Activation Sweep") -> str:
    lines = [
        f"# {title}",
        "",
        "| threshold | min_activation | max_orders | ttl_ms | min_replace_ms | orders | fills | fill_rate | adverse_5s | alpha_pnl | total_pnl | blocked |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {shock_threshold} | {min_activation_to_quote} | {max_active_orders} | {quote_ttl_ms} | {min_replace_interval_ms} | {virtual_orders} | {virtual_fills} | {fill_rate} | {average_adverse_5s} | {strategy_alpha_pnl} | {total_pnl} | {risk_blocked_quote_count} |".format(
                **{
                    "max_active_orders": "",
                    "quote_ttl_ms": "",
                    "min_replace_interval_ms": "",
                    **row,
                }
            )
        )
    lines.extend(
        [
            "",
            "Ranking is diagnostic only. Do not treat the best in-sample row as an optimized strategy without split-period validation.",
        ]
    )
    return "\n".join(lines) + "\n"
