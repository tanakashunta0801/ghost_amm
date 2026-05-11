from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ghost_amm.events import CcxtRestCallBlocked, make_event


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
