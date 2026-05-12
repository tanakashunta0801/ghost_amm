# Ghost AMM / Forced-Flow Sponge MVP

Research-first prototype for a bitbank spot BTC/JPY virtual AMM. The MVP records or generates events, replays them deterministically, projects virtual post-only quotes, simulates conservative fills, and writes analytics. It does not submit live orders.

Current implementation status and remaining gates are tracked in [ghost_amm_todo.md](ghost_amm_todo.md).

## Quick Start

```powershell
uv run --extra test pytest

uv run ghost-amm replay `
  --events examples/sell_shock/input.jsonl `
  --config configs/default.yaml `
  --out data/reports/sell_shock
```

The replay command writes generated artifacts under `data/reports/`, which is intentionally ignored by git. Deterministic example input and expected summary files live under `examples/`.

## Public Dry Run

Public stream dry-run uses bitbank socket.io public channels only. It does not require API keys and writes raw/normalized/virtual events so the run can be replayed later.

```powershell
uv run --extra full ghost-amm dry-run-bitbank-public `
  --pair btc_jpy `
  --config configs/default.yaml `
  --out data/reports/dryrun_btc_jpy `
  --max-events 500
```

The dry-run output directory includes replay-shaped `summary.json`, `report.md`, `fills.csv`, `risk_diagnostics.md`, and `recording_inspection.json`. Use `source_events.jsonl` as the input when replaying the observed public stream.

## Recording Real Public Data

Use `record-bitbank-public` before real-data replay. It writes metadata first, flushes each JSONL event, reconnects on stream failures, and can rotate files for long runs.

```powershell
uv run --with "python-socketio[client]>=5" --with aiohttp ghost-amm record-bitbank-public `
  --pair btc_jpy `
  --config configs/default.yaml `
  --out data/raw/bitbank_btc_jpy_1h.jsonl `
  --timeout-sec 3600 `
  --rotate-every-bytes 104857600 `
  --flush-every-events 1 `
  --max-reconnects 100 `
  --heartbeat-interval-sec 60 `
  --prevent-sleep
```

On Windows, `--prevent-sleep` requests the OS to keep the system awake for the recording process. It cannot protect against lid-close sleep policy, power loss, shutdown, or network loss. Periodic `dry_run_heartbeat` events make long recordings easier to inspect for stalls.

Inspect the recording before replay:

```powershell
uv run ghost-amm inspect-recording data/raw/bitbank_btc_jpy_1h.jsonl
```

Check whether an in-progress recording is still updating and currently replayable:

```powershell
uv run ghost-amm recording-status data/raw/bitbank_btc_jpy_1h.jsonl --strict --max-stale-sec 300
```

For strict channel coverage, including observed ticker and trade events:

```powershell
uv run ghost-amm inspect-recording data/raw/bitbank_btc_jpy_1h.jsonl --strict
```

To fail closed on inspection problems and write replay reports in one step:

```powershell
uv run ghost-amm validate-public-recording `
  --events data/raw/bitbank_btc_jpy_1h.jsonl `
  --config configs/default.yaml `
  --out data/reports/bitbank_btc_jpy_1h
```

Evaluate whether generated reports satisfy the pre-live quality gate:

```powershell
uv run ghost-amm evaluate-quality-gate `
  --summary data/reports/bitbank_btc_jpy_24h_config_a/summary.json data/reports/bitbank_btc_jpy_24h_config_b/summary.json `
  --recording-inspection data/reports/bitbank_btc_jpy_24h_config_a/recording_inspection.json `
  --out data/reports/bitbank_btc_jpy_24h_quality_gate.json
```

After a long public recording finishes, run the public-data gate to inspect once, replay multiple configs, and evaluate the quality gate in one command:

```powershell
uv run ghost-amm run-public-data-gate `
  --events data/raw/bitbank_btc_jpy_24h_20260512_234537*.jsonl `
  --configs configs/default.yaml configs/diagnostic_controlled_churn.yaml `
  --out data/reports/bitbank_btc_jpy_24h_gate
```

The command writes `recording_inspection.json`, one replay report directory per config, `quality_gate.json`, and `public_data_gate.json`. It exits non-zero unless strict recording inspection and the configured quality thresholds pass.
The CLI expands `--events` wildcards itself, so the `*.jsonl` form works in PowerShell.

## External Fair Price Events

Replay can consume `external_fair_price` events as an additional robust-fair source. A CCXT public ticker snapshot can be converted to one JSONL event by combining BTC/USD and USD/JPY:

```powershell
uv run --extra full ghost-amm ccxt-fair-snapshot `
  --exchange <public-exchange-id> `
  --btc-usd-symbol BTC/USD `
  --usd-jpy-symbol USD/JPY `
  --out data/raw/external_fair_snapshot.jsonl
```

These events are filtered by the same freshness, source-count, and deviation rules as bitbank book/ticker fair sources.

## Safety Boundary

- Default pair is `btc_jpy` / `BTC/JPY`.
- All MVP orders are virtual and `post_only=true`.
- CCXT is wrapped by `ghost_amm.exchange.ccxt_gateway.CcxtGateway`; order submission and private calls are blocked in MVP mode.
- No withdrawal execution path exists in the package.
- Future live/private execution is represented by interfaces and live gates only. If any gate fails, a `LiveOrderBlocked` event is produced instead of a real order.
