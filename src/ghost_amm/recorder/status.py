from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from ghost_amm.recorder.inspection import inspect_recording


@dataclass(frozen=True)
class RecordingFileStatus:
    path: str
    exists: bool
    bytes: int
    last_write_time: float | None
    last_write_age_sec: float | None


@dataclass(frozen=True)
class RecordingStatus:
    ok: bool
    stale: bool
    total_bytes: int
    latest_write_age_sec: float | None
    min_duration_hours: float | None
    duration_hours: float | None
    duration_ok: bool | None
    files: list[RecordingFileStatus]
    inspection: dict[str, Any] | None
    reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def recording_status(
    paths: Iterable[str | Path],
    *,
    strict: bool = False,
    max_stale_sec: float = 300.0,
    inspect: bool = True,
    min_duration_hours: float | None = None,
    now: float | None = None,
) -> RecordingStatus:
    now = time.time() if now is None else now
    file_statuses = [_file_status(Path(path), now=now) for path in paths]
    missing = [item.path for item in file_statuses if not item.exists]
    existing = [item for item in file_statuses if item.exists]
    total_bytes = sum(item.bytes for item in existing)
    latest_age = min((item.last_write_age_sec for item in existing if item.last_write_age_sec is not None), default=None)
    stale = latest_age is None or latest_age > max_stale_sec
    inspection = None
    duration_hours = None
    duration_ok = None
    reason = None
    if missing:
        reason = "missing_files:" + ",".join(missing)
    elif stale:
        reason = f"recording_stale:{latest_age}>{max_stale_sec}"
    if inspect and not missing:
        result = inspect_recording([item.path for item in existing], strict=strict)
        inspection = result.to_dict()
        duration_hours = result.duration_hours
        if min_duration_hours is not None:
            duration_ok = duration_hours >= min_duration_hours
        if not result.ok_for_replay and reason is None:
            reason = f"inspection_failed:{result.reason}"
        elif min_duration_hours is not None and duration_hours < min_duration_hours and reason is None:
            reason = f"recording_duration_below_min:{duration_hours}<{min_duration_hours}"
    elif min_duration_hours is not None and reason is None:
        duration_ok = False
        reason = "inspection_required_for_min_duration"
    return RecordingStatus(
        ok=reason is None,
        stale=stale,
        total_bytes=total_bytes,
        latest_write_age_sec=latest_age,
        min_duration_hours=min_duration_hours,
        duration_hours=duration_hours,
        duration_ok=duration_ok,
        files=file_statuses,
        inspection=inspection,
        reason=reason,
    )


def _file_status(path: Path, *, now: float) -> RecordingFileStatus:
    if not path.exists():
        return RecordingFileStatus(str(path), False, 0, None, None)
    stat = path.stat()
    return RecordingFileStatus(
        path=str(path),
        exists=True,
        bytes=stat.st_size,
        last_write_time=stat.st_mtime,
        last_write_age_sec=max(0.0, now - stat.st_mtime),
    )
