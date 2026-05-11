# /goal Ghost AMM — bitbank Forced-Flow Sponge Bot MVP

## Goal

Build a reproducible prototype of a crypto trading research bot called **Ghost AMM / Forced-Flow Sponge**.

The eventual real trading venue is **bitbank spot exchange**, and the primary production pair is **BTC/JPY**. The MVP must still be research-first: record data, replay it deterministically, generate virtual orders, simulate fills, and only later allow a tightly gated bitbank paper/live execution adapter.

This is **not** a price-prediction bot, **not** an indicator strategy, and **not** an ML model.

The bot should behave like a small virtual AMM projected onto centralized exchange order books:

- It continuously computes a fair price from bitbank market data, with optional JPY-converted external references later.
- It maintains an inventory-aware quote surface.
- It projects that quote surface into hypothetical post-only limit orders.
- It activates more aggressively only around forced-flow-like events such as abnormal taker flow, sudden order-book thinning, or book rebuilds after shocks.
- It must be testable by deterministic event replay, not candle backtesting.

The MVP must **not place real orders**. It should only record events, replay events, generate virtual orders, simulate fills, and produce analytics.

The MVP must support two research execution modes:

```text
1. event-replay backtest
   - read recorded/synthetic events
   - rebuild the book deterministically
   - generate virtual post-only quotes
   - simulate fills conservatively
   - produce analytics

2. public-stream dry-run
   - connect to bitbank public streams
   - run the same fair-price, shock, AMM, risk, and virtual-fill pipeline in real time
   - emit virtual orders and virtual fills only
   - never call private order endpoints
```

In this project, "backtest" means **event-replay backtest**, not candle/OHLCV backtesting.
In this project, "dry-run" means **live public-market-data simulation with virtual orders**, not real order submission.

Any later real order submission must be **bitbank-only**, **spot-only**, **post-only limit orders only**, and must require multiple explicit live-trading gates.

---

## Core Hypothesis

Large forced-flow events temporarily distort liquidity. After the first shock has passed, if price is dislocated from an external fair price and the order book starts rebuilding, a small inventory-controlled virtual AMM may obtain favorable fills by supplying liquidity with post-only quotes.

We are testing this question:

> After forced-flow shocks, does projecting an inventory-aware AMM quote surface produce fills that are favorable relative to later fair price movement, after fees and conservative fill assumptions?

We are **not** testing:

- Whether BTC will go up or down.
- Whether EMA/RSI/MACD signals work.
- Whether an ML classifier can predict returns.
- Whether a strategy works on OHLCV candles.

---

## Non-Goals

Do **not** implement these in the MVP:

- Real order submission in the MVP.
- Leverage trading.
- Perpetual futures, funding-rate trading, or hedge execution in the MVP.
- Automatic live execution without explicit live gates.
- Withdrawal-related functionality or withdrawal API calls.
- A dashboard-heavy frontend.
- ML model training.
- Indicator-based entry/exit signals.
- Candle-only backtesting.
- Optimization that overfits parameters.

All execution must be virtual/paper-only until the replay engine and analytics are reliable.

---

## Target Market for MVP

Use bitbank spot BTC/JPY first:

```text
venue: bitbank
bitbank_pair: btc_jpy
symbol: BTC/JPY
base: BTC
quote: JPY
market_type: spot
```

The system should be designed so other JPY pairs can be added later, but the MVP only needs `btc_jpy`.

Do not use BTC/USDT as the default production pair. If external USD or USDT venues are used later for fair-price references, they must be converted into JPY using an explicit FX source and must never be mixed with BTC/JPY without conversion.

---

## bitbank Exchange Requirements

bitbank must be treated as the execution venue, not just as a generic CCXT-style exchange.

### Scope

MVP scope:

```text
bitbank public market-data recording
bitbank public-stream dry-run
bitbank-shaped synthetic events
bitbank order-book replay / event-replay backtest
bitbank pair-rule validation
CCXT REST gateway for convenience where safe
native bitbank public stream adapter for socket.io market data
virtual post-only orders only
no private API keys required for MVP
no live orders
```

Post-MVP scope:

```text
bitbank private REST adapter
bitbank paper execution adapter
bitbank live execution adapter with hard gates
post-only limit orders only
order/fill reconciliation
cancel-all safety flow
```

### Pair and Market Rules

On startup, the system must fetch and cache bitbank pair metadata and status:

```text
GET /spot/pairs
GET /spot/status
```

The bot must not hardcode minimum order sizes, price precision, amount precision, fee rates, or trading status. It must derive these from bitbank pair metadata whenever possible:

```text
unit_amount
limit_max_amount
price_digits
amount_digits
maker_fee_rate_base
maker_fee_rate_quote
taker_fee_rate_base
taker_fee_rate_quote
is_enabled
stop_order
stop_order_and_cancel
stop_buy_order
stop_sell_order
```

If metadata cannot be fetched, the bot must refuse live/paper-private execution and may only run synthetic replay.

### Public Market Data

Implement a `BitbankPublicRecorder` that connects to bitbank public streams and records raw payloads plus normalized events.

Required channels for `btc_jpy`:

```text
ticker_btc_jpy
transactions_btc_jpy
depth_whole_btc_jpy
depth_diff_btc_jpy
```

The recorder must preserve:

```text
raw room_name
raw payload
local receive timestamp
exchange timestamp when available
sequenceId / s when available
normalized event
```

Order-book reconstruction rules:

```text
1. Start from depth_whole_btc_jpy.
2. Apply depth_diff_btc_jpy updates.
3. Treat diff amounts as absolute quantities.
4. Remove a price level when amount == 0.
5. Do not require sequence IDs to be consecutive.
6. Require sequence IDs to be monotonic for a given book stream.
7. If sequence ordering is invalid, mark the book stale and request/resubscribe a fresh whole-book snapshot.
```

### bitbank-Specific Forced-Flow Proxy

bitbank public data does not need a liquidation stream for the MVP. The `ForcedFlowEvent` must be inferred from bitbank-visible microstructure only:

```text
large taker sell/buy bursts from transactions_btc_jpy
sudden spread widening
20bps depth collapse
best bid/ask level removal bursts
book rebuild after thinning
price dislocation from recent fair/mid
```

This means `ForcedFlowEvent` in the bitbank MVP is an **inferred forced-flow proxy**, not an exchange-provided liquidation event.

### Backtest and Dry-Run Requirements

The project must support both backtesting and dry-run, but they mean specific things:

```text
event-replay backtest:
  source = recorded JSONL/Parquet or synthetic events
  clock = replay event timestamps
  orders = virtual only
  fills = conservative simulated fills
  API keys = not required

public-stream dry-run:
  source = live bitbank public streams
  clock = wall clock + exchange timestamps
  orders = virtual only
  fills = conservative simulated fills from live trades/book movement
  API keys = not required

private-paper mode, post-MVP:
  source = live bitbank public streams + optional private balance/order reads
  orders = virtual only unless all live gates are explicitly enabled
  purpose = reconcile inventory assumptions with real account state without submitting orders

live mode, post-MVP:
  source = live bitbank public/private APIs
  orders = real bitbank post-only limit orders only
  requires all live gates
```

The backtest and dry-run engines must share the same core pipeline:

```text
normalized events
  -> order book state
  -> fair price state
  -> shock activation
  -> inventory state
  -> AMM quote surface
  -> risk kernel
  -> virtual order projector
  -> conservative fill model
  -> analytics
```

Do not implement separate strategy logic for backtest and dry-run. The same deterministic quote-generation code must be used in both modes.

### Private REST Execution Adapter: Post-MVP Only

Create interfaces now, but do not enable real order submission in the MVP.

The future `BitbankPrivateClient` should support only these trading operations:

```text
fetch assets
fetch active orders
fetch order info
create spot limit order with post_only=true
cancel one order
cancel multiple orders
fetch trade history
fetch pair status
fetch pair metadata
```

The live adapter must never implement withdrawal requests. Do not add withdrawal endpoints to the execution path.

Allowed order type for live trading:

```text
type = limit
post_only = true
pair = btc_jpy
side = buy | sell
```

Forbidden order types for the live bot:

```text
market
stop
stop_limit
take_profit
stop_loss
losscut
margin orders
```

### Live Trading Gates

A live order must be impossible unless all gates pass:

```text
config.execution.mode == "live"
config.execution.venue == "bitbank"
config.execution.enable_live_orders == true
environment variable GHOST_AMM_ENABLE_LIVE == "I_ACCEPT_RISK"
API key is present
API secret is present
pair metadata was fetched successfully
spot status for btc_jpy is NORMAL
pair is_enabled == true
stop_order == false
stop_order_and_cancel == false
side-specific stop flag is false
clock drift is within limit
risk kernel allows quote
order is post_only limit
order does not cross the current book
order size and price pass bitbank precision/min/max checks
```

If any gate fails, the adapter must create a `LiveOrderBlocked` event instead of submitting an order.

### API Key Safety

Use environment variables or a secret manager:

```text
BITBANK_API_KEY
BITBANK_API_SECRET
```

Do not store secrets in config files, git, logs, reports, or exceptions. Logs must redact authorization headers and signatures.

Use the shortest practical request validity window for authenticated requests. If local clock drift is too high, block private requests.

### Order Reconciliation

Before any future live trading session:

```text
1. Fetch active bitbank orders for btc_jpy.
2. If unmanaged active orders exist, refuse to start or require explicit cancel-on-start mode.
3. Fetch asset balances.
4. Rebuild local inventory from exchange balances.
5. Cancel stale bot-owned orders if configured.
6. Start quoting only after reconciliation is complete.
```

During live/paper-private trading:

```text
track local_order_id -> bitbank order_id
poll or stream order state
handle partial fills
handle cancel acknowledgment
handle cancel failure
handle rejected post-only orders
handle API errors as first-class events
```

### bitbank Circuit/Status Handling

If bitbank status is not `NORMAL`, or pair/order flags indicate restrictions, the risk kernel must block new quotes.

If circuit-break-like order-book states produce crossed or abnormal BBO, the fair price engine must mark fair price invalid unless a dedicated circuit-break mode is implemented.

---

## CCXT Integration Plan

Use the free/open-source `ccxt` package where it reduces boilerplate, but do not let CCXT erase bitbank-specific behavior.

### Intended CCXT Uses

Use CCXT as a convenience REST gateway for:

```text
load_markets / market metadata cross-checks
fetch_ticker smoke tests
fetch_order_book snapshots when useful
fetch_trades / OHLCV historical convenience where useful
fetch_balance in post-MVP private-paper/live mode
create_order in post-MVP live mode only if post_only=true can be passed and verified
cancel_order / cancel_orders in post-MVP live mode
rate-limit handling and unified error normalization where safe
```

### Native bitbank Adapter Still Required

Do not rely on CCXT as the only bitbank adapter. Keep native bitbank modules for:

```text
public socket.io v4 streams
raw payload recording
bitbank-specific sequence handling
bitbank-specific depth_whole + depth_diff reconstruction
/spot/status and /spot/pairs validation
circuit-break-aware BBO validation
post_only behavior verification
live-trading gates
withdrawal endpoint exclusion
```

### CCXT Safety Rules

```text
- CCXT is allowed in MVP for public REST convenience and smoke tests.
- CCXT must not submit real orders in MVP.
- Any CCXT private call must go through the same LiveOrderIntent -> live_gates -> execution adapter path.
- Never call withdraw-related CCXT methods.
- For live create_order, require type=limit and params containing post_only=true or the bitbank-specific equivalent.
- After any CCXT-created order, reconcile using bitbank order_id and bitbank-native order status semantics.
- If CCXT behavior conflicts with official bitbank API docs, official bitbank docs win.
```

Recommended dependency:

```toml
ccxt = "^4"
```

Add a thin wrapper instead of importing CCXT throughout the codebase:

```text
src/ghost_amm/exchange/ccxt_gateway.py
```

The wrapper should expose only the methods this project explicitly permits. Core AMM/replay/risk code must not import `ccxt` directly.

## Preferred Tech Stack

Use this unless there is a strong reason not to:

```text
Language: Python 3.12+
Dependency manager: uv or Poetry
Data validation: pydantic
Storage format: Parquet via pyarrow
Testing: pytest
Numerics: numpy, pandas
Config: YAML or TOML
CLI: typer or argparse
REST exchange convenience: ccxt free/open-source package, wrapped by ccxt_gateway.py
WebSocket/socket.io: python-socketio or an equivalent socket.io v4 client
```

Keep interfaces clean enough that low-latency components can later be rewritten in Rust/Go if needed.

---

## Repository Structure

Create a project structure like this:

```text
ghost-amm/
  README.md
  pyproject.toml
  configs/
    default.yaml
  data/
    raw/
    replay/
    reports/
  src/
    ghost_amm/
      __init__.py
      cli.py
      config.py
      events.py
      recorder/
        __init__.py
        base.py
        mock_recorder.py
        bitbank_public_recorder.py
        bitbank_normalizer.py
      replay/
        __init__.py
        engine.py
        fill_model.py
      dryrun/
        __init__.py
        public_stream_engine.py
      exchange/
        __init__.py
        ccxt_gateway.py
        bitbank_public.py
        bitbank_private.py
        bitbank_rules.py
        bitbank_paper_executor.py
      market/
        __init__.py
        orderbook.py
        fair_price.py
        shock.py
      amm/
        __init__.py
        inventory.py
        quote_surface.py
        projector.py
      risk/
        __init__.py
        kernel.py
      execution/
        __init__.py
        order_state.py
        live_gates.py
      analytics/
        __init__.py
        metrics.py
        report.py
  tests/
    test_bitbank_rules.py
    test_bitbank_orderbook_reconstruction.py
    test_bitbank_live_gates.py
    test_ccxt_gateway_safety.py
    test_public_stream_dryrun_no_private_calls.py
    test_fair_price.py
    test_inventory_skew.py
    test_quote_surface.py
    test_fill_model.py
    test_replay_determinism.py
```

---

## Event Model

The project must use an event-driven architecture.

Define typed event classes with pydantic or dataclasses. At minimum:

```text
OrderBookSnapshot
OrderBookDelta
TradeEvent
ForcedFlowEvent
BitbankTickerEvent
BitbankStatusEvent
BitbankPairSpecEvent
BitbankRawEvent
MarkPriceEvent
VirtualOrderPlaced
VirtualOrderCanceled
VirtualFill
LiveOrderIntent
LiveOrderBlocked
DryRunHeartbeat
CcxtRestCallBlocked
RiskStateEvent
```

Each event must include:

```text
event_id: str
ts_exchange: int | float
ts_local: int | float
venue: str
symbol: str
event_type: str
sequence: int | str | None
payload: dict
raw_payload: dict | None
```

Use exchange timestamp if available. Keep local receive timestamp too.

Events must be serializable to JSONL and Parquet.

---

## Recorder MVP

Implement a recorder abstraction.

```python
class EventRecorder:
    async def run(self) -> None:
        ...
```

For MVP, include:

1. `MockRecorder` that generates deterministic synthetic bitbank-shaped events.
2. `BitbankPublicRecorder` that records public bitbank WebSocket data for `btc_jpy` without API keys.
3. `PublicStreamDryRunEngine` that consumes normalized live public events and emits virtual orders/fills only.
4. File writer that stores events as JSONL and/or Parquet.
5. Optional `CcxtGateway` public REST smoke tests for ticker/orderbook/trades snapshots.

The first implementation must be testable offline. Real bitbank public data recording and public-stream dry-run are allowed in the MVP; private authenticated order submission is not.

Synthetic data should include scenarios such as:

```text
normal market
spread widening
sudden sell shock
sudden buy shock
order book thinning
book rebuilding after shock
forced-flow event burst
```

---

## Fair Price Engine

Implement a fair price engine. For the bitbank MVP, the default fair price is the reconstructed `btc_jpy` mid price. Multi-source fair price is optional and must use JPY-denominated sources or explicit JPY conversion.

For MVP, support two modes:

### Mode 1: Single-venue mid

```text
fair = (best_bid + best_ask) / 2
```

### Mode 2: Multi-source median

```text
fair = median(valid_mid_prices)
```

The engine must ignore invalid books:

```text
missing bid
missing ask
bid >= ask unless a dedicated circuit-break mode is implemented
stale timestamp
spread too wide
non-JPY reference without explicit FX conversion
```

Output:

```python
FairPriceState(
    fair: float,
    source_count: int,
    spread_bps: float,
    is_valid: bool,
    reason: str | None,
)
```

---

## Inventory Model

The bot has base and quote inventory.

For BTC/JPY:

```text
base = BTC
quote = JPY
```

Compute equity:

```text
equity = base_qty * fair + quote_qty
```

Compute current base ratio:

```text
base_ratio = base_qty * fair / equity
```

Compute inventory skew:

```text
z = base_ratio - target_base_ratio
```

Interpretation:

```text
z > 0: too much BTC
z < 0: too little BTC
```

The inventory engine must handle:

```text
zero equity
negative balances disallowed by default
invalid fair price
position limits
```

---

## Ghost AMM Quote Surface

Generate virtual bid/ask quotes from fair price and inventory skew.

Use exponential distance from fair price:

```text
bid_i = fair * exp(-(half_spread + i * step + skew))
ask_i = fair * exp( +(half_spread + i * step - skew))
```

Where:

```text
half_spread = half_spread_bps / 10_000
step = step_bps / 10_000
skew = skew_strength_bps * z / 10_000
```

Behavior:

```text
If BTC is overweight:
  bids move farther away
  asks move closer
  ask sizes increase
  bid sizes decrease

If BTC is underweight:
  bids move closer
  asks move farther away
  bid sizes increase
  ask sizes decrease
```

Size rule:

```text
bid_size = base_order_size * exp(-size_skew_strength * z)
ask_size = base_order_size * exp( size_skew_strength * z)
```

Clamp sizes with:

```text
min_order_size
max_order_size
max_total_quote_exposure
max_total_base_exposure
```

Round prices and sizes:

```text
price -> tick_size
size -> lot_size
```

All generated orders must be virtual and post-only by design.

---

## Shock / Forced-Flow Activator

Implement a shock score that controls how strongly the AMM quote surface appears.

The activator should combine at least these features:

```text
forced_flow_notional_recent
recent_taker_buy_notional
recent_taker_sell_notional
orderbook_depth_20bps
spread_bps
fair_price_dislocation_bps
book_rebuild_score
```

A simple MVP activation formula is acceptable:

```text
force_ratio = forced_flow_notional_5s / max(depth_20bps, epsilon)
activation = sigmoid(temperature * (force_ratio - threshold))
```

But it must support extension later.

Activation range:

```text
0.0 = asleep
1.0 = fully active
```

Quote size should be scaled by activation:

```text
effective_order_size = base_order_size * activation
```

For bitbank, the activator must work without liquidation data. Use `transactions_btc_jpy`, `depth_diff_btc_jpy`, and reconstructed depth to infer forced-flow pressure.

Do not activate immediately on the first shock tick. Add a configurable delay/cooldown:

```text
shock_detection_window_ms
minimum_wait_after_shock_ms
activation_decay_ms
```

The bot should avoid catching the first falling knife. It should prefer aftershock / book-rebuild conditions.

---

## Order Projector

The order projector converts the quote surface into virtual orders.

Responsibilities:

```text
create virtual post-only orders
cancel stale virtual orders
replace quotes when fair price moves
avoid crossing the current best bid/ask
avoid quoting when risk kernel blocks trading
```

Virtual orders must include:

```text
order_id
venue
symbol
side
price
size
post_only = true
created_at
expires_at
reason
quote_level
activation
inventory_skew
fair_price_at_creation
```

Order projector must never submit live orders in the MVP.

For post-MVP bitbank paper/live execution, the projector should emit `LiveOrderIntent` objects, and a separate execution adapter should decide whether those intents pass live gates. Strategy code must never call bitbank private REST directly.

---

## Conservative Fill Model

Do not use naive candle fills.

A virtual order can be filled only if the event replay shows enough opposite-side trade flow or book movement to plausibly consume queue ahead.

Implement a conservative queue model:

```text
When a virtual order is placed at price P:
  estimate queue_ahead at P from order book depth

For each subsequent trade/orderbook event:
  reduce queue_ahead only when aggressive flow reaches P

Fill only after queue_ahead <= 0
```

For MVP, a simplified model is okay, but it must be pessimistic rather than optimistic.

Support parameters:

```text
queue_ahead_multiplier
maker_fee_bps
taker_fee_bps
bitbank_dynamic_fee_rates
latency_ms
min_resting_time_ms
cancel_latency_ms
```

The fill model must record:

```text
fill_price
fill_size
fill_ts
fee
queue_ahead_estimate
fair_at_fill
fair_after_1s
fair_after_5s
fair_after_30s
```

---

## Replay / Backtest Engine

Implement deterministic event-replay backtesting.

Input:

```text
recorded event file
config file
initial inventory
```

Process:

```text
1. Load events sorted by timestamp and sequence.
2. Rebuild order book state.
3. Update fair price state.
4. Update shock/activation state.
5. Update inventory state.
6. Generate quote surface.
7. Project/cancel virtual orders.
8. Simulate fills conservatively.
9. Apply virtual fills to inventory.
10. Emit replay results and metrics.
```

Requirements:

```text
Same input + same config => exactly same output.
No randomness unless seeded.
Every virtual decision should be explainable from prior events.
No lookahead leakage.
```

Add a test that replaying the same file twice produces identical fills and PnL.

---

## Public-Stream Dry-Run Engine

Implement a dry-run mode that uses live bitbank public streams but never submits orders.

Input:

```text
bitbank public socket.io stream
config file
initial virtual inventory
optional ccxt public REST snapshot cross-check
```

Process:

```text
1. Connect to ticker, transactions, depth_whole, and depth_diff.
2. Normalize incoming events.
3. Rebuild the order book in real time.
4. Run the same fair-price, shock, inventory, AMM, risk, projector, and fill-model pipeline as replay.
5. Emit virtual orders and virtual fills.
6. Persist all raw events, normalized events, virtual decisions, and metrics.
```

Requirements:

```text
no API keys required
no private endpoint calls
no real orders
same quote-generation code as replay
same risk kernel as replay/live
dry-run output should be replayable later as an event file
```

CLI example:

```bash
ghost-amm dry-run-bitbank-public   --pair btc_jpy   --config configs/default.yaml   --out data/reports/dryrun_btc_jpy
```

## Risk Kernel

Implement a risk kernel that can block quoting.

Risk checks:

```text
invalid fair price
spread too wide
book too thin
activation too low
inventory too skewed
max drawdown exceeded
max daily loss exceeded
too many virtual fills in short time
stale market data
bitbank status not NORMAL
bitbank pair disabled or order-stopped
invalid bitbank pair metadata
sequence ordering violation
latency too high
config violation
```

Output:

```python
RiskDecision(
    allow_quote: bool,
    allow_buy: bool,
    allow_sell: bool,
    max_order_size: float,
    reason: str | None,
)
```

The risk kernel should be called before projecting orders.

---

## Analytics

Generate a report after replay.

Metrics to include:

```text
total PnL
realized PnL
unrealized PnL
fees paid
number of virtual orders
number of virtual fills
fill rate
average spread captured
average adverse selection after 1s / 5s / 30s
PnL by shock event
PnL outside shock events
max inventory skew
average inventory holding time
max drawdown
worst fill
best fill
risk-blocked quote count
```

Important adverse selection metric:

```text
For buy fill:
  adverse_5s = fair_after_5s - fill_price

For sell fill:
  adverse_5s = fill_price - fair_after_5s
```

Positive value means the fill was favorable relative to later fair price.

Generate:

```text
CSV summary
JSON summary
Markdown report
```

No need for a complex web UI in the MVP.

---

## CLI Commands

Implement a CLI with commands like:

```bash
ghost-amm generate-synthetic \
  --scenario sell_shock \
  --venue synthetic_bitbank \
  --pair btc_jpy \
  --out data/raw/sell_shock.jsonl

ghost-amm record-bitbank-public \
  --pair btc_jpy \
  --channels ticker,transactions,depth_whole,depth_diff \
  --out data/raw/bitbank_btc_jpy.jsonl

ghost-amm dry-run-bitbank-public \
  --pair btc_jpy \
  --config configs/default.yaml \
  --out data/reports/dryrun_btc_jpy

ghost-amm ccxt-smoke-test \
  --exchange bitbank \
  --symbol BTC/JPY \
  --public-only

ghost-amm validate-bitbank-rules \
  --pair btc_jpy \
  --config configs/default.yaml

ghost-amm replay \
  --events data/raw/sell_shock.jsonl \
  --config configs/default.yaml \
  --out data/reports/sell_shock

ghost-amm report \
  --replay data/reports/sell_shock/replay.parquet \
  --out data/reports/sell_shock/report.md
```

---

## Default Config

Create `configs/default.yaml` with reasonable bitbank-oriented values:

```yaml
symbol: BTC/JPY
venue: synthetic_bitbank
market_type: spot
pair: btc_jpy

bitbank:
  public_ws_url: "wss://stream.bitbank.cc/socket.io/?EIO=4&transport=websocket"
  public_rest_url: "https://public.bitbank.cc"
  private_rest_url: "https://api.bitbank.cc/v1"
  pair: btc_jpy
  channels:
    - ticker_btc_jpy
    - transactions_btc_jpy
    - depth_whole_btc_jpy
    - depth_diff_btc_jpy
  fetch_pair_spec_on_start: true
  fetch_status_on_start: true
  require_status_normal: true
  require_post_only: true
  forbid_market_orders: true
  forbid_margin_orders: true
  forbid_withdrawal_endpoints: true
  sequence_policy: monotonic_not_consecutive
  block_on_crossed_book: true
  clock_drift_limit_ms: 1000

ccxt:
  enabled: true
  exchange_id: bitbank
  public_rest_only_in_mvp: true
  allow_private_calls: false
  allow_order_submission: false
  forbid_withdrawal_methods: true
  use_enable_rate_limit: true
  require_official_bitbank_docs_override: true

execution:
  mode: replay          # replay | dry_run_public | paper_private | live
  venue: bitbank
  enable_live_orders: false
  require_live_env_var: true
  live_env_var_name: GHOST_AMM_ENABLE_LIVE
  live_env_var_value: I_ACCEPT_RISK
  cancel_on_start: false
  refuse_if_unmanaged_orders_exist: true
  max_active_orders_per_pair: 20
  post_only_only: true

market:
  stale_after_ms: 3000
  max_spread_bps: 50
  min_depth_20bps_jpy: 5000000
  reject_circuit_break_book: true

inventory:
  initial_base_qty: 0.01
  initial_quote_qty: 150000
  target_base_ratio: 0.5
  max_abs_skew: 0.35
  negative_balances_allowed: false

amm:
  levels: 6
  base_order_size: 0.0002
  half_spread_bps: 8
  step_bps: 10
  skew_strength_bps: 80
  size_skew_strength: 3.0
  min_order_size_fallback: 0.0001
  max_order_size: 0.002
  tick_size_fallback_jpy: 1
  lot_size_fallback_btc: 0.0001
  use_bitbank_pair_spec_rounding: true

shock:
  forced_flow_window_ms: 5000
  depth_bps: 20
  threshold: 1.0
  temperature: 1.5
  minimum_wait_after_shock_ms: 2000
  activation_decay_ms: 30000
  min_activation_to_quote: 0.15
  infer_from_bitbank_transactions: true
  infer_from_depth_thinning: true
  infer_from_spread_widening: true

fill_model:
  queue_ahead_multiplier: 1.5
  maker_fee_bps_fallback: 0
  taker_fee_bps_fallback: 10
  use_bitbank_dynamic_fee_rates: true
  latency_ms: 150
  cancel_latency_ms: 150
  min_resting_time_ms: 500

risk:
  max_drawdown_pct: 5
  max_daily_loss_pct: 3
  max_virtual_fills_per_minute: 20
  block_on_sequence_ordering_violation: true
  block_on_bitbank_status_not_normal: true
  block_on_pair_stop_flags: true
  block_on_unfetched_pair_spec: true
```

---

## Testing Requirements

Write unit tests for:

```text
fair price calculation
invalid book filtering
inventory skew calculation
quote surface behavior when overweight
quote surface behavior when underweight
price and size rounding
bitbank pair metadata validation
bitbank amount/price precision handling
bitbank order-book reconstruction from whole + diff streams
bitbank live-gate blocking
CCXT gateway blocks private/order/withdrawal calls in MVP
public-stream dry-run never calls private endpoints
activation score
risk blocking
fill model pessimism
replay determinism
```

Important tests:

1. If inventory is overweight, asks should move closer and bids should move farther.
2. If inventory is underweight, bids should move closer and asks should move farther.
3. If activation is zero, no orders should be projected.
4. If spread is too wide, risk kernel should block quotes.
5. Same replay input should produce exactly the same result twice.
6. The fill model should not fill merely because price touched a level.
7. bitbank live execution must be blocked unless all live gates pass.
8. bitbank order-book reconstruction must treat sequence IDs as monotonic, not necessarily consecutive.
9. If bitbank status is not NORMAL, the risk kernel must block new quotes.
10. Public-stream dry-run must emit virtual orders/fills only and must not require API keys.
11. CCXT gateway must not expose withdrawal methods or real order submission in MVP mode.

---

## Acceptance Criteria

The MVP is complete when:

```text
- The repository installs cleanly.
- Synthetic event files can be generated.
- Event-replay backtests can run on synthetic events.
- Public-stream dry-run can run on bitbank public data without API keys.
- The Ghost AMM quote surface generates inventory-aware virtual orders.
- Shock activation changes order size or quoting intensity.
- Conservative virtual fills are simulated.
- Inventory changes after virtual fills.
- Risk kernel can block quoting.
- A Markdown report is generated after replay.
- Unit tests pass.
- Replay is deterministic.
- No live order submission is reachable in MVP mode.
- CCXT is wrapped behind ccxt_gateway.py and cannot submit orders in MVP mode.
- The default symbol is BTC/JPY and the default pair is btc_jpy.
- The bitbank public recorder can normalize ticker, transactions, depth_whole, and depth_diff events.
- The bitbank pair-rule validator checks unit amount, max amount, precision, fees, and status flags.
- The codebase contains no withdrawal execution path.
```

---

## Implementation Order

Build in this order:

1. Project skeleton and config loader.
2. Event model.
3. Order book state model.
4. Synthetic bitbank-shaped event generator.
5. bitbank public normalizer and pair-rule model.
6. CCXT gateway wrapper for public REST smoke tests and market metadata cross-checks.
7. bitbank order-book reconstruction from depth_whole + depth_diff.
8. Fair price engine.
9. Inventory engine.
10. Ghost AMM quote surface.
11. Shock activator.
12. Risk kernel.
13. Order projector.
14. Conservative fill model.
15. Replay / backtest engine.
16. Public-stream dry-run engine.
17. Analytics and Markdown report.
18. bitbank public recorder.
19. Tests.
20. README with usage examples.
21. Post-MVP only: bitbank paper/private execution adapter behind live gates.

---

## Design Principles

Follow these principles:

```text
Event replay over candle backtesting.
Public-stream dry-run before any private/live execution.
Inventory curve over buy/sell signals.
Determinism over cleverness.
Conservative fills over optimistic fills.
No lookahead.
No real orders in MVP.
Real trading, when added, is bitbank-only and post-only.
Explain every fill.
Measure adverse selection.
Prefer high-liquidity JPY pairs.
Kill quoting when data quality or bitbank status is bad.
```

---

## Future Extensions

After MVP, possible extensions:

```text
bitbank private paper-trading adapter
CCXT-assisted private adapter behind hard gates
bitbank live execution adapter behind hard gates
multi-venue fair price median using JPY-converted references
other domestic JPY venue references
funding-aware inventory skew outside bitbank spot only
perp hedge simulator outside bitbank spot only
Rust/Go execution engine
multi-symbol JPY portfolio inventory surface
```

Do not implement these until the MVP is working and tested.

---

## Implementation Status - 2026-05-11 JST

Current milestone:

```text
MVP virtual-trading prototype is implemented.
Current active next step is stable bitbank public-data recording for real-data event replay.
```

Completed:

```text
- Python package and CLI skeleton
- default BTC/JPY / btc_jpy config
- typed event model and JSONL serialization
- synthetic bitbank-shaped event generator
- bitbank public normalizer for ticker, transactions, depth_whole, depth_diff
- bitbank pair/status REST validation
- deterministic order-book reconstruction with monotonic sequence checks
- fair-price, inventory, quote-surface, shock, risk, projector, fill-model pipeline
- deterministic replay engine with Markdown/JSON/CSV reports
- public-stream dry-run using public data only
- CCXT wrapper that blocks private/order/withdrawal paths in MVP
- live gate scaffolding that emits LiveOrderBlocked instead of real orders
- tests for the major MVP safety and deterministic replay requirements
```

Verification already run:

```text
uv run --extra test pytest -q
ghost-amm generate-synthetic --scenario sell_shock ...
ghost-amm replay --events data/raw/sell_shock.jsonl ...
ghost-amm validate-bitbank-rules --pair btc_jpy ...
ghost-amm dry-run-bitbank-public --pair btc_jpy ... --max-events 20
```

New recorder-hardening work added after the MVP checkpoint:

```text
- record-bitbank-public writes pair spec and status metadata at the start of recording.
- JSONL recording is flushed incrementally instead of only at process exit.
- recorder supports event-count and byte-size file rotation.
- recorder reconnects and rejoins public channels after connection failures.
- recorder emits connection/error health events into the JSONL stream.
- inspect-recording summarizes event coverage, channel rooms, depth sequence ordering, and replay readiness.
- short live smoke recording was replayed successfully.
```

Recommended next command for real-data BK:

```powershell
uv run --with "python-socketio[client]>=5" --with aiohttp ghost-amm record-bitbank-public `
  --pair btc_jpy `
  --config configs/default.yaml `
  --out data/raw/bitbank_btc_jpy_1h.jsonl `
  --timeout-sec 3600 `
  --rotate-every-bytes 104857600 `
  --flush-every-events 1 `
  --max-reconnects 100

uv run ghost-amm inspect-recording data/raw/bitbank_btc_jpy_1h.jsonl --strict

uv run ghost-amm replay `
  --events data/raw/bitbank_btc_jpy_1h.jsonl `
  --config configs/default.yaml `
  --out data/reports/bitbank_btc_jpy_1h
```

Notes:

```text
- API keys are still not required for BK/replay.
- A short recording can pass replay-minimal inspection even if no trade event occurs during a quiet window.
- Use inspect-recording --strict for longer captures where all public channels should have emitted events.
- Real order submission remains out of scope and blocked in MVP mode.
```


---

## External Documentation to Check During Implementation

Use the official bitbank API documentation as the source of truth during implementation:

```text
bitbank API docs repository:
https://github.com/bitbankinc/bitbank-api-docs

Public API docs:
https://github.com/bitbankinc/bitbank-api-docs/blob/master/public-api_JP.md

Public stream docs:
https://github.com/bitbankinc/bitbank-api-docs/blob/master/public-stream_JP.md

Private REST API docs:
https://github.com/bitbankinc/bitbank-api-docs/blob/master/rest-api_JP.md
```

Also check CCXT official documentation/source when implementing the optional CCXT gateway:

```text
CCXT docs:
https://docs.ccxt.com/

CCXT GitHub:
https://github.com/ccxt/ccxt

CCXT bitbank adapter:
https://github.com/ccxt/ccxt/blob/master/python/ccxt/bitbank.py
```

Do not assume pair precision, fee rates, minimum sizes, active status, or stop flags. Fetch them at runtime and fail closed when they are unavailable.
Do not assume CCXT and native bitbank responses are semantically identical. Normalize them explicitly and prefer official bitbank docs when there is a conflict.
