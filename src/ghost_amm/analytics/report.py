from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ghost_amm.analytics.metrics import MetricsSummary
from ghost_amm.events import Event, write_jsonl


def write_report(out_dir: str | Path, events: list[Event], summary: MetricsSummary, *, metadata: dict[str, Any] | None = None) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary_data = asdict(summary) | (metadata or {})
    write_jsonl(out / "events.jsonl", events)
    with (out / "summary.json").open("w", encoding="utf-8") as fh:
        json.dump(summary_data, fh, ensure_ascii=False, indent=2, sort_keys=True)
    _write_fills_csv(out / "fills.csv", events)
    (out / "report.md").write_text(_render_markdown(summary_data), encoding="utf-8")


def _write_fills_csv(path: Path, events: list[Event]) -> None:
    fills = [event for event in events if event.event_type == "virtual_fill"]
    fields = [
        "order_id",
        "side",
        "fill_price",
        "fill_size",
        "fill_ts",
        "fee",
        "queue_ahead_estimate",
        "fair_at_fill",
        "fair_after_1s",
        "fair_after_5s",
        "fair_after_30s",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for fill in fills:
            writer.writerow({field: fill.payload.get(field) for field in fields})


def _render_markdown(summary_data: dict[str, Any]) -> str:
    lines = [
        "# Ghost AMM Replay Report",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    for key, value in summary_data.items():
        lines.append(f"| {key} | {value} |")
    lines.extend(
        [
            "",
            "All orders in this report are virtual post-only orders. No private bitbank endpoint or live order path is used by replay.",
        ]
    )
    return "\n".join(lines) + "\n"
