from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict

from ghost_amm.analytics.metrics import summarize
from ghost_amm.analytics.report import write_report
from ghost_amm.config import Config, load_config
from ghost_amm.dryrun.public_stream_engine import PublicStreamDryRunEngine
from ghost_amm.events import read_jsonl, write_jsonl
from ghost_amm.exchange.bitbank_public import BitbankPublicClient, cache_pair_rules
from ghost_amm.exchange.ccxt_gateway import CcxtGateway, CcxtGatewayBlocked, CcxtGatewayConfig, CcxtGatewayError
from ghost_amm.recorder.bitbank_public_recorder import BitbankPublicRecorder
from ghost_amm.recorder.inspection import inspect_recording
from ghost_amm.recorder.mock_recorder import generate_synthetic_events
from ghost_amm.replay.engine import ReplayEngine


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ghost-amm")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("generate-synthetic")
    p.add_argument("--scenario", default="sell_shock")
    p.add_argument("--venue", default="synthetic_bitbank")
    p.add_argument("--pair", default="btc_jpy")
    p.add_argument("--out", required=True)

    p = sub.add_parser("replay")
    p.add_argument("--events", required=True)
    p.add_argument("--config", default="configs/default.yaml")
    p.add_argument("--out", required=True)

    p = sub.add_parser("report")
    p.add_argument("--replay", required=True)
    p.add_argument("--config", default="configs/default.yaml")
    p.add_argument("--out", required=True)

    p = sub.add_parser("record-bitbank-public")
    p.add_argument("--pair", default="btc_jpy")
    p.add_argument("--config", default="configs/default.yaml")
    p.add_argument("--channels", default="ticker,transactions,depth_whole,depth_diff")
    p.add_argument("--out", required=True)
    p.add_argument("--max-events", type=int, default=None)
    p.add_argument("--timeout-sec", type=float, default=60.0)
    p.add_argument("--rotate-every-events", type=int, default=None)
    p.add_argument("--rotate-every-bytes", type=int, default=None)
    p.add_argument("--flush-every-events", type=int, default=1)
    p.add_argument("--max-reconnects", type=int, default=10)
    p.add_argument("--reconnect-delay-sec", type=float, default=3.0)
    p.add_argument("--no-metadata", action="store_true")

    p = sub.add_parser("dry-run-bitbank-public")
    p.add_argument("--pair", default="btc_jpy")
    p.add_argument("--config", default="configs/default.yaml")
    p.add_argument("--out", required=True)
    p.add_argument("--max-events", type=int, default=None)
    p.add_argument("--timeout-sec", type=float, default=60.0)

    p = sub.add_parser("ccxt-smoke-test")
    p.add_argument("--exchange", default="bitbank")
    p.add_argument("--symbol", default="BTC/JPY")
    p.add_argument("--public-only", action="store_true")

    p = sub.add_parser("validate-bitbank-rules")
    p.add_argument("--pair", default="btc_jpy")
    p.add_argument("--config", default="configs/default.yaml")
    p.add_argument("--cache", default="data/replay/bitbank_pair_rules.json")

    p = sub.add_parser("inspect-recording")
    p.add_argument("events", nargs="+")
    p.add_argument("--strict", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "generate-synthetic":
        events = generate_synthetic_events(args.scenario, args.venue, args.pair)
        write_jsonl(args.out, events)
        print(json.dumps({"events": len(events), "out": args.out}, sort_keys=True))
        return 0

    if args.command == "replay":
        config = load_config(args.config)
        engine = ReplayEngine(config)
        output = engine.run_file(args.events, args.out)
        fills = sum(1 for event in output if event.event_type == "virtual_fill")
        orders = sum(1 for event in output if event.event_type == "virtual_order_placed")
        print(json.dumps({"events": len(output), "virtual_orders": orders, "virtual_fills": fills, "out": args.out}, sort_keys=True))
        return 0

    if args.command == "report":
        config = load_config(args.config)
        events = read_jsonl(args.replay)
        fair = _last_fair(events)
        inv_cfg = config.section("inventory")
        summary = summarize(events, initial_base=float(inv_cfg["initial_base_qty"]), initial_quote=float(inv_cfg["initial_quote_qty"]), last_fair=fair)
        write_report(args.out, events, summary)
        print(json.dumps({"out": args.out}, sort_keys=True))
        return 0

    if args.command == "record-bitbank-public":
        config = load_config(args.config)
        channels = _expand_channels(args.channels, args.pair)
        recorder = BitbankPublicRecorder(
            pair=args.pair,
            channels=channels,
            out=args.out,
            url=str(config.get("bitbank.public_ws_url")),
            public_rest_url=str(config.get("bitbank.public_rest_url")),
            spot_rest_url=str(config.get("bitbank.private_rest_url")),
            max_events=args.max_events,
            timeout_sec=args.timeout_sec,
            fetch_metadata_on_start=not args.no_metadata,
            rotate_every_events=args.rotate_every_events,
            rotate_every_bytes=args.rotate_every_bytes,
            flush_every_events=args.flush_every_events,
            max_reconnects=args.max_reconnects,
            reconnect_delay_sec=args.reconnect_delay_sec,
        )
        asyncio.run(recorder.run())
        print(json.dumps({"events": len(recorder.events), "out": args.out, "files": [str(path) for path in recorder.output_paths]}, sort_keys=True))
        return 0

    if args.command == "dry-run-bitbank-public":
        config = load_config(args.config)
        engine = PublicStreamDryRunEngine(config=config, pair=args.pair, out=args.out, max_events=args.max_events, timeout_sec=args.timeout_sec)
        events = asyncio.run(engine.run())
        print(json.dumps({"events": len(events), "out": args.out}, sort_keys=True))
        return 0

    if args.command == "ccxt-smoke-test":
        gateway = CcxtGateway(CcxtGatewayConfig(exchange_id=args.exchange))
        try:
            ticker = gateway.fetch_ticker(args.symbol)
            book = gateway.fetch_order_book(args.symbol, limit=5)
            print(json.dumps({"ticker": _compact(ticker), "order_book": _compact(book)}, default=str, sort_keys=True))
            return 0
        except (CcxtGatewayError, CcxtGatewayBlocked) as exc:
            print(json.dumps({"blocked_or_unavailable": str(exc)}, sort_keys=True))
            return 2

    if args.command == "validate-bitbank-rules":
        config = load_config(args.config)
        client = BitbankPublicClient(
            public_base_url=str(config.get("bitbank.public_rest_url")),
            spot_base_url=str(config.get("bitbank.private_rest_url")),
        )
        specs = client.fetch_pairs()
        statuses = client.fetch_statuses()
        cache_pair_rules(args.cache, specs, statuses)
        spec = next((item for item in specs if item.name == args.pair), None)
        status = next((item for item in statuses if item.pair == args.pair), None)
        if not spec or not status:
            print(json.dumps({"ok": False, "reason": "pair_or_status_missing", "cache": args.cache}, sort_keys=True))
            return 1
        result = {
            "ok": spec.is_enabled and status.is_normal and not spec.stop_order and not spec.stop_order_and_cancel,
            "pair": asdict(spec),
            "status": asdict(status),
            "cache": args.cache,
        }
        print(json.dumps(result, sort_keys=True))
        return 0 if result["ok"] else 1

    if args.command == "inspect-recording":
        result = inspect_recording(args.events, strict=args.strict)
        print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))
        return 0 if result.ok_for_replay else 1

    return 1


def _expand_channels(channels: str, pair: str) -> list[str]:
    expanded = []
    for channel in channels.split(","):
        channel = channel.strip()
        if "_" in channel and channel.endswith(pair):
            expanded.append(channel)
        else:
            expanded.append(f"{channel}_{pair}")
    return expanded


def _compact(value: object) -> object:
    if isinstance(value, dict):
        return {key: value[key] for key in list(value)[:10]}
    return value


def _last_fair(events: list) -> float | None:
    for event in reversed(events):
        if event.event_type == "mark_price" and event.payload.get("fair") is not None:
            return float(event.payload["fair"])
    return None


if __name__ == "__main__":
    raise SystemExit(main())
