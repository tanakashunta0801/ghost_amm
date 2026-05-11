from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from ghost_amm.events import Event


@dataclass(frozen=True)
class RecordingInspection:
    files: int
    events: int
    event_counts: dict[str, int]
    rooms: dict[str, int]
    has_pair_spec: bool
    has_status: bool
    has_ticker: bool
    has_trades: bool
    has_depth_snapshot: bool
    has_depth_delta: bool
    sequence_violations: int
    ok_for_replay: bool
    reason: str | None

    def to_dict(self) -> dict:
        return asdict(self)


def inspect_recording(paths: Iterable[str | Path], *, strict: bool = False) -> RecordingInspection:
    path_list = [Path(path) for path in paths]
    counts: Counter[str] = Counter()
    rooms: Counter[str] = Counter()
    events = 0
    sequence_violations = 0
    last_depth_sequence: int | None = None

    for path in path_list:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                data = json.loads(line)
                events += 1
                event_type = str(data.get("event_type"))
                counts[event_type] += 1
                payload = data.get("payload") or {}
                if isinstance(payload, dict) and payload.get("room_name"):
                    rooms[str(payload["room_name"])] += 1
                if event_type in {"order_book_snapshot", "order_book_delta"}:
                    seq = _to_int(data.get("sequence"))
                    if event_type == "order_book_snapshot":
                        last_depth_sequence = seq
                    elif seq is not None and last_depth_sequence is not None:
                        if seq <= last_depth_sequence:
                            sequence_violations += 1
                        last_depth_sequence = seq

    has_pair_spec = counts["bitbank_pair_spec"] > 0
    has_status = counts["bitbank_status"] > 0
    has_ticker = counts["bitbank_ticker"] > 0
    has_trades = counts["trade"] > 0
    has_depth_snapshot = counts["order_book_snapshot"] > 0
    has_depth_delta = counts["order_book_delta"] > 0
    required = [
        ("bitbank_pair_spec", has_pair_spec),
        ("bitbank_status", has_status),
        ("order_book_snapshot", has_depth_snapshot),
        ("order_book_delta", has_depth_delta),
    ]
    if strict:
        required.extend([("bitbank_ticker", has_ticker), ("trade", has_trades)])
    missing = []
    for name, present in required:
        if not present:
            missing.append(name)
    ok = not missing and sequence_violations == 0
    reason = None
    if missing:
        reason = "missing:" + ",".join(missing)
    elif sequence_violations:
        reason = "sequence_violations"
    return RecordingInspection(
        files=len(path_list),
        events=events,
        event_counts=dict(sorted(counts.items())),
        rooms=dict(sorted(rooms.items())),
        has_pair_spec=has_pair_spec,
        has_status=has_status,
        has_ticker=has_ticker,
        has_trades=has_trades,
        has_depth_snapshot=has_depth_snapshot,
        has_depth_delta=has_depth_delta,
        sequence_violations=sequence_violations,
        ok_for_replay=ok,
        reason=reason,
    )


def _to_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
