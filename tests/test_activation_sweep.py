from ghost_amm.analytics.sweep import run_activation_sweep
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
