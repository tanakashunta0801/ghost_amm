from ghost_amm.amm.quote_surface import QuoteSurface


def _surface() -> QuoteSurface:
    return QuoteSurface(
        levels=1,
        base_order_size=1.0,
        half_spread_bps=10,
        step_bps=10,
        skew_strength_bps=100,
        size_skew_strength=2,
        min_order_size=0.0001,
        max_order_size=10,
        tick_size=1,
        lot_size=0.0001,
    )


def test_quote_surface_overweight_moves_asks_closer_and_bids_farther() -> None:
    neutral = _surface().generate(fair=10000, inventory_skew=0, activation=1)
    overweight = _surface().generate(fair=10000, inventory_skew=0.2, activation=1)
    n_bid = next(q for q in neutral if q.side == "buy")
    n_ask = next(q for q in neutral if q.side == "sell")
    o_bid = next(q for q in overweight if q.side == "buy")
    o_ask = next(q for q in overweight if q.side == "sell")
    assert o_bid.price < n_bid.price
    assert o_ask.price < n_ask.price
    assert o_bid.size < n_bid.size
    assert o_ask.size > n_ask.size


def test_quote_surface_underweight_moves_bids_closer_and_asks_farther() -> None:
    neutral = _surface().generate(fair=10000, inventory_skew=0, activation=1)
    underweight = _surface().generate(fair=10000, inventory_skew=-0.2, activation=1)
    n_bid = next(q for q in neutral if q.side == "buy")
    n_ask = next(q for q in neutral if q.side == "sell")
    u_bid = next(q for q in underweight if q.side == "buy")
    u_ask = next(q for q in underweight if q.side == "sell")
    assert u_bid.price > n_bid.price
    assert u_ask.price > n_ask.price
    assert u_bid.size > n_bid.size
    assert u_ask.size < n_ask.size


def test_activation_zero_generates_no_quotes() -> None:
    assert _surface().generate(fair=10000, inventory_skew=0, activation=0) == []
