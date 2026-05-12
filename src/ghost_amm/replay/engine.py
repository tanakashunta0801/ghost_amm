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
        self.last_replay_order = str(config.get("replay.order", "arrival_order"))
        self.last_strict_sequence = bool(config.get("replay.strict_sequence", True))

    def run(
        self,
        events: list[Event],
        *,
        replay_order: str | None = None,
        strict_sequence: bool | None = None,
    ) -> list[Event]:
        ordered = self._order_events(events, replay_order=replay_order)
        self.last_strict_sequence = bool(self.config.get("replay.strict_sequence", True)) if strict_sequence is None else strict_sequence
        if self.last_strict_sequence:
            _assert_monotonic_sequences(ordered)
        output: list[Event] = []
        for event in ordered:
            output.append(event)
            output.extend(self.pipeline.process(event))
        return enrich_fair_after(output)

    def run_file(
        self,
        events_path: str | Path,
        out_dir: str | Path,
        *,
        replay_order: str | None = None,
        strict_sequence: bool | None = None,
    ) -> list[Event]:
        return self.run_files([events_path], out_dir, replay_order=replay_order, strict_sequence=strict_sequence)

    def run_files(
        self,
        event_paths: list[str | Path],
        out_dir: str | Path,
        *,
        replay_order: str | None = None,
        strict_sequence: bool | None = None,
    ) -> list[Event]:
        events: list[Event] = []
        for path in event_paths:
            events.extend(read_jsonl(path))
        output = self.run(events, replay_order=replay_order, strict_sequence=strict_sequence)
        inv_cfg = self.config.section("inventory")
        last_fair = self.pipeline.last_fair.fair
        summary = summarize(
            output,
            initial_base=float(inv_cfg.get("initial_base_qty", 0.01)),
            initial_quote=float(inv_cfg.get("initial_quote_qty", 150_000)),
            last_fair=last_fair,
        )
        write_report(
            out_dir,
            output,
            summary,
            metadata={"replay_order": self.last_replay_order, "strict_sequence": self.last_strict_sequence},
        )
        return output

    def _order_events(self, events: list[Event], *, replay_order: str | None = None) -> list[Event]:
        explicit_order = replay_order is not None
        order = replay_order or str(self.config.get("replay.order", "arrival_order"))
        if order not in {"arrival_order", "exchange_time_sort"}:
            raise ValueError(f"Unsupported replay order: {order}")
        if order == "exchange_time_sort":
            allowed = bool(self.config.get("replay.allow_exchange_time_sort", False))
            if not allowed and not explicit_order:
                raise ValueError("exchange_time_sort requires replay.allow_exchange_time_sort=true or an explicit CLI override")
            self.last_replay_order = order
            return sorted(events, key=lambda event: (event.ts_exchange, str(event.sequence)))
        self.last_replay_order = order
        return list(events)


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


def _assert_monotonic_sequences(events: list[Event]) -> None:
    last_by_stream: dict[tuple[str, str, str], int] = {}
    for event in events:
        seq = _to_int(event.sequence)
        if seq is None:
            continue
        key = (event.venue, event.symbol, _sequence_stream(event.event_type))
        previous = last_by_stream.get(key)
        if previous is not None and seq < previous:
            raise ValueError(f"Sequence violation in replay stream {key}: {seq} after {previous}")
        last_by_stream[key] = seq


def _sequence_stream(event_type: str) -> str:
    if event_type in {"order_book_snapshot", "order_book_delta"}:
        return "order_book"
    return event_type


def _to_int(value: int | str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
