# Developer guide: writing a new strategy

This guide follows one complete example: **hold a fund when its 50-day moving
average is above its 20-day moving average**. The architecture is described
in [ARCHITECTURE.md](ARCHITECTURE.md) and the development rules in
[CLAUDE.md](../CLAUDE.md).

> **Mind the direction of the rule.** The MA50 above the MA20 means that
> recent prices have fallen **below** their slow trend: it is a rule that
> buys the dip. The classic "golden cross" is the reverse, the MA20 above the
> MA50. Both are written with the same code by swapping the parameters, and
> the register counts them as two variants.

## A first run, with no real data

Before downloading anything, a real backtest can be run on an invented market:

```bash
uv run python scripts/demo.py --figures demo_output
```

`quant_backtester.demo` draws two fictitious funds, `FUND_A` and `FUND_B`, from
a fixed seed (the same seed gives the same prices to the bit). It writes them
to a temporary store on a `DEMO` calendar, which copies the Euronext holidays
of 2024-2025, then builds a `StrategyRunner` whose every assumption is
declared: costs, whole lots, EUR 10,000, `FUND_A` as benchmark. The reader, the
engine, the execution and the report are the project's own. Only the prices
are fake. A strategy being written can be tried there, in place of `SA1`
below:

```python
from pathlib import Path

from quant_backtester.demo import demo_runner
from quant_backtester.strategies import WorldMA20Benchmark

runner = demo_runner(Path("demo_store"), seed=20240101)  # a new, empty folder
result = runner.run(
    WorldMA20Benchmark(instrument_id="FUND_A"),  # SA1: the fund above its MA20
    ("FUND_A", "FUND_B"),
    "2025-01-02",
    "2025-12-31",
)
print(result.report().render())
```

2024 serves as the signals' warm-up, and 2025 is the measured period. A figure
obtained on the demo says nothing about a rule. It shows how the engine works,
nothing more.

## 0. Before writing code: the hypothesis

Write the hypothesis in `research/hypotheses.toml` **before the first run**,
and commit it:

```toml
[[hypothesis]]
hypothesis_id = "ma50_over_ma20_world"
status = "PREREGISTERED"
written_on = 2026-09-27
statement = "Holding ETF_WORLD only while its 50-session average is above its 20-session one beats holding it."
universe = "ROTATION_2"
prediction = "Higher net Sharpe than buy and hold of ETF_WORLD, at x1 and x2 costs, for 40/50/60 x 15/20/25."
refutation = "Paired Sharpe interval against the control includes or is below zero, or the edge exists at one parameter point only."
```

A run that is not attached to a hypothesis written in advance tests nothing
(see [research/PROTOCOL.md](../research/PROTOCOL.md)). The 2018-2026 history
of `ROTATION_2` has already been looked at: it is no longer a test sample.

## 1. Separate the signal from the decision

- **Signal**: the reusable transformation, here `MA_a / MA_b − 1`.
- **Decision**: what is done with it, here "invested if > 0, otherwise cash".

First look for an existing signal in `signals/` (see the list in
ARCHITECTURE.md §6). The crossing of two averages exists:
`MovingAverageCrossSignal` in `signals/price/trend.py`. If nothing fits, write
your own following section 2.

Do not use `ctx.market.history(...)` to recompute an average in the strategy.
`ctx.market` is for reading a point value, for instance "is the VIX above
30". A reusable transformation must be a signal: that way it is tested, it has
a fingerprint, and its window contract is checked.

## 2. Writing a signal (anatomy of `MovingAverageCrossSignal`)

```python
@dataclass(frozen=True, slots=True)
class MovingAverageCrossSignal(Signal):
    signal_id: str
    first_sessions: int
    second_sessions: int
    price_basis: PriceBasis
    bar_field: BarField = BarField.CLOSE
    max_age_sessions: int = 1

    def __post_init__(self) -> None:          # refuse an absurd configuration
        ...

    def definition(self) -> Mapping[str, object]:
        return {"type": "MovingAverageCrossSignal", "first_sessions": ..., ...}

    def compute(self, context, instrument_ids) -> SignalResult:
        return self.compute_window(
            context, instrument_ids,
            spec=WindowSpec(max(self.first_sessions, self.second_sessions)),
            bar_field=self.bar_field,
            basis=self.price_basis,
            max_age_sessions=self.max_age_sessions,
            formula=self._ratio_of_averages,
        )

    def _ratio_of_averages(self, window: LoadedWindow) -> float | None:
        first = _average_of_last(window.points, self.first_sessions)
        second = _average_of_last(window.points, self.second_sessions)
        if second <= 0:
            return None                          # -> INVALID_INPUT
        return first / second - 1.0
```

The rules to follow:

- **A frozen dataclass**, and every parameter that changes the number appears
  in `definition()`. An identifier that keeps its name must keep its meaning.
- **`WindowSpec(n)` counts prices**, not returns: 20 returns need 21
  observations. The default mode, `CONSECUTIVE_SESSIONS`, refuses a window with
  a hole. A published series (a rate, a macroeconomic index) needs
  `AVAILABLE_OBSERVATIONS`.
- **Go through `compute_window`.** It handles every status (`NOT_LISTED`,
  `STALE_INPUT`, `INSUFFICIENT_HISTORY`, etc.). The formula decides one thing
  only: return `None` when those particular numbers leave it undefined.
- **Choose the price basis explicitly.** `ADJUSTED` fits here, because a
  dividend that fell within the long window would otherwise push the short MA
  below the long one with no trend at all. `RAW` fits a quoted level.
- No forward fill, no interpolation, no normalisation over the whole sample.
- Export the signal in `signals/__init__.py`.
- **A model estimated within the decision** (`signals/models/garch.py` is the
  example) remains a pure function of its configuration and its window: no
  model kept in the object, no starting point taken from a previous call, no
  file written in `compute()`. An optional dependency is imported at
  computation time, not at the top of the module, so that the catalogue and
  the other strategies import without it; its absence stops the launch
  (`validate()`), it never becomes a status or a fallback. A numerical failure
  on valid data has a **declared** and traced fallback; invalid data have none.

### Testing the signal (`tests/signals/price/test_trend.py`)

The synthetic market of `tests/conftest.py` rises by 1 each session: `ETF_EU`
is worth 100 to 109 over ten sessions of September 2026. Everything can be
checked by hand. The minimum tests:

| Test | Example |
|---|---|
| A value computable by hand | MA2 = 108.5; MA5 = 107 → `108.5/107 − 1` |
| Comparison with a naive loop | each average recomputed in a loop |
| Boundary case | `ETF_LATE` (4 sessions) → `INSUFFICIENT_HISTORY` |
| A hole in the window | contested bar → `NON_CONSECUTIVE_HISTORY` |
| **Look-ahead guard** | adding a price *after* the decision does not change the result (`frame.equals`) |
| Refused configuration | length < 2, equal lengths → `ValueError` |

## 3. Writing the strategy

### The quick form (trial, notebook): `@strategy`

```python
from quant_backtester.signals import MovingAverageCrossSignal, PriceBasis
from quant_backtester.signals.types import SignalStatus
from quant_backtester.strategies import strategy

ma = MovingAverageCrossSignal(
    signal_id="ma50_over_ma20",
    first_sessions=50,
    second_sessions=20,
    price_basis=PriceBasis.ADJUSTED,
)


@strategy(strategy_id="ma_cross_try", signals=[ma], instrument_id="ETF_WORLD")
def ma_cross(ctx):
    if ctx.signal_status("ma50_over_ma20", "ETF_WORLD") is not SignalStatus.OK:
        return ctx.cash()
    if ctx.signal_value("ma50_over_ma20", "ETF_WORLD") <= 0.0:
        return ctx.cash()
    return ctx.weights({"ETF_WORLD": 1.0})
```

Declare as `**parameters` of the decorator every value the function captures
(threshold, instrument): otherwise it does not enter the run's fingerprint.

### The form that is kept: a class

A strategy that is kept is a frozen class. The one in this example is not in
the package: it only serves this guide. The catalogue's strategies are
written this way, `SA3_smooth_moving_average.py` for instance:

```python
@dataclass(frozen=True, slots=True)
class MovingAverageCross(Strategy):
    instrument_id: str
    first_sessions: int = 50
    second_sessions: int = 20
    strategy_id: str = "moving_average_cross"

    def required_signals(self):
        return (self.signal(),)  # MovingAverageCrossSignal, ADJUSTED

    def decide(self, ctx):
        status = ctx.signal_status(self.signal_id, self.instrument_id)
        among = ctx.considering({self.instrument_id: status})
        if status is not SignalStatus.OK:
            return ctx.cash(among=among)
        if ctx.signal_value(self.signal_id, self.instrument_id) <= 0.0:
            return ctx.cash(among=among)
        return ctx.weights({self.instrument_id: 1.0}, among=among)
```

The rules of the decision:

- **An unusable signal is a case to settle explicitly.** `ctx.cash()` leaves
  the market; `ctx.hold_positions()` keeps the positions without sending an
  order. They are two different strategies: write the choice in the
  docstring.
- **Record what the decision read.** `ctx.considering({fund: status})` builds
  the selection to pass as `among`: a valid signal counts one instrument
  considered, whatever the answer; an unusable signal counts none and keeps its
  status. Without this, "the rule said no" and "the rule had nothing to read"
  give the same record.
- **No mutable state.** What depends on the past comes from the context
  (`ctx.portfolio`), never from an attribute or a closure that is incremented.
- **No import of `quant_backtester.data`**, no "today" date, no file read. A
  test fails the build otherwise.
- Weights are fractions of capital in [0, 1], summing to ≤ 1, for tradable
  names of `ctx.universe`. The rest is cash.
- Export the class in `strategies/__init__.py`, and add it to the test "every
  exported strategy is runnable" (`tests/strategies/test_exports.py`).
- **A strategy that receives a catalogue code carries it at the head of its
  files**: its module (`SA11_garch_vol_control.py`), its test file
  (`test_SA11_garch_vol_control.py`, with `test_` staying in front for pytest),
  its study script (`scripts/SA11_run_garch_study.py`, and its test
  `test_SA11_run_garch_study.py`) and the figures that script writes
  (`SA11_equity_common.png`). A module that several strategies share (signals,
  models, rules) keeps a plain name. The strategy modules all sit at the root
  of `strategies/`, with no subfolder. The module's path enters
  `definition()`: renaming a module changes the fingerprint of its strategy.

### Testing the strategy (`tests/strategies/test_<module>.py`)

The helper `decide_with(strategy, context, make_decision, universe)` of
`tests/research/test_references.py` computes the declared signals and then
calls `decide`. Test what the rule **decides**: invested on a rising series
(2 over 5), in cash when the averages are inverted, in cash when history is
missing, the declared signal identifier, a refused configuration. Check too
that the `@strategy` form decides like the class.

## 4. Running a backtest

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path("scripts").resolve()))
from ma_strategy import MovingAverageCross  # the class written above, in your file
from run_etf_strategies_comparison import STORE, UNIVERSE, build_runner

from quant_backtester.backtest.schedule import EverySession

runs = build_runner(STORE)  # the same store, costs, cash and benchmark as the SA rules
result = runs.run(
    MovingAverageCross(instrument_id="ETF_WORLD", first_sessions=50, second_sessions=20),
    UNIVERSE,  # ETF_WORLD and ETF_SP500_PEA
    "2025-01-02",
    "2026-09-17",
    schedule=EverySession(),
)
print(result.run_id)
print(result.report().render())  # gross / net, costs, turnover, average cash, assumptions
print(result.compare().render())  # against ETF_WORLD
print(result.rejects())  # refused orders, with their reason
```

Run it with `uv run python my_trial.py`, with the local store filled
(`scripts/update_market_data.py`).

- **Schedules**: `EverySession()`, `EveryNSessions(n)`, `Weekly()`,
  `Monthly()`.
- **Warm-up**: the data before `start` remain readable by the signals. An MA50
  can therefore be computed from the first measured session if the history
  exists.
- **Costs**: `dataclasses.replace(runs, execution=...)` for another
  `ExecutionModel` (the `SA11` to `SA13` studies run a second time at ×2 costs
  this way).
- **Reading the report**: "sessions with nothing to choose from" counts the
  decisions where no signal was readable. A session spent in cash on a valid
  signal does not appear there, provided the strategy passes `among` as above.

## 5. Judging a variant honestly

1. **Commit** the code before launching a run, and **count every variant
   tried**: the number of trials deflates the Sharpe (`quality_details(...,
   trials=...)`), and a forgotten variant inflates it. There has been no common
   register of runs since 2026-10-11: the study's script keeps that count and
   writes it (`trial_register` in `SA11_run_garch_study.py`).
2. **Compare with an executable control**, for instance
   `BuyAndHold(instruments=("ETF_WORLD",))` under the same costs, over the same
   sessions, with `paired_block_bootstrap(result.equity(), control.equity(),
   statistic=PairedStatistic.SHARPE, block=10, draws=2000, seed=..., level=0.90,
   config=ANALYTICS)`. If the interval contains zero, there is no conclusion.
3. **Think in neighbourhoods**: 40/50/60 × 15/20/25, several start dates, costs
   ×1 and ×2. A result that exists at one point only is noise. Each point is a
   counted trial.
4. **Return a status** that answers the written hypothesis, and nothing broader
   (`research/PROTOCOL.md`, section 6). A rejected variant stays counted.
5. **Keep what you cite**: the study's exports go to `runs/`, and
   `write_strategy_reports.py` draws from them the `results/<CODE>/` folder,
   which is committed.
6. A retained rule is only proven **out of sample**: observed on paper, its
   configuration frozen, and read only after a year of sessions.

## 6. Checklist before committing

```bash
set -o pipefail
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest
```

- [ ] Hypothesis written and committed before the first run.
- [ ] Signal: frozen dataclass, complete `definition()`, correct `WindowSpec`,
      explicit price basis, numpy docstring (units, availability).
- [ ] Signal tests: hand-computed value, boundary case, hole, **look-ahead**,
      refused configuration.
- [ ] Strategy: no import of `data`, no state, the "unusable signal" case
      settled and documented.
- [ ] Strategy tests, and the export test updated.
- [ ] No hidden parameter: everything is a field or a declared parameter.
- [ ] ruff, format, pyright and pytest clean (warnings are errors).
