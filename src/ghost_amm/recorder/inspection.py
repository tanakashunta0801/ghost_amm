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
    depth_delta_sequence_monotonic: bool
    depth_snapshot_first_ts: float | None
    depth_snapshot_last_ts: float | None
    ticker_count: int
    transaction_count: int
    reconnect_count: int
    heartbeat_events: int
    connection_events: int
    first_event_ts: float | None
    last_event_ts: float | None
    duration_ms: float | None
    duration_hours: float | None
    max_event_gap_ms: float | None
    max_local_exchange_drift_ms: float | None
    metadata_fetch_failed: bool
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
    depth_snapshot_first_ts: float | None = None
    depth_snapshot_last_ts: float | None = None
    last_event_ts: float | None = None
    first_event_ts: float | None = None
    final_event_ts: float | None = None
    max_event_gap_ms: float | None = None
    max_local_exchange_drift_ms: float | None = None
    reconnect_count = 0
    heartbeat_events = 0
    connection_events = 0
    metadata_fetch_failed = False

    for path in path_list:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                data = json.loads(line)
                events += 1
                event_type = str(data.get("event_type"))
                ts_exchange = _to_float(data.get("ts_exchange"))
                ts_local = _to_float(data.get("ts_local"))
                if ts_exchange is not None:
                    first_event_ts = ts_exchange if first_event_ts is None else first_event_ts
                    final_event_ts = ts_exchange
                    if last_event_ts is not None:
                        gap = max(0.0, ts_exchange - last_event_ts)
                        max_event_gap_ms = gap if max_event_gap_ms is None else max(max_event_gap_ms, gap)
                    last_event_ts = ts_exchange
                if ts_exchange is not None and ts_local is not None:
                    drift = abs(ts_local - ts_exchange)
                    max_local_exchange_drift_ms = drift if max_local_exchange_drift_ms is None else max(max_local_exchange_drift_ms, drift)
                counts[event_type] += 1
                payload = data.get("payload") or {}
                raw_payload = data.get("raw_payload") or {}
                room_name = _room_name(payload, raw_payload)
                if room_name:
                    rooms[room_name] += 1
                if event_type == "dry_run_heartbeat":
                    heartbeat_events += 1
                    if _is_connection_heartbeat(payload):
                        connection_events += 1
                if isinstance(payload, dict):
                    if "reconnects" in payload:
                        reconnect_count = max(reconnect_count, int(payload.get("reconnects") or 0))
                    reason = str(payload.get("reason") or "")
                    if reason.startswith("metadata_fetch_failed") or reason == "metadata_pair_or_status_missing":
                        metadata_fetch_failed = True
                if event_type in {"order_book_snapshot", "order_book_delta"}:
                    seq = _to_int(data.get("sequence"))
                    if event_type == "order_book_snapshot":
                        last_depth_sequence = seq
                        if ts_exchange is not None:
                            depth_snapshot_first_ts = ts_exchange if depth_snapshot_first_ts is None else depth_snapshot_first_ts
                            depth_snapshot_last_ts = ts_exchange
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
    ticker_count = counts["bitbank_ticker"]
    transaction_count = counts["trade"]
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
    ok = not missing and sequence_violations == 0 and not metadata_fetch_failed
    reason = None
    if missing:
        reason = "missing:" + ",".join(missing)
    elif metadata_fetch_failed:
        reason = "metadata_fetch_failed"
    elif sequence_violations:
        reason = "sequence_violations"
    duration_ms = None
    duration_hours = None
    if first_event_ts is not None and final_event_ts is not None:
        duration_ms = max(0.0, final_event_ts - first_event_ts)
        duration_hours = duration_ms / 3_600_000
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
        depth_delta_sequence_monotonic=sequence_violations == 0,
        depth_snapshot_first_ts=depth_snapshot_first_ts,
        depth_snapshot_last_ts=depth_snapshot_last_ts,
        ticker_count=ticker_count,
        transaction_count=transaction_count,
        reconnect_count=reconnect_count,
        heartbeat_events=heartbeat_events,
        connection_events=connection_events,
        first_event_ts=first_event_ts,
        last_event_ts=final_event_ts,
        duration_ms=duration_ms,
        duration_hours=duration_hours,
        max_event_gap_ms=max_event_gap_ms,
        max_local_exchange_drift_ms=max_local_exchange_drift_ms,
        metadata_fetch_failed=metadata_fetch_failed,
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


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _room_name(payload: object, raw_payload: object) -> str | None:
    if isinstance(payload, dict) and payload.get("room_name"):
        return str(payload["room_name"])
    if isinstance(raw_payload, dict):
        room_name = raw_payload.get("room_name")
        if room_name:
            return str(room_name)
    return None


def _is_connection_heartbeat(payload: object) -> bool:
    if not isinstance(payload, dict):
        return True
    heartbeat_type = payload.get("heartbeat_type")
    if heartbeat_type is None:
        return True
    return heartbeat_type in {"connect", "disconnect"}
