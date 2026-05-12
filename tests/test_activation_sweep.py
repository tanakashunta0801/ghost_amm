from ghost_amm.analytics.sweep import run_activation_sweep, run_churn_sweep
from ghost_amm.config import Config
from ghost_amm.recorder.mock_recorder import generate_synthetic_events


def test_activation_sweep_writes_summary_outputs(tmp_path) -> None:
    events = generate_synthetic_events("sell_shock", "synthetic_bitbank", "btc_jpy")
    rows = run_activation_sweep(
        base_config=Config(),
        events=events,
        thresholds=[0.1],
        min_activations=[0.01],
        out_dir=tmp_path,
    )
    assert len(rows) == 1
    assert (tmp_path / "activation_sweep.json").exists()
    assert (tmp_path / "activation_sweep.csv").exists()
    assert (tmp_path / "activation_sweep.md").exists()
    assert rows[0]["virtual_orders"] >= 0


def test_churn_sweep_writes_summary_outputs(tmp_path) -> None:
    events = generate_synthetic_events("sell_shock", "synthetic_bitbank", "btc_jpy")
    rows = run_churn_sweep(
        base_config=Config(),
        events=events,
        shock_threshold=0.1,
        min_activation=0.01,
        max_active_orders=[2],
        quote_ttls_ms=[30_000],
        min_replace_intervals_ms=[10_000],
        replace_threshold_bps=2,
        size_replace_threshold_ratio=0.5,
        out_dir=tmp_path,
    )
    assert len(rows) == 1
    assert (tmp_path / "churn_sweep.json").exists()
    assert (tmp_path / "churn_sweep.csv").exists()
    assert (tmp_path / "churn_sweep.md").exists()
    assert rows[0]["max_active_orders"] == 2
