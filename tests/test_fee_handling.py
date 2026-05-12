from dataclasses import asdict

from ghost_amm.config import Config
from ghost_amm.events import make_event
from ghost_amm.exchange.bitbank_rules import BitbankPairSpec
from ghost_amm.pipeline import GhostAmmPipeline


def _pair_spec(maker_fee_rate_quote: float) -> BitbankPairSpec:
    return BitbankPairSpec(
        name="btc_jpy",
        base_asset="btc",
        quote_asset="jpy",
        unit_amount=0.0001,
        limit_max_amount=100,
        price_digits=0,
        amount_digits=4,
        maker_fee_rate_quote=maker_fee_rate_quote,
        is_enabled=True,
    )


def test_pair_spec_maker_fee_overrides_fallback_fee() -> None:
    pipeline = GhostAmmPipeline(Config({"fill_model": {"maker_fee_bps_fallback": 5}}))

    pipeline.process(
        make_event(
            "bitbank_pair_spec",
            ts_exchange=1,
            venue="bitbank",
            symbol="BTC/JPY",
            payload=asdict(_pair_spec(0.001)),
        )
    )

    assert pipeline.fill_model.maker_fee_bps == 10


def test_negative_maker_fee_clamps_to_zero_by_default() -> None:
    pipeline = GhostAmmPipeline(Config({"fill_model": {"maker_fee_bps_fallback": 5}}))

    pipeline.process(
        make_event(
            "bitbank_pair_spec",
            ts_exchange=1,
            venue="bitbank",
            symbol="BTC/JPY",
            payload=asdict(_pair_spec(-0.0002)),
        )
    )

    assert pipeline.fill_model.maker_fee_bps == 0


def test_negative_maker_fee_can_be_treated_as_rebate() -> None:
    pipeline = GhostAmmPipeline(
        Config(
            {
                "fill_model": {"maker_fee_bps_fallback": 5},
                "fee": {"negative_maker_fee_policy": "allow_rebate"},
            }
        )
    )

    pipeline.process(
        make_event(
            "bitbank_pair_spec",
            ts_exchange=1,
            venue="bitbank",
            symbol="BTC/JPY",
            payload=asdict(_pair_spec(-0.0002)),
        )
    )

    assert pipeline.fill_model.maker_fee_bps == -2
