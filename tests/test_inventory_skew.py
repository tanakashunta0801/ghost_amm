from ghost_amm.amm.inventory import InventoryState


def test_inventory_skew_calculation() -> None:
    inventory = InventoryState(base_qty=1, quote_qty=100, target_base_ratio=0.5)
    snap = inventory.snapshot(100)
    assert snap["equity"] == 200
    assert snap["base_ratio"] == 0.5
    assert snap["skew"] == 0

    overweight = InventoryState(base_qty=2, quote_qty=0, target_base_ratio=0.5)
    assert overweight.skew(100) == 0.5
