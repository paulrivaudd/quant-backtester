# Architecture

State on 2026-09-27. This document describes how the project is divided, how
a backtest session unfolds and which mechanisms ensure that a result is right
and reproducible. The development rules are in [CLAUDE.md](../CLAUDE.md).

| Document | For |
|---|---|
| [NEW_STRATEGY_GUIDE.md](NEW_STRATEGY_GUIDE.md) | running a first offline run, writing a signal and a strategy, judging them |
| [DATA.md](DATA.md) | the `data` layer in detail; adding an instrument or a source |
| [FORMULAS.md](FORMULAS.md) | every formula of the code: signals, costs, portfolio, metrics |
| [CORPORATE_ACTIONS.md](CORPORATE_ACTIONS.md) | splits, dividends, spin-offs: what is handled and what is not |
| [GLOSSARY.md](GLOSSARY.md) | the finance terms, with the names the code uses |
| [IMPROVEMENTS.md](IMPROVEMENTS.md) | what remains to be done |

## 1. What the project seeks to guarantee

The framework backtests daily strategies, and it aims first at **trust** in a
figure, not at speed. Every choice below serves three properties:

1. **No information from the future.** A decision reads only what was
   published at its instant. What a data point describes (its date) and the
   moment it becomes available are two distinct things.
2. **Nothing implicit.** Calendars, costs, execution prices, windows and
   parameters are declared and recorded with the result.
3. **Reproducible to the bit.** The same code, the same committed
   configuration and the same store give the same numbers. A `run_id` proves
   it.

## 2. The layers and the dependency rule

```
src/quant_backtester/
    data/        local Parquet store, providers, calendars, point-in-time reading
      │
    signals/     the market at an instant  ->  one number per instrument (+ a status)
      │
    portfolio/   requested target  ->  admissible target (weights, limits), state of the book
      │
    execution/   admissible target  ->  quantities on lots, orders, fills, rejects, costs
      │
    backtest/    the loop that advances time, the decision context, the runner
      │
    analytics/   gross/net performance, benchmark, attribution, uncertainty
      │
    strategies/  rules composed from the layers above
      │
    research/    hypotheses, register of experiments, run archives, paper trading
```

Dependencies go **one way only**: a module may import a layer placed above its
own in this diagram, never a layer placed below. If a layer needs information
that comes from below, it is passed in as an argument.
`tests/test_package_structure.py` checks this rule on every module.

**One exception, and only one: `backtest/runner.py`.** It is a composition
façade. It builds the engine, runs a strategy and returns its report. It
therefore imports `strategies.base` (the contract of a strategy) and
`analytics` (the report, the curves, the charts). The test declares it in
`COMPOSITION_FACADES`, and no other module may do the same. The rest of
`backtest/`, in particular `engine.py` and `context.py`, follows the rule.
Strategies import `backtest/context.py`, placed above them: that is an allowed
import.

Three more rules are checked by the same tests:

- `strategies/` and `analytics/` never import `quant_backtester.data`. A
  strategy therefore cannot open a reader and read beyond its instant.
- No layer imports `research/`.
- Only `data/` performs network I/O.

| Package | Role | Key modules |
|---|---|---|
| `data/` | Ingestion, checking, storage and reading of market series | `sources/`, `schemas`, `normalizer`, `validator`, `crosscheck`, `revisions`, `bar_corrections`, `corporate_actions`, `known_gaps`, `conflict_reviews`, `repository`, `updater`, `reader`, `calendars`, `instruments`, `universes` |
| `signals/` | Reusable transformations of a history into a number | `base` (`Signal`, `SignalResult`), `windows`, `types`, `engine`, `snapshot`, `price/`, `risk/`, `level/`, `cross_sectional/` |
| `portfolio/` | What a book is allowed to hold, and what it holds | `targets` (`TargetAllocation`), `allocation` (`PortfolioModel`, `ConstrainedTarget`), `constraints`, `limits` (`PortfolioLimits`), `holdings`, `state` (`PortfolioState`), `view` |
| `execution/` | What the market does with an order | `model` (`ExecutionModel`, `Sizing`), `costs` (`CostModel`), `rounding` (lots), `orders`, `fills` (`Fill`, `ExecutionReject`) |
| `backtest/` | Time | `config` (`BacktestConfig`), `engine`, `timetable`, `schedule`, `context` (`StrategyContext`), `market`, `records` (`BacktestRecord`), `result` (`BacktestResult`), `runner` (`StrategyRunner`, `StrategyResult`) |
| `analytics/` | What a run produced | `config` (`AnalyticsConfig`), `curves` (including `aligned_equity_curves`), `performance`, `relative` (`RelativePerformanceStats`: alpha, beta, tracking error, information ratio), `report`, `comparison`, `attribution`, `contribution`, `uncertainty`, `plots`, `quality` (a 0-100% score against the market, versioned rules `QUALITY_V1`), `volatility_forecast` (ex post quality of a variance forecast: QLIKE), `return_forecast` (two-session return forecast: mean, sign, joint loss) |
| `strategies/` | The rules | `base` (`Strategy`), `functional` (`@strategy`), `catalogue` (codes `SA1` to `SA16`), one module per strategy at the root (`SA1_world_ma20_benchmark` … `SA16_risk_budget`), `adaptive/` (the rules they share) |
| `ml/` | The fitted models (outside the layers, see below) | `config` (`NeuralStrategyConfig`), `features` (`NeuralFeatureBuilder`, `FeatureScaler`), `network` (`NeuralAllocator`), `artifacts` (`NeuralArtifact`), `dataset` (`ForwardOpenReturnBuilder`, purge), `training` (`calibrate_neural_strategy`), `signatures/` (`SignatureVariant`, `SignatureArtifact`, `SignatureModelSchedule`, `calibrate_month`) |
| `research/` | The research discipline | `references` (the books a study measures itself against) |

`provenance.py` (the git state of the code that produced a result) and
`numbers.py` (guards on numeric parameters) cut across the layers.

`ml/` is not a layer. `config`, `features`, `network` and `artifacts` read
nothing above `signals/`: they are what a model's signal (`signals/ml/`) and
strategy (`strategies/SA14_neural_allocation.py`) import. `dataset` and
`training` run offline, **before** any backtest: they compose the reader, the
runner and the strategy, like `backtest/runner.py`, and no layer imports them.
PyTorch is an optional dependency (`uv sync --extra ml`) that only these three
folders import; the tests of `tests/test_package_structure.py` check the three
rules. `ml/signatures/` follows the same split: `config`, `models` and
`artifacts` import only NumPy and `signals/` - that is what
`signals/ml/signature_return.py` and the `SA13` strategy read - and only
`training` imports PyTorch and the reader.

## 3. One session, three instants

A daily backtest often speaks of "the day's price", which does not exist. Each
session of the reference calendar (XPAR, Euronext Paris) has three instants,
declared in `backtest/timetable.py` and recorded with the result:

```
 session D-1                              session D
 ─────────────────────────────┬───────────────────────────────────────────────────
                        23:00 │ 09:01             17:30       23:00         23:00
                   DECISION   │ EXECUTION         Paris       VALUATION     DECISION
                   (reads all │ (orders of D-1    close       (book marked  (signals of D,
                    that is   │  filled at the                at the known  target for D+1)
                    published)│  opening price)               closes)
```

- **Decision, 23:00 Paris.** Late enough for the same day's New York close to
  be published: a US session and a European session are thus comparable. The
  signals are computed and the strategy sets a target.
- **Corporate action check, before the open.** If a held position goes
  ex-date on an action (split, dividend…) since the previous session, the run
  stops with `UnsupportedCorporateAction`. It stops even if the strategy was
  about to sell at that open, because the sale would take place after the
  event. See [CORPORATE_ACTIONS.md](CORPORATE_ACTIONS.md).
- **Execution, the next session's open.** Orders are sized and filled at the
  opening auction price (`Sizing.AT_AUCTION`, the default). `Sizing.AT_DECISION`
  freezes the quantities at the decision close, like an order placed the day
  before.
- **Valuation, after the close.** The book is marked at the closing prices
  known at that instant, then comes the next decision.

The order of the instants is checked: a decision taken before the valuation of
its own book would receive a portfolio from its future. The gap between a US
close and the next European open is modelled explicitly. It is never
approximated as "the next bar".

## 4. How a run unfolds

```
StrategyRunner.run(strategy, universe, start, end, schedule=...)
 │
 ├─ strategy.validate()                    complete and serialisable configuration
 ├─ reference calendar -> sessions         (never freq="B")
 │
 └─ BacktestEngine, for each session:
      0. check        held position going ex-date -> UnsupportedCorporateAction
      1. execution    pending orders -> fills at the opening price, costs, rejects
      2. valuation    book marked at the available closes
      3. if the session is in the schedule:
           reader.at(23:00)              -> PointInTimeReader frozen at that instant
           SignalEngine.compute(...)     -> SignalSnapshot (one result per signal)
           StrategyContext(...)          -> signals, market, book, the day's universe
           strategy.decide(ctx)          -> TargetAllocation
           portfolio: limits, lots       -> orders for the next session
      4. BacktestRecord of the session   (everything that happened, kept)
 │
 └─ StrategyResult: records, gross/net report(), compare() to the benchmark,
                    run_id, the strategy's fingerprint, state of the code
```

Only `backtest/engine.py` advances time. The signals and the strategy receive
an instant and the history available at that instant, nothing else.

## 5. The `data` layer

The detail is in [DATA.md](DATA.md).

### Ingestion

```
provider (Yahoo, Euronext, FRED, ALFRED, ECB)
   │  sources/<provider>.py         the only place that knows the provider's columns
   ▼
raw/          immutable downloads, never rewritten
   │  normalizer.py                 canonical schema, availability timestamp (UTC)
   │  validator.py                  rules by asset class
   │  crosscheck.py                 several sources -> one checked series, field by field
   ▼
clean/checked_bars/                 what strategies read
```

`scripts/update_market_data.py` drives the ingestion. A promotion writes the
bars, the check verdicts, the journal of revisions and that of the applied
downloads **in a single transaction**: the files are prepared under
`.pending/`, a SHA-256 manifest is written, then everything is published
together. A lock (`market_data/.lock`) is shared for runs and exclusive for
writes; a concurrent writer receives `StoreBusy`.

### Committed metadata

`market_data/metadata/` is versioned configuration, not data:

| File | Content |
|---|---|
| `instruments.toml` | each series: type, calendar, publication, tradability, mandatory `history_basis` and `history_note` |
| `calendars/` | sessions, actual opening and closing times, half-days |
| `universes.toml` | dated members (a name that left keeps its exit date) |
| `crosscheck.toml` | tolerances between sources |
| `known_gaps.toml` | known and explained holes |
| `conflict_reviews.toml` | conflicts between sources reviewed and settled (status `REVIEWED`) |
| `bar_corrections.toml` | broken bars deleted (never repaired), with the reason |
| `accepted_revisions.toml`, `corporate_actions.toml` | reviewed revisions and events |

### Point-in-time reading

`MarketDataReader.at(instant)` returns a frozen `PointInTimeReader`. Its
methods take **no** date argument: there is no expression that reads beyond
it. Each reading carries a status: `OK`, `STALE` (last value too old),
`NOT_LISTED` (the instrument did not exist) or `MISSING` (a hole, or a session
contested by two sources). A hole is never filled by carrying a price forward.
The age of a value is counted in sessions of the reference calendar.

## 6. The `signals` layer

A **signal** turns the market at an instant into one number per instrument.
It decides nothing: "this fund's momentum is +8.1%" is a signal, "buy the best
two" is a strategy.

- A signal is a **frozen dataclass**. `definition()` lists every parameter
  that changes the number, and `fingerprint()` is its hash.
- A window declares its contract (`WindowSpec`): `CONSECUTIVE_SESSIONS`
  (N sessions held by the venue, with no hole) or `AVAILABLE_OBSERVATIONS`
  (N published observations, for an indicator). `signals/windows.py` is the
  only place that loads a window, and it refuses one that does not match the
  contract. `tail(N)` is not a window.
- The price basis is explicit: `RAW` (quotation) or `ADJUSTED` (adjusted for
  the actions known at the decision instant).
- Each result carries a status per instrument: `OK`, `NOT_LISTED`,
  `MISSING_INPUT`, `STALE_INPUT`, `INSUFFICIENT_HISTORY`,
  `NON_CONSECUTIVE_HISTORY`, `INSUFFICIENT_CROSS_SECTION` or `INVALID_INPUT`.
  A number exists only if the status is `OK`, and `SignalResult` checks it.
- `SignalEngine` computes the declared signals and produces a
  `SignalSnapshot`. A `SignalRequest` computes a signal on a universe of its
  own, for instance the VIX read as a gauge without being held.

Available signals: `ReturnSignal`, `MomentumSignal`, `MeanReversionSignal`,
`MovingAverageTrendSignal`, `MovingAverageCrossSignal` (price),
`RealizedVolatilitySignal`, `CurrentDrawdownSignal` (risk),
`LevelChangeSignal`, `LevelZScoreSignal` (published series),
`CrossSectionalRank` (ranking), `GarchVolatilitySignal` and
`EwmaVolatilitySignal` (models, `signals/models/garch.py`),
`ArimaGarchForecastSignal` (`signals/models/arima_garch.py`),
`SignatureReturnSignal` (`signals/ml/signature_return.py`, features of
`signals/signatures/`), `SpanScaledVolatilitySignal`
(`signals/risk/span_volatility.py`: volatility over the last `N + 1` available
closes, each return divided by the square root of the sessions it spans, an
`AVAILABLE_OBSERVATIONS` contract declared, a hole of more than
`max_span_sessions` sessions refused).

## 7. Strategy and decision context

A strategy (`strategies/base.py`) declares its signals and takes a decision:

```python
class Strategy(ABC):
    def required_signals(self) -> Sequence[Signal | SignalRequest]: ...
    def decide(self, ctx: StrategyContext) -> TargetAllocation: ...
```

Its parameters are the fields of a frozen dataclass. They enter
`definition()` and `fingerprint()`, hence the identity of the run. The engine
checks that the definition did not change during the run (`StrategyMutated`).

`StrategyContext` (in `backtest/`, because the engine builds it) contains
everything a decision can see, frozen at one instant:

| Attribute / method | Role |
|---|---|
| `ctx.signal_value`, `signal_status`, `signal_value_or_none`, `signal` | read the snapshot |
| `ctx.top`, `bottom`, `where` | select names (`Selection`, which keeps the reason for those excluded) |
| `ctx.market.value`, `values`, `history` | read a raw series, with status and age |
| `ctx.portfolio` | the book: weights, quantities, average cost, cash invested |
| `ctx.universe` | the names the universe allows that day |
| `ctx.weights`, `equal_weight`, `cash`, `hold_positions`, `keep_and_buy` | express the target |

The target constructors refuse a book that nobody could hold: a negative
weight, a sum above 1, a name outside the universe or a non-tradable
instrument.

Pitfalls of the context: `signal_value` raises `UnusableSignal` if the status
is not `OK`, whereas `signal_value_or_none` returns `None`. `keep_and_buy`
splits a fraction of the **remaining cash** between new lines: it is not a
portfolio weight, and it refuses a line already held. `hold_positions` sends
no order, unless a limit cuts the book. `@strategy` records the qualified name
of the function, not its code: only the git state traces a change to its body.

### The reference books (`research/references.py`)

The strategies that are kept have a code and are described below, in the
catalogue. The three classes of this module are not candidates and are not in
the `strategies` package: they are the references and the control that the
studies measure a strategy against.

| Class | Exact rule | If the signal is unusable |
|---|---|---|
| `BuyAndHold(instruments)` | buys in equal parts then keeps the quantities; the weights drift. A name whose purchase failed is bought later with the remaining cash, without selling the lines already held (D5) | no signal |
| `EqualWeightRebalance(instruments)` | equal weights asked again at each decision, so it sells the winner and buys back the loser | no signal |
| `FixedWeights(weights)` | aims at constant weights and trades only when price drift moves it away from its target by more than the rebalancing band; its realised exposure is therefore not exactly its target. The diagnostics' control | no signal |

A rule on a single fund records what it read with
`ctx.considering({fund: status})`, passed as `among` to `cash`, `weights` or
`hold_positions`: a day in cash on a valid signal counts one instrument
considered, a day with no readable signal counts none and carries the status.
That is what lets the report count only the latter as "sessions with nothing
to choose from".

The reference scripts pass `top_n=1` on the two-fund universe. With the
default value `top_n=2`, the rotation would hold both.

### The catalogue (`strategies/catalogue.py`)

A strategy that is kept receives a **code** (family + number) and a short
**label**. The three spellings of a name follow from them and are never
written by hand:

| Use | Form | Example |
|---|---|---|
| table, figure, legend | `display_name` | `SA3 - smooth MA` |
| `strategy_id` of a result | `strategy_id` | `SA3_smooth_ma` |
| file name | `slug` | `sa3_smooth_ma` |

A single family, `SA`. The neural allocation was `ML1`, alone in its family,
until 2026-10-11: it is `SA14`, and the code `ML1` is not reassigned. Its
module imports PyTorch as soon as it is loaded, which its entry declares
(`extra = "ml"`). A code is assigned once, in the order of adoption, and is
never reused; the label may be reworded. `SA1` to `SA10` are the ten ETF rules
of 2026-10-03 (numbered 0 to 9 in their specification: `SA1` is the MA20
benchmark, `SA10` the ensemble), `SA11` the GARCH volatility control, `SA12`
the ARIMA-GARCH and `SA13` the neural signatures of 2026-10-10 (labels without
a dash), `SA14` the neural allocation. The three reference books are not
catalogued; the earlier examples and exercises were removed from the code on
2026-10-11. `entry("SA3")`, `entry_of(strategy)` and `family(Family.SA)` give
an entry; `entry.load()` imports the class on demand.

### SA14, the neural allocation (`strategies/SA14_neural_allocation.py`)

A small network (a shared encoder `Linear(100, 8)`, a hidden layer of 16, a
softmax over the buyable funds and cash) proposes weights every evening. It is
trained **before** the backtest (`scripts/SA14_run_neural_strategy.py`), then
frozen in an artifact identified by its content (`model_id`). The decision
caps, removes the weights under 1%, then compares with the book actually held:
`hold_positions` within the 3-point band (cash included), `weights`
otherwise, `cash` if an input is missing. Three safeguards specific to a
fitted model: the input is built by the same `NeuralFeatureBuilder` in
training and in decision; the future open→open returns are read only by
`ForwardOpenReturnBuilder`, on a reader frozen at the end of training; the
artifact carries its information cutoff date and a decision taken before it is
refused (`InformationCutoffError`).

### SA11, the GARCH volatility control (`strategies/SA11_garch_vol_control.py`)

`GarchVolControl` holds `ETF_WORLD` at `min(1, 12% / max(σ, 5%))`, where
`σ = sqrt(252 · h(t+1|t))` is the one-session forecast of a zero-mean
GARCH(1,1) with Student innovations. The model is **re-estimated at each
decision** on the 756 log returns (757 adjusted closes, consecutive sessions)
known at that instant; nothing is kept from one decision to the next, neither
model, nor starting point, nor cache. The 3-point band, the target and the
floor are those of `SA6`, its comparator.

- **Units.** Returns are multiplied by 100 for the optimiser only; everything
  that comes out of `forecast_garch` is in decimal units (daily variance, `ω`
  divided by 10,000, a volatility of 20% written `0.20`).
- **Fallback.** A fit that did not converge, is inadmissible (`α + β ≥ 1`,
  `ν ≤ 2`…) or gives an invalid forecast is replaced by an EWMA (0.94, seeded
  on 60 returns) of the **same valid window**. The signal stays `OK`: the
  value is usable, which does not mean that GARCH converged;
  `GarchVolatilitySignal.diagnose()` gives the source and the reason. A short,
  holed, stale or invalid window triggers neither fit nor fallback: cash.
- **What the forecast covers.** The close → close return; the order is
  executed at the next open. It is a proxy for the position's risk.
- **Dependency.** The estimation is done by `arch`, an optional dependency
  (extra `stats`), imported at fit time. The module, the class and the
  catalogue import without it; `validate()`, called by every run, raises
  `MissingDependency`.
- **Control.** `EwmaVolControl` applies the same rule to the EWMA alone, under
  a research identifier (`research_ewma94_vol_control`), without a catalogue
  code.

`analytics/volatility_forecast.py` judges the forecast **ex post**: pairing
origin → next session, QLIKE (`log q + r²/q`, with a metric floor of 1e-12
that is counted), squared error, standardised residuals.
`scripts/SA11_run_garch_study.py` keeps separate the common ranking, the
quality of the forecast and the economic test of the hypothesis (paired
bootstrap, a second real run at doubled costs).

### SA12, ARIMA-GARCH (`strategies/SA12_arima_garch.py`)

`ArimaGarch` holds `ETF_WORLD` while an ARIMA(1,0,1) forecasts a positive
return for **the first session an order can carry**, at a weight sized by the
variance of that return.

- **Chronology.** On the evening of `t`, the last known return is
  `r_t = log(O_t / O_{t-1})` on adjusted opens; the order is executed at
  `O_{t+1}`, so the return targeted is `r_{t+2}`, the **second step**. The
  adjusted opens come from `load_adjusted_open_window`: raw open × adjusted
  close / raw close, all three known at the decision instant.
- **Mean.** `mu_2` of the filtered state (`statsmodels`, state space,
  stationary initialisation, a single starting point, re-estimated every
  evening).
- **Risk.** A Student GARCH(1,1) on the 696 ARIMA innovations left after the
  first 60 are removed: `h_1`, then `h_2 = ω + (α + β) h_1`, and
  `v_2 = h_2 + (φ + θ)² h_1`, the variance of the two-step *return*. EWMA
  fallback on the same innovations (`h_2 = h_1`). A sequential two-stage
  estimation, not a joint likelihood.
- **Rule.** Entry from cash if `mu_2 > 20 bp`, holding if `mu_2 > 0`, exit at
  zero inclusive, read on the position **actually held**;
  `w = g · min(1, 12% / max(σ, 5%))`; a 3-point band, an exit and an entry
  from cash always being sent.
- **One signal, one computation.** `ArimaGarchForecastSignal` carries `mu_2` as
  its value and the variance, the volatility, the source and the diagnostics
  as columns; `read_joint_forecast` raises if the volatility column is
  missing. An ARIMA failure is `INVALID_INPUT` with `failure_stage="ARIMA"`,
  never a missing data point.
- **Controls** (without a catalogue code): D0 without the direction filter, D1
  with an EWMA variance, D2 with a constant mean.
  `scripts/SA12_run_arima_garch_study.py` runs them and assigns a status to
  the hypothesis (`INSUFFICIENT_EVIDENCE`, `NOT_SUPPORTED`, `UNCERTAIN`,
  `SUPPORTED_RETROSPECTIVE`).

`analytics/return_forecast.py` pairs a forecast at origin `t` with the return
from the open of `t+1` to the open of `t+2` and measures the mean (MSE, sign
with its denominators) and the joint loss `log v + e²/v`.

### SA13, neural signatures (`strategies/SA13_signatures_neurons.py`)

`SignaturesNeurons` holds `ETF_WORLD` while an additive model, reading the
log-signature of its last 60 sessions, forecasts a positive simple return from
the open of `t+1` to the open of `t+2`.

- **Path** (`signals/signatures/path.py`). 61 points `(P, U, T)`: cumulative log
  return × 100 on adjusted closes, cumulative notional activity (raw close ×
  raw volume) relative to the median of the previous 60 sessions, session
  time. 120 consecutive sessions required, zero age; a missing volume makes the
  window unusable, an observed zero volume is kept and counted.
- **Log-signature** (`signals/signatures/logsignature.py`). Order 3, `esig`
  with the `roughpy` backend, Hall basis checked key by key (14 coefficients,
  13 after removing the single constant displacement of time). `FeatureSpec`
  names the representation (log-signature, nine classic indicators, raw
  trajectory) and the explanatory processes, concatenated by blocks and
  qualified (`ETF_WORLD:[1,2]`); a missing block makes the whole variant
  unusable.
- **Model** (`ml/signatures/`). A small `tanh` network of 4 units per
  coefficient, centred at zero, summed with a bias (157 parameters): the
  forecast is exactly `reference + Σ contributions`, as a decimal return. A
  control Ridge regression. Inference is written in NumPy (`models.py`); only
  the fitting (`training.py`) imports PyTorch.
- **Monthly re-estimation** (`calibrate_month`). 126 validation origins ending
  on the last session of the previous month, 1,008 training ones before them,
  purged at both boundaries by the label end dates; the features of each
  origin are those built at its own instant; the scaler and the weights see
  only the training set, the validation chooses the epoch. A month without
  enough valid examples has no model and says why.
- **Artifacts** (`artifacts.py`). `SignatureArtifact` is identified by its
  content (weights, scaler, names and order of the features, definition of the
  variant, periods, cutoff, environment); NumPy arrays without pickle and a
  JSON manifest. `SignatureModelSchedule`, immutable, gives each decision the
  model planned for its month and raises `ModelCausalityError` if its cutoff or
  its availability does not precede the decision.
- **Rule.** Entry if the forecast exceeds 20 bp, holding if it is strictly
  positive, exit at zero inclusive, read on the position held;
  `w = g · min(1, 12% / max(σ20, σ60, 5%))`; a 3-point band. The portfolio is
  continuous from one month to the next.
- **Controls** (without a catalogue code): C0 the same models without the
  filter, C1 Ridge, C2 order 2, C3 without volume, C4 classic indicators, C5
  raw trajectory, C6/C7 World + S&P 500 context.
  `scripts/SA13_run_signature_study.py` calibrates, runs, exports the
  contributions and assigns the status.

## 8. Portfolio and execution

Four objects must be told apart:

| Object | What it describes | Produced by |
|---|---|---|
| `TargetAllocation` | what the strategy **asks for** (weights) | `strategy.decide(ctx)` |
| `ConstrainedTarget` (in `PortfolioDecision`) | what the limits **allow** (weights), with each cut named | `PortfolioModel.decide` |
| `Order` / `Fill` / `ExecutionReject` | what is **asked of the market** and what **comes of it** (quantities) | `ExecutionModel.rebalance` |
| `PortfolioState` | what the book **holds** (quantities, average cost, cash) | the fills applied |

- `portfolio/` works in **weights**. `PortfolioModel.decide` refuses an
  inadmissible target: an unknown instrument, a non-tradable one, one in
  another currency or outside the day's universe raises `InadmissibleTarget`.
  There is no silent cut. `PortfolioLimits` then caps each line, then reduces
  the weights proportionally if the gross exposure exceeds its cap. The
  weights removed stay in cash and are not redistributed. These caps apply to
  the target **before costs and rounding**.
- `execution/` goes from weights to **quantities**. Quantities are rounded
  towards zero to the instrument's lot (`rounding`). Sales go before
  purchases, and a purchase the cash does not cover is reduced.
  `ExecutionModel` brings together a `CostModel`, whose commission (with its
  minimum), half-spread and slippage are separate, named terms, a minimum
  order value and a sizing mode (`Sizing`). The equations are in
  [FORMULAS.md](FORMULAS.md).
- An order not executed is a **reject with a reason**. It does not disappear
  silently: it is counted in the report. A target executed once is never
  queued again. If a purchase is rejected, it is up to the next decision to
  ask for it again.

| `ExecutionRejectReason` | Meaning |
|---|---|
| `NON_TRADABLE` | an instrument declared `tradable = false` (last safeguard; `portfolio` refuses it before) |
| `CURRENCY_MISMATCH` | an instrument quoted in another currency than the book (same role) |
| `NO_EXECUTION_PRICE` | no opening price at the execution instant |
| `STALE_EXECUTION_PRICE` | the last opening price dates from an earlier session |
| `NO_DECISION_PRICE` | `Sizing.AT_DECISION` without a close at the decision to set the quantity |
| `BELOW_MINIMUM_TRADE` | an order below the declared minimum value |
| `INSUFFICIENT_CASH` | a purchase reduced or refused for lack of cash, costs included |
| `CASH_SHARE_BUDGET` | a `keep_and_buy` purchase brought back to its share of cash, at the price actually paid |
| `INVALID_QUANTITY` | a held position off the lot grid (a book built outside the engine) |
| `OUTSIDE_TRADING_UNIVERSE` | the purchase of a name that left the universe between the decision and the open; a sale is never refused for this reason |

## 9. Result, analytics and identity of a run

`StrategyResult` keeps everything: `records` (one entry per session),
`orders()`, `fills()`, `rejects()`, `holdings()`, `weights()`, `costs()`,
`equity(book)` and `drawdown(book)`.

- `report()` shows **gross and net side by side**, the costs broken down, the
  turnover, the average cash, the sessions without a price, the purchases cut,
  and the fill assumptions.
- `compare()` sets the run against the runner's declared benchmark, valued
  during the run, over a period with no inner hole. Besides the absolute
  measures, it gives the regression alpha, the beta, the active return, the
  tracking error, the information ratio and the R² (`comparison.relative`).
  `report()` shows them gross and net, and `report(benchmark=...)` produces an
  exploratory report against another reference without touching the one that
  is kept. Formulas and undefined cases: [FORMULAS.md](FORMULAS.md) §4.
- `analytics.uncertainty.paired_block_bootstrap` resamples by blocks the
  **difference** between a strategy and an executable control, under the same
  convention as the report.
- `run_id` hashes the whole configuration: the strategy, the execution, the
  calendar, the universe, the store's fingerprint (`data_state`), that of the
  calendars and instruments, the environment (Python, `uv.lock`, numpy,
  pandas, pyarrow, scipy) and the state of the code (commit, clean tree or
  not). Two runs with the same `run_id` produced the same numbers.

## 10. The `research` layer

The `research/` layer carries the research discipline described in
[research/PROTOCOL.md](../research/PROTOCOL.md):

| Element | Role |
|---|---|
| `research/hypotheses.toml` | the hypotheses of the strategies studied, written **before** their runs (`PREREGISTERED`): what they predict and what would refute them |
| `research/commentary.toml` | the written analysis of each strategy, read by `write_strategy_reports.py` |
| `quant_backtester.research.references` | `BuyAndHold`, `EqualWeightRebalance`, `FixedWeights`: the books a study measures a strategy against |

The register of runs, the paper trading plans, the archive of a run and the
loader of hypotheses were removed on 2026-10-11: no script used them any more.
Each study counts its own trials and prints them.

## 11. Integrity mechanisms, in summary

| Risk | Safeguard |
|---|---|
| Reading the future | reader frozen at an instant, no date argument; a "the future changes nothing" test per layer |
| A window with a hole | `WindowSpec` + `windows.py`, status `NON_CONSECUTIVE_HISTORY` |
| A contested data point | multi-source cross-check, `CONFLICT` served as a hole, committed review |
| A half-written store | transactions with a manifest, shared or exclusive lock |
| A non-reproducible result | `run_id`, `fingerprint`, git state, environment; `uv.lock` committed |
| A strategy that cheats | no import of `data` (test), a context without a reader, a frozen definition |
| A flattering figure | gross and net, executable control, paired bootstrap, register of variants |
| A silent regression | offline tests, warnings = errors, CI on every push, `ruff` + `pyright` |

## 12. Where to add what

| I want… | Where | Note |
|---|---|---|
| a new investment rule | `strategies/` (or a script / notebook with `@strategy`) | see the guide |
| a reusable transformation of a price | `signals/price/`, `signals/risk/`… | frozen dataclass, `compute_window`, tests with a look-ahead guard |
| a new provider | `data/sources/` + a normaliser that ends with `bars_frame` | normalise all of its quirks in the adapter; see [DATA.md](DATA.md) §11 |
| a new instrument | `market_data/metadata/instruments.toml` | `history_basis` and `history_note` mandatory; see [DATA.md](DATA.md) §10 |
| a new universe | `market_data/metadata/universes.toml` | dated members |
| another cost model | `ExecutionModel` / `CostModel` passed to the runner | never in the strategy |
| a new metric | `analytics/` | gross and net, the same convention as the report |

## 13. Scripts and environment

| Script | Role | Network |
|---|---|---|
| `scripts/demo.py` | a first backtest on a synthetic market (`quant_backtester.demo`), reports and figures | no |
| `scripts/update_market_data.py` | download, check and promote (`--archive`, `--coverage`, `--only`, `--rebuild`) | yes, except `--coverage` and `--rebuild` |
| `scripts/accept_revision.py` | prepare the TOML block of a revision to review; modifies no file | no |
| `scripts/generate_calendars.py` | regenerate the calendars from `exchange_calendars` and check them | no |
| `scripts/check_calendar_coverage.py` | fail when fewer than 90 days of calendar remain | no |
| `scripts/run_etf_strategies_comparison.py` | the `SA` rules on the same dates and costs (`--start`, `--end`; `SA11` left out with the note "dependency missing" without the `stats` extra); `quality_details.csv` | no |
| `scripts/SA13_run_signature_study.py` | the `SA13` study: monthly calibrations, controls C0 to C7, contributions, status of the hypothesis, costs ×2 (`OMP_NUM_THREADS=1`, extras `ml stats signatures`) | no |
| `scripts/SA12_run_arima_garch_study.py` | the `SA12` study: controls D0/D1/D2, two-step forecasts, status of the hypothesis, costs ×2 (`OMP_NUM_THREADS=1`) | no |
| `scripts/SA11_run_garch_study.py` | the `SA11` study over the common period: ranking, `SA6`/EWMA controls, QLIKE, bootstrap, costs ×2, histories by strategy | no |
| `scripts/SA16_download_data.py`, `scripts/SA16_run_study.py`, `scripts/SA16_report.py` | the `SA16` study: isolated store `runs/sa16_store` (network), then reproduction of SA15, references, candidates and controls, neighbours and restarts, freeze, figures (`results/SA16/study.md`) | yes for the store, no afterwards |
| `scripts/write_strategy_reports.py` | the `results/` folder: one subfolder per strategy (`analysis.md`, tables, figures) and `summary/` that compares the books, from the exports of a study stored in `runs/`; `--only SA12` writes the folder of a dedicated study, with the ranking of its books and the section the study wrote (`report_extra_<code>.md`) | no |

**API reference.** Every public module, class and function has a numpy
docstring that gives the units, the time zone and the availability instant.
It is read with `pydoc`, with no extra dependency and always up to date with
the code:

```bash
uv run python -m pydoc quant_backtester.backtest.runner   # one module in the terminal
uv run python -m pydoc -b                                  # the whole package in the browser
```

A reference copied by hand, with line numbers, would be wrong from the next
commit on.

A script contains no business computation. It loads the configuration, checks
the preconditions, calls the package and writes to a new folder.

**Environment.** Python 3.12 exactly (`requires-python = ">=3.12,<3.13"`), and
`uv` with `uv.lock` committed. The locks of the store and of the journals use
`fcntl`/`flock`, which offers the shared mode a run needs: **Linux, macOS or
WSL, not native Windows** (decision D11). Importing the store there fails with
a message that says so. `numbers.py` refuses a `bool` where a number is
expected, because in Python `True` is an `int` and would otherwise pass for a
rate or a duration.

**Annualisation.** The reports declare `AnalyticsConfig(sessions_per_year=255,
risk_free_rate=0.02)` for XPAR. `RealizedVolatilitySignal.annualization` has no
default value: it is declared, 252 for XNYS or 255 for XPAR.

The folders of the `data` layer are under `market_data/`: `metadata/` is
committed, `raw/`, `clean/` and `validation/` are not.
