from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Iterable

from ghost_amm.events import Event, deterministic_event_id, iter_jsonl, write_jsonl


DEFAULT_METADATA_EVENT_TYPES = ("bitbank_pair_spec", "bitbank_status")


@dataclass(frozen=True)
class RecordingSplit:
    index: int
    path: str
    events: int
    data_events: int
    start_ts: float
    end_ts: float
    duration_hours: float


@dataclass(frozen=True)
class RecordingSplitResult:
    inputs: list[str]
    out_prefix: str
    parts: int
    first_ts: float
    last_ts: float
    metadata_events: int
    splits: list[RecordingSplit]

    def to_dict(self) -> dict:
        data = asdict(self)
        data["splits"] = [asdict(split) for split in self.splits]
        return data


def split_recording_by_time(
    paths: Iterable[str | Path],
    *,
    out_prefix: str | Path,
    parts: int = 2,
    metadata_event_types: Iterable[str] = DEFAULT_METADATA_EVENT_TYPES,
) -> RecordingSplitResult:
    if parts < 2:
        raise ValueError("parts_must_be_at_least_2")
    input_paths = [Path(path) for path in paths]
    if not input_paths:
        raise ValueError("no_input_files")
    metadata_types = tuple(metadata_event_types)
    metadata_seen: set[str] = set()
    metadata_events: list[Event] = []
    data_events: list[Event] = []
    for path in input_paths:
        for event in iter_jsonl(path):
            if event.event_type in metadata_types and event.event_type not in metadata_seen:
                metadata_events.append(event)
                metadata_seen.add(event.event_type)
            elif event.ts_exchange is not None:
                data_events.append(event)
    if not data_events:
        raise ValueError("no_timestamped_data_events")
    first_ts = min(float(event.ts_exchange) for event in data_events)
    last_ts = max(float(event.ts_exchange) for event in data_events)
    if last_ts <= first_ts:
        raise ValueError("recording_duration_zero")

    span = last_ts - first_ts
    out = Path(out_prefix)
    splits: list[RecordingSplit] = []
    for index in range(parts):
        start = first_ts + span * index / parts
        end = first_ts + span * (index + 1) / parts
        selected = [
            event
            for event in data_events
            if _event_in_split(float(event.ts_exchange), start=start, end=end, final=index == parts - 1)
        ]
        if not selected:
            raise ValueError(f"empty_split:{index + 1}")
        split_start = min(float(event.ts_exchange) for event in selected)
        split_end = max(float(event.ts_exchange) for event in selected)
        output_path = out.parent / f"{out.name}_{index + 1:02d}.jsonl"
        output_events = [*_metadata_for_split(metadata_events, split_start), *selected]
        write_jsonl(output_path, output_events)
        splits.append(
            RecordingSplit(
                index=index + 1,
                path=str(output_path),
                events=len(output_events),
                data_events=len(selected),
                start_ts=split_start,
                end_ts=split_end,
                duration_hours=max(0.0, split_end - split_start) / 3_600_000,
            )
        )
    return RecordingSplitResult(
        inputs=[str(path) for path in input_paths],
        out_prefix=str(out),
        parts=parts,
        first_ts=first_ts,
        last_ts=last_ts,
        metadata_events=len(metadata_events),
        splits=splits,
    )


def _event_in_split(ts: float, *, start: float, end: float, final: bool) -> bool:
    if final:
        return start <= ts <= end
    return start <= ts < end


def _metadata_for_split(metadata_events: list[Event], split_start_ts: float) -> list[Event]:
    adjusted: list[Event] = []
    for index, event in enumerate(metadata_events):
        ts = split_start_ts - (len(metadata_events) - index)
        adjusted.append(
            replace(
                event,
                event_id=deterministic_event_id("recording_split_metadata", event.event_id, index, ts),
                ts_exchange=ts,
                ts_local=ts,
            )
        )
    return adjusted
