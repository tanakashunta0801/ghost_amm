import json

from ghost_amm.analytics.quality_gate import QualityGateThresholds, evaluate_quality_gate
from ghost_amm.cli import main


def test_quality_gate_passes_multiple_positive_reports_with_24h_inspection(tmp_path) -> None:
    inspection = _write_json(tmp_path / "recording_inspection.json", {"ok_for_replay": True, "duration_hours": 24.5})
    summary_a = _write_summary(tmp_path / "a.json", strategy_alpha_pnl=10.0)
    summary_b = _write_summary(tmp_path / "b.json", strategy_alpha_pnl=5.0)

    result = evaluate_quality_gate(
        summary_paths=[summary_a, summary_b],
        recording_inspection_path=inspection,
        thresholds=QualityGateThresholds(min_report_count=2, min_recording_hours=24, min_fills=30),
    )

    assert result.ok
    assert result.failures == []


def test_quality_gate_fails_short_recording_low_fills_and_negative_alpha(tmp_path) -> None:
    inspection = _write_json(tmp_path / "recording_inspection.json", {"ok_for_replay": True, "duration_hours": 12.0})
    summary = _write_summary(tmp_path / "summary.json", strategy_alpha_pnl=-4.0, virtual_fills=1, fill_rate=0.0001)

    result = evaluate_quality_gate(summary_paths=[summary], recording_inspection_path=inspection)

    assert not result.ok
    assert "report_count_below_min:1<2" in result.failures
    assert "recording_duration_below_min:12.0<24.0" in result.failures
    assert f"{summary}:fills_below_min:1<30" in result.failures
    assert f"{summary}:strategy_alpha_not_positive:-4.0<=0.0" in result.failures


def test_evaluate_quality_gate_cli_writes_result_and_returns_failure(tmp_path, capsys) -> None:
    inspection = _write_json(tmp_path / "recording_inspection.json", {"ok_for_replay": True, "duration_hours": 6.0})
    summary = _write_summary(tmp_path / "summary.json", strategy_alpha_pnl=-1.0, virtual_fills=1)
    out = tmp_path / "quality_gate.json"

    code = main(
        [
            "evaluate-quality-gate",
            "--summary",
            str(summary),
            "--recording-inspection",
            str(inspection),
            "--out",
            str(out),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["ok"] is False
    assert out.exists()
    assert json.loads(out.read_text(encoding="utf-8"))["ok"] is False


def _write_summary(
    path,
    *,
    strategy_alpha_pnl: float,
    virtual_fills: int = 50,
    virtual_orders: int = 1000,
    fill_rate: float = 0.05,
    orders_per_minute: float = 3.0,
    cancels_per_minute: float = 2.0,
):
    return _write_json(
        path,
        {
            "strategy_alpha_pnl": strategy_alpha_pnl,
            "virtual_fills": virtual_fills,
            "virtual_orders": virtual_orders,
            "fill_rate": fill_rate,
            "orders_per_minute": orders_per_minute,
            "cancels_per_minute": cancels_per_minute,
            "fill_per_active_second": 0.01,
        },
    )


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path
