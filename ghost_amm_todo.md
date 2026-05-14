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
- Quality gate: `evaluate-quality-gate` fails closed unless inspection duration, fills, alpha, and churn thresholds pass across multiple reports.
- Long recording support: `record-bitbank-public --prevent-sleep` keeps Windows awake during the recording process when the OS allows it.
- Long recording observability: `record-bitbank-public --heartbeat-interval-sec` emits periodic heartbeat events for stall diagnostics.
- Long recording idle watchdog: `record-bitbank-public --max-idle-sec` reconnects when market messages stop arriving while the process is still alive.
- Recording monitor: `recording-status` reports file freshness, strict inspection status, and stale recording failures.
- Public data gate runner: `run-public-data-gate` inspects a recording once, replays multiple configs, writes per-config reports, and evaluates `quality_gate.json`.
- CLI event inputs expand wildcards internally, so rotated JSONL sets like `data/raw/bitbank_btc_jpy_24h_*.jsonl` work in PowerShell.
- Recording monitor supports `--min-duration-hours`, so 24h gate checks fail explicitly on partial recordings.
- Public data gate runner supports `--prevent-sleep`, so Windows can stay awake during long post-recording replay and quality checks.
- Public data gate runner supports `--require-min-duration-before-replay`, so early recorder exits stop before expensive multi-config replay.
- Quality gate writes `quality_gate.md` alongside JSON so pass/fail, alpha, fills, and churn are reviewable without parsing JSON.
- Public data gate runner supports `--diagnostic-configs`, so high-churn diagnostic replays are generated without counting against the quality gate.

## In Progress

- Active 25h buffered public recording is running locally for `btc_jpy`.
- Recording output: `data/raw/bitbank_btc_jpy_25h_retry_20260514_204916*.jsonl`.
- Started: 2026-05-14 20:49:16 JST. Expected completion: around 2026-05-15 21:49 JST.
- This retry uses `--max-idle-sec 300`, `--max-reconnects 500`, `--heartbeat-interval-sec 60`, and `--prevent-sleep`.
- Last checked: 2026-05-14 20:55 JST, duration 0.11h, strict recording status `ok_for_replay=true`, stale `false`, sequence violations 0, duration gate `0.11<24h`.
- `powercfg /requests` shows a `SYSTEM` request from the uv-managed Python recorder process, so `--prevent-sleep` is active while the process is alive.
- At 2026-05-14 21:07 JST, the active Windows power plan was also changed locally for the recording: AC auto sleep disabled and AC hybrid sleep disabled. Before/after snapshots are under `data/logs/powercfg_*_25h_retry_20260514_204916.json`.
- After the gate finishes, restore normal AC sleep policy if desired with `powercfg /change standby-timeout-ac 120`, `powercfg /setacvalueindex SCHEME_CURRENT SUB_SLEEP HYBRIDSLEEP 1`, and `powercfg /setactive SCHEME_CURRENT`.
- Completion watcher is running locally and should run `run-public-data-gate --require-min-duration-before-replay --prevent-sleep` after the 25h recorder exits.
- Expected gate output: `data/reports/bitbank_btc_jpy_25h_retry_20260514_204916_gate`.
- Previous 24h attempt `data/raw/bitbank_btc_jpy_24h_20260512_234537*.jsonl` failed the duration gate at 18.43h. Root cause candidate: the recorder process lived until the 24h timeout, but market events stopped around 18.43h; idle watchdog was added before this retry.
- No remaining code-only TODO is currently in progress; the active gate is real public data collection and validation.

## Pending Real-Data Gates

- Record a 24h bitbank public JSONL dataset.
- Run strict inspection on the 24h recording.
- Replay the 24h recording and review generated reports.
- Record and inspect a longer 1-week public dataset.
- Use the real-data reports to decide whether the strategy has positive enough quality to justify any future live-order work.

## Latest Real-Data Check

Checked on 2026-05-12 with the existing 12h-named recording:

```powershell
uv run ghost-amm validate-public-recording `
  --events data/raw/bitbank_btc_jpy_12h_20260511_233819.jsonl data/raw/bitbank_btc_jpy_12h_20260511_233819_0001.jsonl `
  --config configs/default.yaml `
  --out data/reports/bitbank_btc_jpy_12h_validation
```

Result:

- strict inspection passed: 163,422 source events, no sequence violations, metadata present, ticker/trade/depth coverage present.
- actual inspected duration was 5.92h, so this does not satisfy the 24h recording gate.
- default config produced 0 virtual orders and 0 fills because `activation_too_low` dominated all risk blocks.
- `configs/diagnostic_relaxed_activation.yaml` produced 22,157 virtual orders but 0 fills, with very high quote churn.
- `configs/diagnostic_controlled_churn.yaml` produced 888 virtual orders and 1 fill.
- controlled churn summary: `strategy_alpha_pnl=-4.82625`, `fill_rate=0.001126`, `orders_per_minute=2.499`, `cancels_per_minute=2.496`.
- `evaluate-quality-gate` failed as expected: only 1 report, 5.92h duration, 1 fill, and negative strategy alpha.

Interpretation:

- The 12h data proves the recorder and replay path work on real public data.
- It does not prove profitability.
- Pre-live quality gate remains failed until a 24h recording passes strict validation and multiple replay configs show stable positive alpha with enough fills.

Additional smoke check on 2026-05-13 with the active 24h recording at 0.78h:

```powershell
uv run ghost-amm run-public-data-gate `
  --events data/raw/bitbank_btc_jpy_24h_20260512_234537*.jsonl `
  --configs configs/default.yaml configs/diagnostic_relaxed_activation.yaml configs/diagnostic_controlled_churn.yaml `
  --out data/reports/bitbank_btc_jpy_24h_gate_smoke_20260513_0030
```

Result:

- strict inspection passed on the partial recording: 21,566 source events, 0 sequence violations, duration 0.78h.
- `configs/default.yaml`: 0 virtual orders, 0 fills, `strategy_alpha_pnl=0.0`.
- `configs/diagnostic_relaxed_activation.yaml`: 6,137 virtual orders, 0 fills, very high churn at 130.8 orders/min and 130.8 cancels/min.
- `configs/diagnostic_controlled_churn.yaml`: 158 virtual orders, 2 fills, `strategy_alpha_pnl=+5.051`, `fill_rate=0.01266`, `orders_per_minute=3.36`, `cancels_per_minute=3.34`.
- `quality_gate.json` failed as expected: duration below 24h, too few fills, default/relaxed alpha not positive, relaxed churn too high.

Interpretation:

- The new one-shot gate command works on real public JSONL and PowerShell wildcard input.
- The partial positive alpha on 2 fills is not evidence of profitability.
- The 24h gate remains open until the full recording completes and enough fills are observed across multiple configs.

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
  --max-reconnects 100 `
  --heartbeat-interval-sec 60 `
  --max-idle-sec 300 `
  --prevent-sleep
```

Strict inspection:

```powershell
uv run ghost-amm recording-status data/raw/bitbank_btc_jpy_10m.jsonl --strict --max-stale-sec 300

uv run ghost-amm inspect-recording data/raw/bitbank_btc_jpy_10m.jsonl --strict
```

Replay:

```powershell
uv run ghost-amm validate-public-recording `
  --events data/raw/bitbank_btc_jpy_10m.jsonl `
  --config configs/default.yaml `
  --out data/reports/bitbank_btc_jpy_10m
```

25h buffered recording for the 24h gate:

```powershell
uv run --with "python-socketio[client]>=5" --with aiohttp ghost-amm record-bitbank-public `
  --pair btc_jpy `
  --config configs/default.yaml `
  --out data/raw/bitbank_btc_jpy_25h.jsonl `
  --timeout-sec 90000 `
  --rotate-every-bytes 104857600 `
  --flush-every-events 1 `
  --max-reconnects 500 `
  --reconnect-delay-sec 3 `
  --heartbeat-interval-sec 60 `
  --max-idle-sec 300 `
  --prevent-sleep

uv run ghost-amm validate-public-recording `
  --events data/raw/bitbank_btc_jpy_25h*.jsonl `
  --config configs/default.yaml `
  --out data/reports/bitbank_btc_jpy_24h

uv run ghost-amm recording-status data/raw/bitbank_btc_jpy_25h*.jsonl --strict --max-stale-sec 300 --min-duration-hours 24

uv run ghost-amm evaluate-quality-gate `
  --summary data/reports/bitbank_btc_jpy_24h_config_a/summary.json data/reports/bitbank_btc_jpy_24h_config_b/summary.json `
  --recording-inspection data/reports/bitbank_btc_jpy_24h_config_a/recording_inspection.json `
  --out data/reports/bitbank_btc_jpy_24h_quality_gate.json
```

One-shot 24h public data gate:

```powershell
uv run ghost-amm run-public-data-gate `
  --events data/raw/bitbank_btc_jpy_25h*.jsonl `
  --configs configs/default.yaml configs/diagnostic_controlled_churn.yaml `
  --diagnostic-configs configs/diagnostic_relaxed_activation.yaml `
  --out data/reports/bitbank_btc_jpy_25h_gate `
  --require-min-duration-before-replay `
  --prevent-sleep
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
