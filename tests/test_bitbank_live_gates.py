from ghost_amm.config import Config
from ghost_amm.exchange.bitbank_rules import BitbankStatus, fallback_btc_jpy_spec
from ghost_amm.execution.live_gates import evaluate_live_order_gates
from ghost_amm.execution.order_state import OrderIntent
from ghost_amm.market.orderbook import OrderBook
from ghost_amm.recorder.mock_recorder import generate_synthetic_events
from ghost_amm.replay.engine import ReplayEngine
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


def test_pipeline_emits_live_intent_and_blocked_events_without_private_calls() -> None:
    output = ReplayEngine(Config()).run(generate_synthetic_events("sell_shock", "synthetic_bitbank", "btc_jpy"))
    virtual_orders = [event for event in output if event.event_type == "virtual_order_placed"]
    intents = [event for event in output if event.event_type == "live_order_intent"]
    blocked = [event for event in output if event.event_type == "live_order_blocked"]

    assert virtual_orders
    assert len(intents) == len(virtual_orders)
    assert len(blocked) == len(virtual_orders)
    assert blocked[0].payload["reason"] == "execution_mode_not_live"
    assert intents[0].payload["client_order_id"] == virtual_orders[0].payload["order_id"]


def test_pipeline_blocks_even_when_live_gates_pass_in_mvp(monkeypatch) -> None:
    monkeypatch.setenv("GHOST_AMM_ENABLE_LIVE", "I_ACCEPT_RISK")
    monkeypatch.setenv("BITBANK_API_KEY", "k")
    monkeypatch.setenv("BITBANK_API_SECRET", "s")
    cfg = Config({"execution": {"mode": "live", "enable_live_orders": True}})

    output = ReplayEngine(cfg).run(generate_synthetic_events("sell_shock", "bitbank", "btc_jpy"))
    blocked = [event for event in output if event.event_type == "live_order_blocked"]

    assert blocked
    assert all(event.payload["reason"] == "mvp_live_submission_disabled" for event in blocked)
