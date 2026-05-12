# Ghost AMM TODO

Target repo: `tanakashunta0801/ghost_amm`
Target market: bitbank spot `BTC/JPY` / `btc_jpy`

Policy: do not submit live orders yet. First make replay, public recording, risk checks, and analytics trustworthy.

## Current Status

As of 2026-05-12, the repository is public and CI is green. The MVP is a research and replay system for a virtual Ghost AMM, not a live trading bot.

Latest verified local test run:

```powershell
uv run --extra test pytest -q
```

## Done

- TODO-001: fill model now shares aggressive trade flow across active orders, respects queue ahead, price priority, partial fills, and min resting time.
- TODO-002: replay defaults to arrival order, with opt-in exchange-time sorting and strict sequence checks.
- TODO-003: explicit missing config paths fail closed.
- TODO-004: robust fair supports bitbank orderbook mid, bitbank ticker mid/last, external BTC/USD x USD/JPY fair events, freshness checks, deviation filtering, source count, and median fair.
- TODO-005: shock activation is side-specific with bid/ask activation and shock direction.
- TODO-006: quote surface skips raw sizes below min order size instead of rounding tiny activation up to min size.
- TODO-007: bitbank pair spec maker fee is reflected in fill simulation.
- TODO-008: fill burst cooldown risk stop exists.
- TODO-009: inventory and notional limits exist.
- TODO-010: fair drift stop exists.
- TODO-011: last trade versus fair deviation stop exists.
- TODO-012: recording inspection reports channel coverage, metadata state, reconnect/gap diagnostics, and strict failures.
- TODO-013: public dry-run writes replay-shaped reports and source events.
- TODO-014: generated data/report directories are ignored; deterministic examples live under `examples/`.
- TODO-015: adverse selection metrics are split by side.
- TODO-016: quote churn metrics are available and included in churn sweep output.
- TODO-017: shock event attribution is carried into fills and summary metrics.
- TODO-018: GitHub Actions runs pytest on push/PR.
- TODO-019: bitbank normalizer fixture tests exist.
- TODO-020: orderbook stale/recovery tests exist.
- TODO-021: live order intent and live order blocked events are separated.
- TODO-022: future live gate conditions are explicit, and MVP still blocks real submission.
- Recording gate: `validate-public-recording` fails closed on strict inspection errors before writing replay reports.

## In Progress

- No remaining code-only TODO is currently in progress.
- The next gate is real public data collection and validation.

## Pending Real-Data Gates

- Record a 24h bitbank public JSONL dataset.
- Run strict inspection on the 24h recording.
- Replay the 24h recording and review generated reports.
- Record and inspect a longer 1-week public dataset.
- Use the real-data reports to decide whether the strategy has positive enough quality to justify any future live-order work.

## Latest Real-Data Check

Checked on 2026-05-12 with the existing 12h recording:

```powershell
uv run ghost-amm validate-public-recording `
  --events data/raw/bitbank_btc_jpy_12h_20260511_233819.jsonl data/raw/bitbank_btc_jpy_12h_20260511_233819_0001.jsonl `
  --config configs/default.yaml `
  --out data/reports/bitbank_btc_jpy_12h_validation
```

Result:

- strict inspection passed: 163,422 source events, no sequence violations, metadata present, ticker/trade/depth coverage present.
- default config produced 0 virtual orders and 0 fills because `activation_too_low` dominated all risk blocks.
- `configs/diagnostic_relaxed_activation.yaml` produced 22,157 virtual orders but 0 fills, with very high quote churn.
- `configs/diagnostic_controlled_churn.yaml` produced 888 virtual orders and 1 fill.
- controlled churn summary: `strategy_alpha_pnl=-4.82625`, `fill_rate=0.001126`, `orders_per_minute=2.499`, `cancels_per_minute=2.496`.

Interpretation:

- The 12h data proves the recorder and replay path work on real public data.
- It does not prove profitability.
- Pre-live quality gate remains failed until a 24h recording passes strict validation and multiple replay configs show stable positive alpha with enough fills.

## Do Not Do Yet

- Do not create a real live order submission path in this MVP.
- Do not use private bitbank API keys for replay or public dry-run.
- Do not treat synthetic or short public recordings as proof of profitability.

## Useful Commands

Short public recording:

```powershell
uv run --with "python-socketio[client]>=5" --with aiohttp ghost-amm record-bitbank-public `
  --pair btc_jpy `
  --config configs/default.yaml `
  --out data/raw/bitbank_btc_jpy_10m.jsonl `
  --timeout-sec 600 `
  --rotate-every-bytes 104857600 `
  --flush-every-events 1 `
  --max-reconnects 100
```

Strict inspection:

```powershell
uv run ghost-amm inspect-recording data/raw/bitbank_btc_jpy_10m.jsonl --strict
```

Replay:

```powershell
uv run ghost-amm validate-public-recording `
  --events data/raw/bitbank_btc_jpy_10m.jsonl `
  --config configs/default.yaml `
  --out data/reports/bitbank_btc_jpy_10m
```

24h recording gate:

```powershell
uv run --with "python-socketio[client]>=5" --with aiohttp ghost-amm record-bitbank-public `
  --pair btc_jpy `
  --config configs/default.yaml `
  --out data/raw/bitbank_btc_jpy_24h.jsonl `
  --timeout-sec 86400 `
  --rotate-every-bytes 104857600 `
  --flush-every-events 1 `
  --max-reconnects 100

uv run ghost-amm validate-public-recording `
  --events data/raw/bitbank_btc_jpy_24h.jsonl `
  --config configs/default.yaml `
  --out data/reports/bitbank_btc_jpy_24h
```

## Pre-Live Completion Gates

- `pytest` passes.
- Fill model has no aggressive trade over-consumption.
- Arrival-order replay is the default.
- Explicit missing config fails closed.
- Robust fair can require at least two fresh sources.
- bitbank book-only fair can be blocked by config.
- bid/ask activation is side-specific.
- Risk kernel includes fill burst, inventory/notional, fair drift, and last-trade deviation stops.
- Fee is reflected in reports.
- 24h public recording passes strict inspection.
- 24h replay generates reports.
- Adverse selection and quote churn are visible in summary/sweep outputs.
- `data/reports`, `data/raw`, and replay artifacts are not tracked by git.
- Live order path is absent or fully blocked.
