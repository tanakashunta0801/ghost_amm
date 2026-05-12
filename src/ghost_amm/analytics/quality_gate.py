from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class QualityGateThresholds:
    min_report_count: int = 2
    min_recording_hours: float = 24.0
    min_fills: int = 30
    min_fill_rate: float = 0.001
    min_strategy_alpha_pnl: float = 0.0
    max_orders_per_minute: float = 10.0
    max_cancels_per_minute: float = 10.0


@dataclass(frozen=True)
class QualityGateResult:
    ok: bool
    failures: list[str]
    thresholds: dict[str, Any]
    reports: list[dict[str, Any]]
    recording_inspection: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_quality_gate(
    *,
    summary_paths: list[str | Path],
    recording_inspection_path: str | Path | None = None,
    thresholds: QualityGateThresholds | None = None,
) -> QualityGateResult:
    thresholds = thresholds or QualityGateThresholds()
    failures: list[str] = []
    reports = [_summary_report(Path(path)) for path in summary_paths]
    if len(reports) < thresholds.min_report_count:
        failures.append(f"report_count_below_min:{len(reports)}<{thresholds.min_report_count}")

    inspection = None
    if recording_inspection_path is None:
        failures.append("recording_inspection_required")
    else:
        inspection = _read_json(Path(recording_inspection_path))
        if not inspection.get("ok_for_replay"):
            failures.append(f"recording_inspection_not_ok:{inspection.get('reason')}")
        duration_hours = _to_float(inspection.get("duration_hours"))
        if duration_hours is None:
            failures.append("recording_duration_missing")
        elif duration_hours < thresholds.min_recording_hours:
            failures.append(f"recording_duration_below_min:{duration_hours}<{thresholds.min_recording_hours}")

    for report in reports:
        label = str(report["path"])
        if int(report["virtual_fills"]) < thresholds.min_fills:
            failures.append(f"{label}:fills_below_min:{report['virtual_fills']}<{thresholds.min_fills}")
        if float(report["fill_rate"]) < thresholds.min_fill_rate:
            failures.append(f"{label}:fill_rate_below_min:{report['fill_rate']}<{thresholds.min_fill_rate}")
        if float(report["strategy_alpha_pnl"]) <= thresholds.min_strategy_alpha_pnl:
            failures.append(f"{label}:strategy_alpha_not_positive:{report['strategy_alpha_pnl']}<={thresholds.min_strategy_alpha_pnl}")
        if float(report["orders_per_minute"]) > thresholds.max_orders_per_minute:
            failures.append(f"{label}:orders_per_minute_above_max:{report['orders_per_minute']}>{thresholds.max_orders_per_minute}")
        if float(report["cancels_per_minute"]) > thresholds.max_cancels_per_minute:
            failures.append(f"{label}:cancels_per_minute_above_max:{report['cancels_per_minute']}>{thresholds.max_cancels_per_minute}")

    return QualityGateResult(
        ok=not failures,
        failures=failures,
        thresholds=asdict(thresholds),
        reports=reports,
        recording_inspection=inspection,
    )


def write_quality_gate_result(path: str | Path, result: QualityGateResult) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        json.dump(result.to_dict(), fh, ensure_ascii=False, indent=2, sort_keys=True)


def _summary_report(path: Path) -> dict[str, Any]:
    data = _read_json(path)
    return {
        "path": str(path),
        "strategy_alpha_pnl": _required_float(data, "strategy_alpha_pnl"),
        "virtual_fills": int(_required_float(data, "virtual_fills")),
        "virtual_orders": int(_required_float(data, "virtual_orders")),
        "fill_rate": _required_float(data, "fill_rate"),
        "orders_per_minute": _required_float(data, "orders_per_minute"),
        "cancels_per_minute": _required_float(data, "cancels_per_minute"),
        "fill_per_active_second": _required_float(data, "fill_per_active_second"),
    }


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"JSON object required: {path}")
    return data


def _required_float(data: dict[str, Any], key: str) -> float:
    value = _to_float(data.get(key))
    if value is None:
        raise ValueError(f"Missing numeric summary field: {key}")
    return value


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
