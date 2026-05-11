from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ghost_amm.events import Event, make_event
from ghost_amm.exchange.bitbank_rules import BitbankPairSpec, BitbankStatus


class BitbankPublicClient:
    def __init__(
        self,
        public_base_url: str = "https://public.bitbank.cc",
        spot_base_url: str = "https://api.bitbank.cc/v1",
        timeout: float = 10.0,
    ) -> None:
        self.public_base_url = public_base_url.rstrip("/")
        self.spot_base_url = spot_base_url.rstrip("/")
        self.timeout = timeout

    def fetch_pairs(self) -> list[BitbankPairSpec]:
        data = self._get_json(self.spot_base_url, "/spot/pairs")
        pairs = _extract_data_list(data, "pairs")
        return [BitbankPairSpec.from_api(pair) for pair in pairs]

    def fetch_statuses(self) -> list[BitbankStatus]:
        data = self._get_json(self.spot_base_url, "/spot/status")
        statuses = _extract_data_list(data, "statuses")
        return [BitbankStatus.from_api(status) for status in statuses]

    def fetch_ticker(self, pair: str) -> dict[str, Any]:
        return self._get_json(self.public_base_url, f"/{pair}/ticker")

    def fetch_order_book(self, pair: str) -> dict[str, Any]:
        return self._get_json(self.public_base_url, f"/{pair}/depth")

    def fetch_trades(self, pair: str) -> dict[str, Any]:
        return self._get_json(self.public_base_url, f"/{pair}/transactions")

    def _get_json(self, base_url: str, path: str) -> dict[str, Any]:
        with urllib.request.urlopen(base_url + path, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))


def pair_spec_event(spec: BitbankPairSpec, *, ts_ms: float, symbol: str = "BTC/JPY") -> Event:
    return make_event("bitbank_pair_spec", ts_exchange=ts_ms, venue="bitbank", symbol=symbol, payload=asdict(spec))


def status_event(status: BitbankStatus, *, ts_ms: float, symbol: str = "BTC/JPY") -> Event:
    return make_event("bitbank_status", ts_exchange=ts_ms, venue="bitbank", symbol=symbol, payload=asdict(status))


def cache_pair_rules(path: str | Path, specs: list[BitbankPairSpec], statuses: list[BitbankStatus]) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "pairs": [asdict(spec) for spec in specs],
        "statuses": [asdict(status) for status in statuses],
    }
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _extract_data_list(response: dict[str, Any], key: str) -> list[dict[str, Any]]:
    data = response.get("data", response)
    if isinstance(data, dict) and key in data:
        return list(data[key])
    if isinstance(data, list):
        return list(data)
    return []
