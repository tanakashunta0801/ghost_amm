from __future__ import annotations

from pathlib import Path

from ghost_amm.analytics.metrics import summarize
from ghost_amm.analytics.report import write_report
from ghost_amm.config import Config
from ghost_amm.events import Event, read_jsonl
from ghost_amm.pipeline import GhostAmmPipeline


class ReplayEngine:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.pipeline = GhostAmmPipeline(config)

    def run(self, events: list[Event]) -> list[Event]:
        ordered = sorted(events, key=lambda event: (event.ts_exchange, str(event.sequence)))
        output: list[Event] = []
        for event in ordered:
            output.append(event)
            output.extend(self.pipeline.process(event))
        return enrich_fair_after(output)

    def run_file(self, events_path: str | Path, out_dir: str | Path) -> list[Event]:
        return self.run_files([events_path], out_dir)

    def run_files(self, event_paths: list[str | Path], out_dir: str | Path) -> list[Event]:
        events: list[Event] = []
        for path in event_paths:
            events.extend(read_jsonl(path))
        output = self.run(events)
        inv_cfg = self.config.section("inventory")
        last_fair = self.pipeline.last_fair.fair
        summary = summarize(
            output,
            initial_base=float(inv_cfg.get("initial_base_qty", 0.01)),
            initial_quote=float(inv_cfg.get("initial_quote_qty", 150_000)),
            last_fair=last_fair,
        )
        write_report(out_dir, output, summary)
        return output


def enrich_fair_after(events: list[Event]) -> list[Event]:
    fair_points = [(event.ts_exchange, float(event.payload["fair"])) for event in events if event.event_type == "mark_price" and event.payload.get("fair") is not None]
    if not fair_points:
        return events
    enriched: list[Event] = []
    for event in events:
        if event.event_type != "virtual_fill":
            enriched.append(event)
            continue
        payload = dict(event.payload)
        for horizon, key in [(1000, "fair_after_1s"), (5000, "fair_after_5s"), (30000, "fair_after_30s")]:
            payload[key] = _fair_at_or_after(fair_points, event.ts_exchange + horizon)
        enriched.append(
            type(event)(
                event_id=event.event_id,
                ts_exchange=event.ts_exchange,
                ts_local=event.ts_local,
                venue=event.venue,
                symbol=event.symbol,
                event_type=event.event_type,
                sequence=event.sequence,
                payload=payload,
                raw_payload=event.raw_payload,
            )
        )
    return enriched


def _fair_at_or_after(points: list[tuple[float, float]], target: float) -> float | None:
    for ts, fair in points:
        if ts >= target:
            return fair
    return points[-1][1]
