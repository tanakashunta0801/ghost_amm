from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from ghost_amm.events import Event, make_event, write_jsonl
from ghost_amm.exchange.bitbank_rules import BitbankStatus, fallback_btc_jpy_spec
from ghost_amm.recorder.base import EventRecorder


class MockRecorder(EventRecorder):
    def __init__(self, *, scenario: str, venue: str, pair: str, out: str | Path) -> None:
        self.scenario = scenario
        self.venue = venue
        self.pair = pair
        self.out = Path(out)

    async def run(self) -> None:
        write_jsonl(self.out, generate_synthetic_events(self.scenario, self.venue, self.pair))


def generate_synthetic_events(scenario: str = "sell_shock", venue: str = "synthetic_bitbank", pair: str = "btc_jpy") -> list[Event]:
    symbol = pair.upper().replace("_", "/")
    ts = 1_700_000_000_000
    seq = 1
    spec = fallback_btc_jpy_spec()
    status = BitbankStatus(pair=pair, status="NORMAL", min_amount=spec.unit_amount)
    events: list[Event] = [
        make_event(
            "bitbank_pair_spec",
            ts_exchange=ts,
            venue="bitbank",
            symbol=symbol,
            sequence=seq,
            payload=asdict(spec),
        ),
        make_event(
            "bitbank_status",
            ts_exchange=ts + 1,
            venue="bitbank",
            symbol=symbol,
            sequence=seq + 1,
            payload=asdict(status),
        ),
    ]
    seq += 2

    fair = 10_000_000.0
    events.append(_snapshot(ts + 100, venue, symbol, seq, fair=fair, spread=2_000, size=0.8))
    seq += 1
    for i in range(3):
        events.append(_trade(ts + 500 + i * 500, venue, symbol, seq, "buy", fair + 1_000, 0.03))
        seq += 1

    if scenario == "buy_shock":
        shock_side = "buy"
        shock_price = fair + 25_000
        post_fair = fair + 18_000
    else:
        shock_side = "sell"
        shock_price = fair - 25_000
        post_fair = fair - 18_000

    for i in range(4):
        events.append(_trade(ts + 3_000 + i * 250, venue, symbol, seq, shock_side, shock_price, 0.8))
        seq += 1

    events.append(_snapshot(ts + 3_800, venue, symbol, seq, fair=post_fair, spread=18_000, size=0.16))
    seq += 1
    events.append(_snapshot(ts + 5_500, venue, symbol, seq, fair=post_fair + (2_000 if scenario != "buy_shock" else -2_000), spread=3_000, size=0.9))
    seq += 1

    # After the configured wait, the book has rebuilt and quotes can rest before a later trade consumes queue.
    events.append(_snapshot(ts + 6_300, venue, symbol, seq, fair=post_fair + (2_000 if scenario != "buy_shock" else -2_000), spread=3_000, size=0.9))
    seq += 1
    if scenario == "buy_shock":
        events.append(_trade(ts + 7_000, venue, symbol, seq, "buy", post_fair + 15_000, 1.0))
    else:
        events.append(_trade(ts + 7_000, venue, symbol, seq, "sell", post_fair - 15_000, 1.0))
    seq += 1
    events.append(_snapshot(ts + 10_000, venue, symbol, seq, fair=post_fair + 8_000, spread=2_000, size=0.9))
    return events


def write_synthetic(path: str | Path, events: Iterable[Event]) -> None:
    write_jsonl(path, events)


def _snapshot(ts: int, venue: str, symbol: str, seq: int, *, fair: float, spread: float, size: float) -> Event:
    half = spread / 2
    bids = [[str(round(fair - half - i * 5_000)), f"{size:.4f}"] for i in range(20)]
    asks = [[str(round(fair + half + i * 5_000)), f"{size:.4f}"] for i in range(20)]
    return make_event(
        "order_book_snapshot",
        ts_exchange=ts,
        venue=venue,
        symbol=symbol,
        sequence=seq,
        payload={"bids": bids, "asks": asks, "source": "synthetic_depth_whole"},
    )


def _trade(ts: int, venue: str, symbol: str, seq: int, side: str, price: float, amount: float) -> Event:
    return make_event(
        "trade",
        ts_exchange=ts,
        venue=venue,
        symbol=symbol,
        sequence=seq,
        payload={"trade_id": seq, "side": side, "price": price, "amount": amount},
    )
