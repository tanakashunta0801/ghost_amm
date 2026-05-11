from ghost_amm.exchange.bitbank_rules import BitbankPairSpec, BitbankStatus


def test_bitbank_pair_metadata_validation_and_precision() -> None:
    spec = BitbankPairSpec(
        name="btc_jpy",
        base_asset="btc",
        quote_asset="jpy",
        unit_amount=0.0001,
        limit_max_amount=100,
        price_digits=0,
        amount_digits=4,
        is_enabled=True,
    )
    assert spec.round_price(123.9) == 123
    assert spec.round_amount(0.123456) == 0.1234
    assert spec.validate_order(side="buy", price=123, amount=0.1234) == (True, None)
    assert spec.validate_order(side="buy", price=123.1, amount=0.1234)[1] == "price_precision_invalid"
    assert spec.validate_order(side="buy", price=123, amount=0.00001)[1] == "amount_below_unit_amount"


def test_bitbank_status_normal() -> None:
    assert BitbankStatus(pair="btc_jpy", status="NORMAL", min_amount=0.0001).is_normal
    assert not BitbankStatus(pair="btc_jpy", status="SUSPENDED", min_amount=0.0001).is_normal
