# Ghost AMM / Forced-Flow Sponge MVP

Research-first prototype for a bitbank spot BTC/JPY virtual AMM. The MVP records or generates events, replays them deterministically, projects virtual post-only quotes, simulates conservative fills, and writes analytics. It does not submit live orders.

## Quick Start

```powershell
uv run --extra test pytest

uv run ghost-amm generate-synthetic `
  --scenario sell_shock `
  --venue synthetic_bitbank `
  --pair btc_jpy `
  --out data/raw/sell_shock.jsonl

uv run ghost-amm replay `
  --events data/raw/sell_shock.jsonl `
  --config configs/default.yaml `
  --out data/reports/sell_shock
```

The replay command writes `events.jsonl`, `fills.csv`, `summary.json`, and `report.md` under the output directory.

## Public Dry Run

Public stream dry-run uses bitbank socket.io public channels only. It does not require API keys and writes raw/normalized/virtual events so the run can be replayed later.

```powershell
uv run --extra full ghost-amm dry-run-bitbank-public `
  --pair btc_jpy `
  --config configs/default.yaml `
  --out data/reports/dryrun_btc_jpy `
  --max-events 500
```

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
  --max-reconnects 100
```

Inspect the recording before replay:

```powershell
uv run ghost-amm inspect-recording data/raw/bitbank_btc_jpy_1h.jsonl
```

For strict channel coverage, including observed ticker and trade events:

```powershell
uv run ghost-amm inspect-recording data/raw/bitbank_btc_jpy_1h.jsonl --strict
```

## Safety Boundary

- Default pair is `btc_jpy` / `BTC/JPY`.
- All MVP orders are virtual and `post_only=true`.
- CCXT is wrapped by `ghost_amm.exchange.ccxt_gateway.CcxtGateway`; order submission and private calls are blocked in MVP mode.
- No withdrawal execution path exists in the package.
- Future live/private execution is represented by interfaces and live gates only. If any gate fails, a `LiveOrderBlocked` event is produced instead of a real order.
