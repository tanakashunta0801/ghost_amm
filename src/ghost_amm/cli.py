from __future__ import annotations

import argparse
import asyncio
import glob
import json
import sys
from dataclasses import asdict
from pathlib import Path

from ghost_amm.analytics.metrics import summarize
from ghost_amm.analytics.quality_gate import QualityGateThresholds, evaluate_quality_gate, write_quality_gate_result
from ghost_amm.analytics.report import write_report
from ghost_amm.analytics.risk_diagnostics import analyze_risk_blocks, write_risk_diagnostics
from ghost_amm.analytics.sweep import run_activation_sweep, run_churn_sweep
from ghost_amm.config import Config, load_config
from ghost_amm.dryrun.public_stream_engine import PublicStreamDryRunEngine
from ghost_amm.events import read_jsonl, write_jsonl
from ghost_amm.exchange.bitbank_public import BitbankPublicClient, cache_pair_rules
from ghost_amm.exchange.ccxt_gateway import CcxtGateway, CcxtGatewayBlocked, CcxtGatewayConfig, CcxtGatewayError
from ghost_amm.recorder.bitbank_public_recorder import BitbankPublicRecorder
from ghost_amm.recorder.inspection import inspect_recording
from ghost_amm.recorder.mock_recorder import generate_synthetic_events
from ghost_amm.recorder.status import recording_status
from ghost_amm.replay.engine import ReplayEngine
from ghost_amm.system_sleep import SystemSleepPreventer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ghost-amm")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("generate-synthetic")
    p.add_argument("--scenario", default="sell_shock")
    p.add_argument("--venue", default="synthetic_bitbank")
    p.add_argument("--pair", default="btc_jpy")
    p.add_argument("--out", required=True)

    p = sub.add_parser("replay")
    p.add_argument("--events", required=True, nargs="+")
    p.add_argument("--config", default="configs/default.yaml")
    p.add_argument("--out", required=True)
    p.add_argument("--replay-order", choices=["arrival_order", "exchange_time_sort"], default=None)
    p.add_argument("--strict-sequence", action=argparse.BooleanOptionalAction, default=None)

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
    p.add_argument("--heartbeat-interval-sec", type=float, default=60.0)
    p.add_argument("--no-metadata", action="store_true")
    p.add_argument("--prevent-sleep", action="store_true")

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

    p = sub.add_parser("ccxt-fair-snapshot")
    p.add_argument("--exchange", required=True)
    p.add_argument("--btc-usd-symbol", default="BTC/USD")
    p.add_argument("--usd-jpy-symbol", default="USD/JPY")
    p.add_argument("--symbol", default="BTC/JPY")
    p.add_argument("--out", default=None)

    p = sub.add_parser("validate-bitbank-rules")
    p.add_argument("--pair", default="btc_jpy")
    p.add_argument("--config", default="configs/default.yaml")
    p.add_argument("--cache", default="data/replay/bitbank_pair_rules.json")

    p = sub.add_parser("inspect-recording")
    p.add_argument("events", nargs="+")
    p.add_argument("--strict", action="store_true")

    p = sub.add_parser("recording-status")
    p.add_argument("events", nargs="+")
    p.add_argument("--strict", action="store_true")
    p.add_argument("--max-stale-sec", type=float, default=300.0)
    p.add_argument("--min-duration-hours", type=float, default=None)
    p.add_argument("--no-inspect", action="store_true")

    p = sub.add_parser("validate-public-recording")
    p.add_argument("--events", required=True, nargs="+")
    p.add_argument("--config", default="configs/default.yaml")
    p.add_argument("--out", required=True)
    p.add_argument("--strict", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--replay-order", choices=["arrival_order", "exchange_time_sort"], default="arrival_order")
    p.add_argument("--strict-sequence", action=argparse.BooleanOptionalAction, default=None)

    p = sub.add_parser("evaluate-quality-gate")
    p.add_argument("--summary", required=True, nargs="+")
    p.add_argument("--recording-inspection", required=True)
    p.add_argument("--out", default=None)
    p.add_argument("--min-report-count", type=int, default=2)
    p.add_argument("--min-recording-hours", type=float, default=24.0)
    p.add_argument("--min-fills", type=int, default=30)
    p.add_argument("--min-fill-rate", type=float, default=0.001)
    p.add_argument("--min-strategy-alpha-pnl", type=float, default=0.0)
    p.add_argument("--max-orders-per-minute", type=float, default=10.0)
    p.add_argument("--max-cancels-per-minute", type=float, default=10.0)

    p = sub.add_parser("run-public-data-gate")
    p.add_argument("--events", required=True, nargs="+")
    p.add_argument("--configs", required=True, nargs="+")
    p.add_argument("--out", required=True)
    p.add_argument("--strict", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--replay-order", choices=["arrival_order", "exchange_time_sort"], default="arrival_order")
    p.add_argument("--strict-sequence", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--min-report-count", type=int, default=2)
    p.add_argument("--min-recording-hours", type=float, default=24.0)
    p.add_argument("--min-fills", type=int, default=30)
    p.add_argument("--min-fill-rate", type=float, default=0.001)
    p.add_argument("--min-strategy-alpha-pnl", type=float, default=0.0)
    p.add_argument("--max-orders-per-minute", type=float, default=10.0)
    p.add_argument("--max-cancels-per-minute", type=float, default=10.0)
    p.add_argument("--prevent-sleep", action="store_true")

    p = sub.add_parser("analyze-risk-blocks")
    p.add_argument("--events", required=True, nargs="+")
    p.add_argument("--out", required=True)

    p = sub.add_parser("sweep-activation")
    p.add_argument("--events", required=True, nargs="+")
    p.add_argument("--config", default="configs/default.yaml")
    p.add_argument("--thresholds", default="0.003,0.01,0.03,0.05")
    p.add_argument("--min-activations", default="0.001,0.01,0.03")
    p.add_argument("--out", required=True)

    p = sub.add_parser("sweep-churn")
    p.add_argument("--events", required=True, nargs="+")
    p.add_argument("--config", default="configs/default.yaml")
    p.add_argument("--threshold", type=float, default=0.05)
    p.add_argument("--min-activation", type=float, default=0.03)
    p.add_argument("--max-active-orders", default="2,4,6")
    p.add_argument("--quote-ttls-ms", default="30000,60000")
    p.add_argument("--min-replace-intervals-ms", default="10000,30000")
    p.add_argument("--replace-threshold-bps", type=float, default=2)
    p.add_argument("--size-replace-threshold-ratio", type=float, default=0.5)
    p.add_argument("--out", required=True)

    args = parser.parse_args(argv)
    if hasattr(args, "events"):
        args.events = _expand_path_args(args.events)
    config_path = getattr(args, "config", None)
    if config_path is not None and not Path(config_path).exists():
        print(json.dumps({"ok": False, "error": "config_not_found", "path": str(config_path)}, sort_keys=True), file=sys.stderr)
        return 1

    if args.command == "generate-synthetic":
        events = generate_synthetic_events(args.scenario, args.venue, args.pair)
        write_jsonl(args.out, events)
        print(json.dumps({"events": len(events), "out": args.out}, sort_keys=True))
        return 0

    if args.command == "replay":
        config = load_config(args.config)
        engine = ReplayEngine(config)
        output = engine.run_files(args.events, args.out, replay_order=args.replay_order, strict_sequence=args.strict_sequence)
        fills = sum(1 for event in output if event.event_type == "virtual_fill")
        orders = sum(1 for event in output if event.event_type == "virtual_order_placed")
        print(
            json.dumps(
                {
                    "events": len(output),
                    "source_files": len(args.events),
                    "virtual_orders": orders,
                    "virtual_fills": fills,
                    "replay_order": engine.last_replay_order,
                    "strict_sequence": engine.last_strict_sequence,
                    "out": args.out,
                },
                sort_keys=True,
            )
        )
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
            heartbeat_interval_sec=args.heartbeat_interval_sec,
        )
        with SystemSleepPreventer(enabled=args.prevent_sleep) as sleep_prevention:
            if args.prevent_sleep and not sleep_prevention.active:
                print(json.dumps({"ok": False, "error": "prevent_sleep_unavailable", "prevent_sleep": sleep_prevention.to_dict()}, sort_keys=True), file=sys.stderr)
                return 1
            asyncio.run(recorder.run())
        print(
            json.dumps(
                {
                    "events": len(recorder.events),
                    "out": args.out,
                    "files": [str(path) for path in recorder.output_paths],
                    "prevent_sleep": sleep_prevention.to_dict(),
                },
                sort_keys=True,
            )
        )
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

    if args.command == "ccxt-fair-snapshot":
        gateway = CcxtGateway(CcxtGatewayConfig(exchange_id=args.exchange))
        try:
            event = gateway.fetch_external_btc_usd_jpy_event(
                btc_usd_symbol=args.btc_usd_symbol,
                usd_jpy_symbol=args.usd_jpy_symbol,
                symbol=args.symbol,
            )
            if args.out:
                write_jsonl(args.out, [event])
                print(json.dumps({"event_type": event.event_type, "out": args.out, "fair_jpy": event.payload["fair_jpy"]}, sort_keys=True))
            else:
                print(event.to_json())
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

    if args.command == "recording-status":
        result = recording_status(
            args.events,
            strict=args.strict,
            max_stale_sec=args.max_stale_sec,
            inspect=not args.no_inspect,
            min_duration_hours=args.min_duration_hours,
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))
        return 0 if result.ok else 1

    if args.command == "validate-public-recording":
        config = load_config(args.config)
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        inspection = inspect_recording(args.events, strict=args.strict)
        _write_json(out / "recording_inspection.json", inspection.to_dict())
        if not inspection.ok_for_replay:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "stage": "inspect_recording",
                        "reason": inspection.reason,
                        "recording_inspection": str(out / "recording_inspection.json"),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 1
        engine = ReplayEngine(config)
        try:
            output = engine.run_files(
                args.events,
                out,
                replay_order=args.replay_order,
                strict_sequence=args.strict_sequence,
            )
        except ValueError as exc:
            print(json.dumps({"ok": False, "stage": "replay", "reason": str(exc)}, ensure_ascii=False, sort_keys=True))
            return 1
        fills = sum(1 for event in output if event.event_type == "virtual_fill")
        orders = sum(1 for event in output if event.event_type == "virtual_order_placed")
        print(
            json.dumps(
                {
                    "ok": True,
                    "events": len(output),
                    "source_files": len(args.events),
                    "source_events": inspection.events,
                    "virtual_orders": orders,
                    "virtual_fills": fills,
                    "replay_order": engine.last_replay_order,
                    "strict_sequence": engine.last_strict_sequence,
                    "recording_inspection": str(out / "recording_inspection.json"),
                    "summary": str(out / "summary.json"),
                    "out": str(out),
                },
                sort_keys=True,
            )
        )
        return 0

    if args.command == "evaluate-quality-gate":
        result = evaluate_quality_gate(
            summary_paths=args.summary,
            recording_inspection_path=args.recording_inspection,
            thresholds=_quality_gate_thresholds(args),
        )
        if args.out:
            write_quality_gate_result(args.out, result)
        print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))
        return 0 if result.ok else 1

    if args.command == "run-public-data-gate":
        with SystemSleepPreventer(enabled=args.prevent_sleep) as sleep_prevention:
            sleep_status = sleep_prevention.to_dict()
            if args.prevent_sleep and not sleep_prevention.active:
                out = Path(args.out)
                out.mkdir(parents=True, exist_ok=True)
                payload = {"ok": False, "stage": "prevent_sleep", "reason": "prevent_sleep_unavailable", "prevent_sleep": sleep_status}
                _write_json(out / "public_data_gate.json", payload)
                print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
                return 1
            code, payload = _run_public_data_gate(args, prevent_sleep=sleep_status)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return code

    if args.command == "analyze-risk-blocks":
        events = []
        for path in args.events:
            events.extend(read_jsonl(path))
        result = analyze_risk_blocks(events)
        json_path, md_path = write_risk_diagnostics(args.out, result)
        print(json.dumps({"json": str(json_path), "markdown": str(md_path), "blocked_events": result.blocked_events}, sort_keys=True))
        return 0

    if args.command == "sweep-activation":
        events = []
        for path in args.events:
            events.extend(read_jsonl(path))
        rows = run_activation_sweep(
            base_config=load_config(args.config),
            events=events,
            thresholds=_parse_float_list(args.thresholds),
            min_activations=_parse_float_list(args.min_activations),
            out_dir=args.out,
        )
        print(json.dumps({"rows": len(rows), "out": args.out, "best": rows[0] if rows else None}, sort_keys=True))
        return 0

    if args.command == "sweep-churn":
        events = []
        for path in args.events:
            events.extend(read_jsonl(path))
        rows = run_churn_sweep(
            base_config=load_config(args.config),
            events=events,
            shock_threshold=args.threshold,
            min_activation=args.min_activation,
            max_active_orders=[int(value) for value in _parse_float_list(args.max_active_orders)],
            quote_ttls_ms=_parse_float_list(args.quote_ttls_ms),
            min_replace_intervals_ms=_parse_float_list(args.min_replace_intervals_ms),
            replace_threshold_bps=args.replace_threshold_bps,
            size_replace_threshold_ratio=args.size_replace_threshold_ratio,
            out_dir=args.out,
        )
        print(json.dumps({"rows": len(rows), "out": args.out, "best": rows[0] if rows else None}, sort_keys=True))
        return 0

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


def _parse_float_list(value: str) -> list[float]:
    return [float(item.strip()) for item in value.split(",") if item.strip()]


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)


def _run_public_data_gate(args: argparse.Namespace, *, prevent_sleep: dict) -> tuple[int, dict]:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    inspection = inspect_recording(args.events, strict=args.strict)
    inspection_path = out / "recording_inspection.json"
    _write_json(inspection_path, inspection.to_dict())
    if not inspection.ok_for_replay:
        payload = {
            "ok": False,
            "stage": "inspect_recording",
            "reason": inspection.reason,
            "recording_inspection": str(inspection_path),
            "prevent_sleep": prevent_sleep,
        }
        _write_json(out / "public_data_gate.json", payload)
        return 1, payload
    summary_paths = []
    replay_results = []
    for index, config_path in enumerate(args.configs, start=1):
        cfg_path = Path(config_path)
        if not cfg_path.exists():
            payload = {
                "ok": False,
                "stage": "config",
                "reason": "config_not_found",
                "path": str(cfg_path),
                "prevent_sleep": prevent_sleep,
            }
            _write_json(out / "public_data_gate.json", payload)
            return 1, payload
        run_out = out / f"{index:02d}_{cfg_path.stem}"
        engine = ReplayEngine(load_config(cfg_path))
        try:
            output = engine.run_files(
                args.events,
                run_out,
                replay_order=args.replay_order,
                strict_sequence=args.strict_sequence,
            )
        except ValueError as exc:
            payload = {
                "ok": False,
                "stage": "replay",
                "reason": str(exc),
                "config": str(cfg_path),
                "out": str(run_out),
                "prevent_sleep": prevent_sleep,
            }
            _write_json(out / "public_data_gate.json", payload)
            return 1, payload
        summary_path = run_out / "summary.json"
        summary_paths.append(summary_path)
        replay_results.append(
            {
                "config": str(cfg_path),
                "out": str(run_out),
                "summary": str(summary_path),
                "events": len(output),
                "virtual_orders": sum(1 for event in output if event.event_type == "virtual_order_placed"),
                "virtual_fills": sum(1 for event in output if event.event_type == "virtual_fill"),
                "replay_order": engine.last_replay_order,
                "strict_sequence": engine.last_strict_sequence,
            }
        )
    quality = evaluate_quality_gate(
        summary_paths=summary_paths,
        recording_inspection_path=inspection_path,
        thresholds=_quality_gate_thresholds(args),
    )
    quality_path = out / "quality_gate.json"
    write_quality_gate_result(quality_path, quality)
    payload = {
        "ok": quality.ok,
        "recording_inspection": str(inspection_path),
        "quality_gate": str(quality_path),
        "replays": replay_results,
        "quality_failures": quality.failures,
        "prevent_sleep": prevent_sleep,
        "out": str(out),
    }
    _write_json(out / "public_data_gate.json", payload)
    return (0 if quality.ok else 1), payload


def _expand_path_args(paths: list[str]) -> list[str]:
    expanded: list[str] = []
    for path in paths:
        if glob.has_magic(path):
            matches = sorted(glob.glob(path))
            if matches:
                expanded.extend(matches)
                continue
        expanded.append(path)
    return expanded


def _quality_gate_thresholds(args: argparse.Namespace) -> QualityGateThresholds:
    return QualityGateThresholds(
        min_report_count=args.min_report_count,
        min_recording_hours=args.min_recording_hours,
        min_fills=args.min_fills,
        min_fill_rate=args.min_fill_rate,
        min_strategy_alpha_pnl=args.min_strategy_alpha_pnl,
        max_orders_per_minute=args.max_orders_per_minute,
        max_cancels_per_minute=args.max_cancels_per_minute,
    )


def _last_fair(events: list) -> float | None:
    for event in reversed(events):
        if event.event_type == "mark_price" and event.payload.get("fair") is not None:
            return float(event.payload["fair"])
    return None


if __name__ == "__main__":
    raise SystemExit(main())
