from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "symbol": "BTC/JPY",
    "venue": "synthetic_bitbank",
    "market_type": "spot",
    "pair": "btc_jpy",
    "replay": {
        "order": "arrival_order",
        "strict_sequence": True,
        "allow_exchange_time_sort": False,
    },
    "bitbank": {
        "public_ws_url": "wss://stream.bitbank.cc/socket.io/?EIO=4&transport=websocket",
        "public_rest_url": "https://public.bitbank.cc",
        "private_rest_url": "https://api.bitbank.cc/v1",
        "pair": "btc_jpy",
        "channels": [
            "ticker_btc_jpy",
            "transactions_btc_jpy",
            "depth_whole_btc_jpy",
            "depth_diff_btc_jpy",
        ],
        "require_status_normal": True,
        "require_post_only": True,
        "sequence_policy": "monotonic_not_consecutive",
        "block_on_crossed_book": True,
        "clock_drift_limit_ms": 1000,
    },
    "ccxt": {
        "enabled": True,
        "exchange_id": "bitbank",
        "public_rest_only_in_mvp": True,
        "allow_private_calls": False,
        "allow_order_submission": False,
        "forbid_withdrawal_methods": True,
    },
    "execution": {
        "mode": "replay",
        "venue": "bitbank",
        "enable_live_orders": False,
        "post_only_only": True,
        "unmanaged_open_orders_present": False,
        "confirm_api_key_no_withdrawal_permission": False,
        "positive_quality_gate_passed": False,
        "live_env_var_name": "GHOST_AMM_ENABLE_LIVE",
        "live_env_var_value": "I_ACCEPT_RISK",
        "max_active_orders_per_pair": 20,
        "quote_ttl_ms": 3000,
        "min_quote_replace_interval_ms": 0,
        "quote_replace_threshold_bps": 0,
        "size_replace_threshold_ratio": 0,
    },
    "market": {
        "stale_after_ms": 3000,
        "max_spread_bps": 50,
        "min_depth_20bps_jpy": 5_000_000,
        "reject_circuit_break_book": True,
    },
    "fair": {
        "min_source_count": 1,
        "max_source_age_ms": 3000,
        "max_source_deviation_bps": 80,
        "use_median": True,
    },
    "inventory": {
        "initial_base_qty": 0.01,
        "initial_quote_qty": 150_000,
        "target_base_ratio": 0.5,
        "max_abs_skew": 0.35,
        "negative_balances_allowed": False,
    },
    "amm": {
        "levels": 6,
        "base_order_size": 0.001,
        "half_spread_bps": 8,
        "step_bps": 10,
        "skew_strength_bps": 80,
        "size_skew_strength": 3.0,
        "min_order_size_fallback": 0.0001,
        "max_order_size": 0.002,
        "tick_size_fallback_jpy": 1,
        "lot_size_fallback_btc": 0.0001,
        "use_bitbank_pair_spec_rounding": True,
    },
    "shock": {
        "forced_flow_window_ms": 5000,
        "depth_bps": 20,
        "threshold": 1.0,
        "temperature": 1.5,
        "minimum_wait_after_shock_ms": 2000,
        "activation_decay_ms": 30000,
        "min_activation_to_quote": 0.15,
        "opposite_side_activation_ratio": 0.0,
    },
    "fill_model": {
        "queue_ahead_multiplier": 1.5,
        "maker_fee_bps_fallback": 0,
        "taker_fee_bps_fallback": 10,
        "latency_ms": 150,
        "cancel_latency_ms": 150,
        "min_resting_time_ms": 500,
    },
    "fee": {
        "maker_fee_source": "bitbank_pair_spec",
        "negative_maker_fee_policy": "clamp_to_zero",
    },
    "risk": {
        "max_drawdown_pct": 5,
        "max_daily_loss_pct": 3,
        "max_virtual_fills_per_minute": 20,
        "max_same_side_fills_per_window": 3,
        "fill_burst_window_ms": 10000,
        "fill_burst_cooldown_ms": 60000,
        "max_base_qty": 0,
        "max_quote_usage_jpy": 0,
        "max_inventory_notional_jpy": 0,
        "max_one_side_inventory_change_jpy_per_minute": 0,
        "max_fair_drop_bps_1s_for_bid": 0,
        "max_fair_rise_bps_1s_for_ask": 0,
        "max_fair_drop_bps_5s_for_bid": 0,
        "max_fair_rise_bps_5s_for_ask": 0,
        "max_last_trade_fair_deviation_bps": 0,
        "last_trade_fair_deviation_max_age_ms": 3000,
        "block_on_sequence_ordering_violation": True,
        "block_on_bitbank_status_not_normal": True,
        "block_on_pair_stop_flags": True,
        "block_on_unfetched_pair_spec": True,
    },
}


class Config:
    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self.data = deep_merge(DEFAULT_CONFIG, data or {})

    def get(self, path: str, default: Any = None) -> Any:
        cur: Any = self.data
        for key in path.split("."):
            if not isinstance(cur, dict) or key not in cur:
                return default
            cur = cur[key]
        return cur

    def section(self, name: str) -> dict[str, Any]:
        value = self.data.get(name, {})
        return value if isinstance(value, dict) else {}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str | Path | None = None) -> Config:
    if path is None:
        return Config()
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    text = config_path.read_text(encoding="utf-8")
    parsed = parse_yaml(text)
    return Config(parsed)


def parse_yaml(text: str) -> dict[str, Any]:
    try:
        import yaml  # type: ignore

        loaded = yaml.safe_load(text) or {}
        if not isinstance(loaded, dict):
            raise ValueError("YAML root must be a mapping")
        return loaded
    except ModuleNotFoundError:
        return _parse_simple_yaml(text)


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]
    pending_key: tuple[int, dict[str, Any], str] | None = None

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        item = line.strip()

        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]

        if item.startswith("- "):
            if pending_key and pending_key[0] == indent:
                _, mapping, key = pending_key
                mapping[key] = []
                stack.append((indent - 1, mapping[key]))
                parent = mapping[key]
                pending_key = None
            if not isinstance(parent, list):
                raise ValueError(f"YAML list item without list parent: {raw_line}")
            parent.append(_parse_scalar(item[2:].strip()))
            continue

        if ":" not in item:
            raise ValueError(f"Unsupported YAML line: {raw_line}")
        key, value = item.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not isinstance(parent, dict):
            raise ValueError(f"YAML mapping item without mapping parent: {raw_line}")
        if value == "":
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
            pending_key = (indent + 2, parent, key)
        else:
            parent[key] = _parse_scalar(value)
            pending_key = None
    return root


def _parse_scalar(value: str) -> Any:
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    lower = value.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if lower == "null":
        return None
    try:
        if any(ch in value for ch in [".", "e", "E"]):
            return float(value)
        return int(value)
    except ValueError:
        return value
