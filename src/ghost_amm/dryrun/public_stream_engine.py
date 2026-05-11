from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from ghost_amm.config import Config
from ghost_amm.events import Event, make_event, now_ms, write_jsonl
from ghost_amm.exchange.bitbank_public import BitbankPublicClient, pair_spec_event, status_event
from ghost_amm.pipeline import GhostAmmPipeline
from ghost_amm.recorder.bitbank_normalizer import normalize_bitbank_message


class PublicStreamDryRunEngine:
    def __init__(
        self,
        *,
        config: Config,
        pair: str,
        out: str | Path,
        channels: Iterable[str] | None = None,
        max_events: int | None = None,
        timeout_sec: float | None = 60.0,
    ) -> None:
        self.config = config
        self.pair = pair
        self.channels = list(channels or [f"ticker_{pair}", f"transactions_{pair}", f"depth_whole_{pair}", f"depth_diff_{pair}"])
        self.out = Path(out)
        self.max_events = max_events
        self.timeout_sec = timeout_sec
        self.pipeline = GhostAmmPipeline(config)
        self.events: list[Event] = []

    async def run(self) -> list[Event]:
        try:
            import socketio  # type: ignore
        except ModuleNotFoundError as exc:
            raise RuntimeError("python-socketio is optional; install ghost-amm[full] for public dry-run") from exc

        self._prime_metadata()
        url = _socketio_base_url(str(self.config.get("bitbank.public_ws_url")))
        sio = socketio.AsyncClient(logger=False, engineio_logger=False)
        done = asyncio.Event()

        @sio.event
        async def connect() -> None:
            for channel in self.channels:
                await sio.emit("join-room", channel)

        @sio.on("message")
        async def message(data: object = None) -> None:
            if not isinstance(data, dict):
                return
            room_name = str(data.get("room_name") or data.get("room") or "")
            for event in normalize_bitbank_message(room_name, data):
                self.events.append(event)
                self.events.extend(self.pipeline.process(event))
            if self.max_events is not None and len(self.events) >= self.max_events:
                done.set()

        await sio.connect(url, transports=["websocket"])
        heartbeat = make_event(
            "dry_run_heartbeat",
            ts_exchange=now_ms(),
            venue="bitbank",
            symbol=self.pair.upper().replace("_", "/"),
            payload={"mode": "dry_run_public", "private_endpoints": "disabled"},
        )
        self.events.append(heartbeat)
        try:
            if self.timeout_sec is None:
                await done.wait()
            else:
                await asyncio.wait_for(done.wait(), timeout=self.timeout_sec)
        except asyncio.TimeoutError:
            self.events.append(
                make_event(
                    "dry_run_heartbeat",
                    ts_exchange=now_ms(),
                    venue="bitbank",
                    symbol=self.pair.upper().replace("_", "/"),
                    payload={"mode": "dry_run_public", "timeout": True, "events": len(self.events)},
                )
            )
        finally:
            await sio.disconnect()
        self.out.mkdir(parents=True, exist_ok=True)
        write_jsonl(self.out / "events.jsonl", self.events)
        return self.events

    def _prime_metadata(self) -> None:
        if not self.config.get("bitbank.fetch_pair_spec_on_start", True) and not self.config.get("bitbank.fetch_status_on_start", True):
            return
        client = BitbankPublicClient(
            public_base_url=str(self.config.get("bitbank.public_rest_url")),
            spot_base_url=str(self.config.get("bitbank.private_rest_url")),
        )
        ts = now_ms()
        symbol = self.pair.upper().replace("_", "/")
        try:
            specs = client.fetch_pairs() if self.config.get("bitbank.fetch_pair_spec_on_start", True) else []
            statuses = client.fetch_statuses() if self.config.get("bitbank.fetch_status_on_start", True) else []
        except Exception as exc:
            event = make_event(
                "risk_state",
                ts_exchange=ts,
                venue="bitbank",
                symbol=symbol,
                payload={"allow_quote": False, "allow_buy": False, "allow_sell": False, "reason": f"metadata_fetch_failed:{type(exc).__name__}"},
            )
            self.events.append(event)
            return
        for spec in specs:
            if spec.name == self.pair:
                event = pair_spec_event(spec, ts_ms=ts, symbol=symbol)
                self.events.append(event)
                self.events.extend(self.pipeline.process(event))
        for status in statuses:
            if status.pair == self.pair:
                event = status_event(status, ts_ms=ts + 1, symbol=symbol)
                self.events.append(event)
                self.events.extend(self.pipeline.process(event))


def _socketio_base_url(url: str) -> str:
    parsed = urlparse(url)
    scheme = "https" if parsed.scheme in {"wss", "ws"} else parsed.scheme
    return f"{scheme}://{parsed.netloc}" if parsed.netloc else url
