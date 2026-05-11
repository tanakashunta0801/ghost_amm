from ghost_amm.config import Config
from ghost_amm.exchange.bitbank_rules import BitbankStatus, fallback_btc_jpy_spec
from ghost_amm.execution.live_gates import evaluate_live_order_gates
from ghost_amm.execution.order_state import OrderIntent
from ghost_amm.market.orderbook import OrderBook
from ghost_amm.risk.kernel import RiskDecision


def test_bitbank_live_execution_blocked_unless_all_gates_pass() -> None:
    cfg = Config()
    book = OrderBook("bitbank", "BTC/JPY")
    book.apply_snapshot({"bids": [["100", "1"]], "asks": [["102", "1"]]}, 1, 1)
    result = evaluate_live_order_gates(
        config=cfg,
        intent=OrderIntent(venue="bitbank", pair="btc_jpy", symbol="BTC/JPY", side="buy", price=99, amount=0.001),
        pair_spec=fallback_btc_jpy_spec(),
        status=BitbankStatus("btc_jpy", "NORMAL", 0.0001),
        book=book,
        risk=RiskDecision(True, True, True, 0.01),
        clock_drift_ms=0,
        env={"GHOST_AMM_ENABLE_LIVE": "I_ACCEPT_RISK", "BITBANK_API_KEY": "k", "BITBANK_API_SECRET": "s"},
    )
    assert not result.allowed
    assert result.reason == "execution_mode_not_live"


def test_bitbank_status_not_normal_blocks_live_gates() -> None:
    cfg = Config({"execution": {"mode": "live", "enable_live_orders": True}})
    book = OrderBook("bitbank", "BTC/JPY")
    book.apply_snapshot({"bids": [["100", "1"]], "asks": [["102", "1"]]}, 1, 1)
    result = evaluate_live_order_gates(
        config=cfg,
        intent=OrderIntent(venue="bitbank", pair="btc_jpy", symbol="BTC/JPY", side="buy", price=99, amount=0.001),
        pair_spec=fallback_btc_jpy_spec(),
        status=BitbankStatus("btc_jpy", "SUSPENDED", 0.0001),
        book=book,
        risk=RiskDecision(True, True, True, 0.01),
        clock_drift_ms=0,
        env={"GHOST_AMM_ENABLE_LIVE": "I_ACCEPT_RISK", "BITBANK_API_KEY": "k", "BITBANK_API_SECRET": "s"},
    )
    assert not result.allowed
    assert result.reason == "bitbank_status_not_normal"
