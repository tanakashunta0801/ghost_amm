from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from ghost_amm.events import CcxtRestCallBlocked, Event, make_event


class CcxtGatewayError(RuntimeError):
    pass


class CcxtGatewayBlocked(CcxtGatewayError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class CcxtGatewayConfig:
    exchange_id: str = "bitbank"
    public_rest_only_in_mvp: bool = True
    allow_private_calls: bool = False
    allow_order_submission: bool = False
    use_enable_rate_limit: bool = True


class CcxtGateway:
    def __init__(self, config: CcxtGatewayConfig | None = None) -> None:
        self.config = config or CcxtGatewayConfig()
        self._exchange: Any | None = None

    def load_markets(self) -> Any:
        return self._public_exchange().load_markets()

    def fetch_ticker(self, symbol: str) -> Any:
        return self._public_exchange().fetch_ticker(symbol)

    def fetch_external_btc_usd_jpy_event(
        self,
        *,
        btc_usd_symbol: str = "BTC/USD",
        usd_jpy_symbol: str = "USD/JPY",
        symbol: str = "BTC/JPY",
        ts_ms: float | None = None,
    ) -> Event:
        btc_ticker = self.fetch_ticker(btc_usd_symbol)
        usd_jpy_ticker = self.fetch_ticker(usd_jpy_symbol)
        return external_fair_event_from_tickers(
            btc_ticker,
            usd_jpy_ticker,
            exchange_id=self.config.exchange_id,
            btc_usd_symbol=btc_usd_symbol,
            usd_jpy_symbol=usd_jpy_symbol,
            symbol=symbol,
            ts_ms=ts_ms,
        )

    def fetch_order_book(self, symbol: str, limit: int | None = None) -> Any:
        return self._public_exchange().fetch_order_book(symbol, limit=limit)

    def fetch_trades(self, symbol: str, limit: int | None = None) -> Any:
        return self._public_exchange().fetch_trades(symbol, limit=limit)

    def fetch_balance(self) -> Any:
        raise CcxtGatewayBlocked("ccxt_private_calls_blocked_in_mvp")

    def create_order(self, *args: Any, **kwargs: Any) -> Any:
        raise CcxtGatewayBlocked("ccxt_order_submission_blocked_in_mvp")

    def cancel_order(self, *args: Any, **kwargs: Any) -> Any:
        raise CcxtGatewayBlocked("ccxt_private_calls_blocked_in_mvp")

    def blocked_event(self, reason: str, *, ts_ms: float, symbol: str = "BTC/JPY") -> CcxtRestCallBlocked:
        return make_event(
            "ccxt_rest_call_blocked",
            ts_exchange=ts_ms,
            venue=self.config.exchange_id,
            symbol=symbol,
            payload={"reason": reason},
        )  # type: ignore[return-value]

    def __getattr__(self, name: str) -> Any:
        lowered = name.lower()
        if "withdraw" in lowered:
            raise AttributeError(name)
        if lowered.startswith(("private", "fetch_my", "fetch_open", "fetch_closed")):
            raise CcxtGatewayBlocked("ccxt_private_calls_blocked_in_mvp")
        raise AttributeError(name)

    def _public_exchange(self) -> Any:
        if self._exchange is None:
            try:
                import ccxt  # type: ignore
            except ModuleNotFoundError as exc:
                raise CcxtGatewayError("ccxt is optional; install ghost-amm[full] to use ccxt smoke tests") from exc
            exchange_cls = getattr(ccxt, self.config.exchange_id)
            self._exchange = exchange_cls({"enableRateLimit": self.config.use_enable_rate_limit})
        return self._exchange


def external_fair_event_from_tickers(
    btc_ticker: dict[str, Any],
    usd_jpy_ticker: dict[str, Any],
    *,
    exchange_id: str,
    btc_usd_symbol: str = "BTC/USD",
    usd_jpy_symbol: str = "USD/JPY",
    symbol: str = "BTC/JPY",
    ts_ms: float | None = None,
) -> Event:
    btc_usd, btc_spread_bps = _ticker_mid_or_last(btc_ticker, label=btc_usd_symbol)
    usd_jpy, fx_spread_bps = _ticker_mid_or_last(usd_jpy_ticker, label=usd_jpy_symbol)
    event_ts = ts_ms if ts_ms is not None else _ticker_timestamp_ms(btc_ticker, usd_jpy_ticker)
    spread_parts = [value for value in [btc_spread_bps, fx_spread_bps] if value is not None]
    spread_bps = sum(spread_parts) if spread_parts else None
    return make_event(
        "external_fair_price",
        ts_exchange=event_ts,
        venue=f"ccxt:{exchange_id}",
        symbol=symbol,
        payload={
            "source": "external_btc_usd_jpy",
            "provider": f"ccxt:{exchange_id}",
            "btc_usd_symbol": btc_usd_symbol,
            "usd_jpy_symbol": usd_jpy_symbol,
            "btc_usd": btc_usd,
            "usd_jpy": usd_jpy,
            "fair_jpy": btc_usd * usd_jpy,
            "spread_bps": spread_bps,
            "confidence": 0.8,
        },
    )


def _ticker_mid_or_last(ticker: dict[str, Any], *, label: str) -> tuple[float, float | None]:
    bid = _positive_float(ticker.get("bid"))
    ask = _positive_float(ticker.get("ask"))
    if bid is not None and ask is not None and bid < ask:
        mid = (bid + ask) / 2
        return mid, (ask - bid) / mid * 10_000
    last = _positive_float(ticker.get("last"))
    if last is not None:
        return last, None
    close = _positive_float(ticker.get("close"))
    if close is not None:
        return close, None
    raise CcxtGatewayError(f"ticker_missing_positive_price:{label}")


def _positive_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _ticker_timestamp_ms(*tickers: dict[str, Any]) -> float:
    timestamps = [_positive_float(ticker.get("timestamp")) for ticker in tickers]
    timestamps = [value for value in timestamps if value is not None]
    return max(timestamps) if timestamps else time.time() * 1000
