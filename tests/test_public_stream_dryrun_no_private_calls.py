from ghost_amm.config import Config
from ghost_amm.dryrun.public_stream_engine import PublicStreamDryRunEngine


def test_public_stream_dryrun_requires_no_api_keys_and_uses_public_channels() -> None:
    engine = PublicStreamDryRunEngine(config=Config(), pair="btc_jpy", out="data/reports/test", max_events=1)
    assert "transactions_btc_jpy" in engine.channels
    assert "depth_whole_btc_jpy" in engine.channels
    assert "depth_diff_btc_jpy" in engine.channels
    assert engine.config.get("execution.enable_live_orders") is False
