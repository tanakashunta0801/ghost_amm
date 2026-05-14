from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from ghost_amm.events import Event, make_event, now_ms
from ghost_amm.exchange.bitbank_public import BitbankPublicClient, pair_spec_event, status_event
from ghost_amm.recorder.base import EventRecorder
from ghost_amm.recorder.bitbank_normalizer import normalize_bitbank_message
from ghost_amm.recorder.jsonl_writer import RotatingJsonlEventWriter


class BitbankPublicRecorder(EventRecorder):
    def __init__(
        self,
        *,
        pair: str = "btc_jpy",
        channels: Iterable[str] | None = None,
        out: str | Path,
        url: str = "wss://stream.bitbank.cc/socket.io/?EIO=4&transport=websocket",
        public_rest_url: str = "https://public.bitbank.cc",
        spot_rest_url: str = "https://api.bitbank.cc/v1",
        max_events: int | None = None,
        timeout_sec: float | None = 60.0,
        fetch_metadata_on_start: bool = True,
        rotate_every_events: int | None = None,
        rotate_every_bytes: int | None = None,
        flush_every_events: int = 1,
        max_reconnects: int = 10,
        reconnect_delay_sec: float = 3.0,
        heartbeat_interval_sec: float | None = 60.0,
        max_idle_sec: float | None = 300.0,
    ) -> None:
        self.pair = pair
        self.channels = list(channels or [f"ticker_{pair}", f"transactions_{pair}", f"depth_whole_{pair}", f"depth_diff_{pair}"])
        self.out = Path(out)
        self.url = url
        self.public_rest_url = public_rest_url
        self.spot_rest_url = spot_rest_url
        self.max_events = max_events
        self.timeout_sec = timeout_sec
        self.fetch_metadata_on_start = fetch_metadata_on_start
        self.rotate_every_events = rotate_every_events
        self.rotate_every_bytes = rotate_every_bytes
        self.flush_every_events = flush_every_events
        self.max_reconnects = max_reconnects
        self.reconnect_delay_sec = reconnect_delay_sec
        self.heartbeat_interval_sec = heartbeat_interval_sec
        self.max_idle_sec = max_idle_sec
        self.events: list[Event] = []
        self.output_paths: list[Path] = []

    async def run(self) -> None:
        try:
            import socketio  # type: ignore
        except ModuleNotFoundError as exc:
            raise RuntimeError("python-socketio is optional; install ghost-amm[full] for public stream recording") from exc

        done = asyncio.Event()
        started_ms = now_ms()
        with RotatingJsonlEventWriter(
            self.out,
            rotate_every_events=self.rotate_every_events,
            rotate_every_bytes=self.rotate_every_bytes,
            flush_every_events=self.flush_every_events,
        ) as writer:
            if self.fetch_metadata_on_start:
                for event in self._metadata_events():
                    self._record(event, writer)
            reconnects = 0
            while not done.is_set():
                if self.timeout_sec is not None and now_ms() - started_ms >= self.timeout_sec * 1000:
                    break
                sio = socketio.AsyncClient(logger=False, engineio_logger=False, reconnection=False)
                last_message_ms = {"value": now_ms()}
                idle = asyncio.Event()

                @sio.event
                async def connect() -> None:
                    last_message_ms["value"] = now_ms()
                    for channel in self.channels:
                        await sio.emit("join-room", channel)
                    self._record(
                        make_event(
                            "dry_run_heartbeat",
                            ts_exchange=now_ms(),
                            venue="bitbank",
                            symbol=self.pair.upper().replace("_", "/"),
                            payload={"mode": "record_bitbank_public", "heartbeat_type": "connect", "connected": True, "reconnects": reconnects},
                        ),
                        writer,
                    )

                @sio.event
                async def disconnect() -> None:
                    self._record(
                        make_event(
                            "dry_run_heartbeat",
                            ts_exchange=now_ms(),
                            venue="bitbank",
                            symbol=self.pair.upper().replace("_", "/"),
                            payload={"mode": "record_bitbank_public", "heartbeat_type": "disconnect", "connected": False, "reconnects": reconnects},
                        ),
                        writer,
                    )

                @sio.on("message")
                async def message(data: object = None) -> None:
                    if not isinstance(data, dict):
                        return
                    room_name = str(data.get("room_name") or data.get("room") or "")
                    if not room_name:
                        return
                    last_message_ms["value"] = now_ms()
                    for event in normalize_bitbank_message(room_name, data):
                        self._record(event, writer)
                    if self.max_events is not None and writer.total_events >= self.max_events:
                        done.set()

                try:
                    await sio.connect(_socketio_base_url(self.url), transports=["websocket"])
                    heartbeat_task = asyncio.create_task(self._heartbeat_loop(done, writer, reconnects))
                    idle_task = asyncio.create_task(self._idle_watchdog_loop(done, idle, sio, writer, reconnects, last_message_ms))
                    wait_timeout = None
                    if self.timeout_sec is not None:
                        elapsed_sec = (now_ms() - started_ms) / 1000
                        wait_timeout = max(self.timeout_sec - elapsed_sec, 0.001)
                    wait_tasks = [asyncio.create_task(done.wait()), asyncio.create_task(idle.wait())]
                    completed, pending = await asyncio.wait(wait_tasks, timeout=wait_timeout, return_when=asyncio.FIRST_COMPLETED)
                    for task in pending:
                        task.cancel()
                    for task in pending:
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                    if not completed:
                        raise asyncio.TimeoutError
                except asyncio.TimeoutError:
                    break
                except Exception as exc:
                    self._record(
                        make_event(
                            "risk_state",
                            ts_exchange=now_ms(),
                            venue="bitbank",
                            symbol=self.pair.upper().replace("_", "/"),
                            payload={
                                "allow_quote": False,
                                "allow_buy": False,
                                "allow_sell": False,
                                "reason": f"recording_connection_error:{type(exc).__name__}",
                                "reconnects": reconnects,
                            },
                        ),
                        writer,
                    )
                finally:
                    if "heartbeat_task" in locals():
                        heartbeat_task.cancel()
                        try:
                            await heartbeat_task
                        except asyncio.CancelledError:
                            pass
                        del heartbeat_task
                    if "idle_task" in locals():
                        idle_task.cancel()
                        try:
                            await idle_task
                        except asyncio.CancelledError:
                            pass
                        del idle_task
                    if sio.connected:
                        await sio.disconnect()

                if done.is_set():
                    break
                reconnects += 1
                if reconnects > self.max_reconnects:
                    self._record(
                        make_event(
                            "risk_state",
                            ts_exchange=now_ms(),
                            venue="bitbank",
                            symbol=self.pair.upper().replace("_", "/"),
                            payload={
                                "allow_quote": False,
                                "allow_buy": False,
                                "allow_sell": False,
                                "reason": "recording_max_reconnects_exceeded",
                                "reconnects": reconnects,
                            },
                        ),
                        writer,
                    )
                    break
                await asyncio.sleep(self.reconnect_delay_sec)
            self.output_paths = writer.paths

    def _record(self, event: Event, writer: RotatingJsonlEventWriter) -> None:
        self.events.append(event)
        writer.write(event)

    async def _heartbeat_loop(self, done: asyncio.Event, writer: RotatingJsonlEventWriter, reconnects: int) -> None:
        interval = self.heartbeat_interval_sec
        if interval is None or interval <= 0:
            return
        while not done.is_set():
            await asyncio.sleep(interval)
            if done.is_set():
                return
            self._record(
                make_event(
                    "dry_run_heartbeat",
                    ts_exchange=now_ms(),
                    venue="bitbank",
                    symbol=self.pair.upper().replace("_", "/"),
                    payload={
                        "mode": "record_bitbank_public",
                        "heartbeat_type": "periodic",
                        "connected": True,
                        "reconnects": reconnects,
                        "heartbeat_interval_sec": interval,
                    },
                ),
                writer,
            )

    async def _idle_watchdog_loop(
        self,
        done: asyncio.Event,
        idle: asyncio.Event,
        sio: Any,
        writer: RotatingJsonlEventWriter,
        reconnects: int,
        last_message_ms: dict[str, int],
    ) -> None:
        max_idle_sec = self.max_idle_sec
        if max_idle_sec is None or max_idle_sec <= 0:
            return
        check_interval = max(0.001, min(max_idle_sec / 2, 30.0))
        while not done.is_set() and not idle.is_set():
            await asyncio.sleep(check_interval)
            idle_ms = now_ms() - last_message_ms["value"]
            if idle_ms < max_idle_sec * 1000:
                continue
            self._record(
                make_event(
                    "risk_state",
                    ts_exchange=now_ms(),
                    venue="bitbank",
                    symbol=self.pair.upper().replace("_", "/"),
                    payload={
                        "allow_quote": False,
                        "allow_buy": False,
                        "allow_sell": False,
                        "reason": "recording_idle_timeout",
                        "idle_ms": idle_ms,
                        "max_idle_sec": max_idle_sec,
                        "reconnects": reconnects,
                    },
                ),
                writer,
            )
            idle.set()
            if getattr(sio, "connected", False):
                await sio.disconnect()
            return

    def _metadata_events(self) -> list[Event]:
        ts = now_ms()
        symbol = self.pair.upper().replace("_", "/")
        client = BitbankPublicClient(public_base_url=self.public_rest_url, spot_base_url=self.spot_rest_url)
        try:
            specs = client.fetch_pairs()
            statuses = client.fetch_statuses()
        except Exception as exc:
            return [
                make_event(
                    "risk_state",
                    ts_exchange=ts,
                    venue="bitbank",
                    symbol=symbol,
                    payload={
                        "allow_quote": False,
                        "allow_buy": False,
                        "allow_sell": False,
                        "reason": f"metadata_fetch_failed:{type(exc).__name__}",
                    },
                )
            ]
        events: list[Event] = []
        for spec in specs:
            if spec.name == self.pair:
                events.append(pair_spec_event(spec, ts_ms=ts, symbol=symbol))
                break
        for status in statuses:
            if status.pair == self.pair:
                events.append(status_event(status, ts_ms=ts + 1, symbol=symbol))
                break
        if not events:
            events.append(
                make_event(
                    "risk_state",
                    ts_exchange=ts,
                    venue="bitbank",
                    symbol=symbol,
                    payload={
                        "allow_quote": False,
                        "allow_buy": False,
                        "allow_sell": False,
                        "reason": "metadata_pair_or_status_missing",
                    },
                )
            )
        return events


def _socketio_base_url(url: str) -> str:
    parsed = urlparse(url)
    scheme = "https" if parsed.scheme in {"wss", "ws"} else parsed.scheme
    return f"{scheme}://{parsed.netloc}" if parsed.netloc else url
