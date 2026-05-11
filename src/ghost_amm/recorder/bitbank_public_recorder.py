from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from ghost_amm.events import Event, write_jsonl
from ghost_amm.recorder.base import EventRecorder
from ghost_amm.recorder.bitbank_normalizer import normalize_bitbank_message


class BitbankPublicRecorder(EventRecorder):
    def __init__(
        self,
        *,
        pair: str = "btc_jpy",
        channels: Iterable[str] | None = None,
        out: str | Path,
        url: str = "wss://stream.bitbank.cc/socket.io/?EIO=4&transport=websocket",
        max_events: int | None = None,
        timeout_sec: float | None = 60.0,
    ) -> None:
        self.pair = pair
        self.channels = list(channels or [f"ticker_{pair}", f"transactions_{pair}", f"depth_whole_{pair}", f"depth_diff_{pair}"])
        self.out = Path(out)
        self.url = url
        self.max_events = max_events
        self.timeout_sec = timeout_sec
        self.events: list[Event] = []

    async def run(self) -> None:
        try:
            import socketio  # type: ignore
        except ModuleNotFoundError as exc:
            raise RuntimeError("python-socketio is optional; install ghost-amm[full] for public stream recording") from exc

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
            if not room_name:
                return
            self.events.extend(normalize_bitbank_message(room_name, data))
            if self.max_events is not None and len(self.events) >= self.max_events:
                done.set()

        await sio.connect(_socketio_base_url(self.url), transports=["websocket"])
        try:
            if self.timeout_sec is None:
                await done.wait()
            else:
                await asyncio.wait_for(done.wait(), timeout=self.timeout_sec)
        except asyncio.TimeoutError:
            pass
        finally:
            await sio.disconnect()
            write_jsonl(self.out, self.events)


def _socketio_base_url(url: str) -> str:
    parsed = urlparse(url)
    scheme = "https" if parsed.scheme in {"wss", "ws"} else parsed.scheme
    return f"{scheme}://{parsed.netloc}" if parsed.netloc else url
