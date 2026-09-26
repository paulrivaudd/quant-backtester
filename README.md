# quant-backtester

A daily-frequency backtesting framework for systematic strategies, built around
one priority: results you can trust and reproduce.

## Status

The **market data layer is complete and in use**: providers, calendars, a local
Parquet store, validation, multi-source cross-checking, a revision policy and a
point-in-time reader. It ingests six instruments end to end, with dated
universe memberships, and deleting the derived layer and rebuilding it from the
raw archive gives the same files byte for byte.

The **signals layer has its first version**: a window loader that refuses a
window which is not what it claims to be, six signals computed from a fund's
own window — return, momentum, moving-average trend, realised volatility,
current drawdown and mean reversion — two more for published series, a
cross-sectional ranking over any of them, and a universe per signal so a gauge
can reach the same decision as the funds it gates.

**Writing a strategy is the point, and it takes about fifteen lines.** A
strategy declares the signals it needs and answers one question - what to hold,
at an instant it did not choose. What it is handed is a decision context: those
signals, a market façade whose every reading carries its status and its age,
the book as it stands, and the names it is allowed to hold. What it is not
handed is a reader, so there is no expression it can write that reads tomorrow.
A runner takes it from there - any period, warm-up included, with the
configuration recorded beside the numbers - and the result draws itself against
whatever it should be measured against.

**Portfolio, execution and the event loop turn a decision into a book that could
have existed, and keep every step of the way.** What the strategy asked for,
what the portfolio allowed of it, the orders that produced, the fills and the
refusals with their reasons, the positions with what they cost, and how the
book was valued - one immutable record per session, from which every table of
a run is built. The economics are enforced rather than assumed: the trading
universe holds only instruments the registry says can be bought, all quoted in
the book's own currency and checked before the first session; weights are
long-only fractions of one book; a purchase is sized at the price it will be
paid; every order is a whole number of lots rounded down, so a trade is
truncated towards zero and a position ends within a lot of its target; the
sales pay for the purchases; cash cannot go below zero; an order is only ever
filled at an opening price of its own session; and a book asked to keep what it
holds sends no order at all.

**Analytics has its first version**: equity curves, drawdowns, the usual ratios,
the split of what execution took, and the caveats a run has to be read with.
None of it reaches back into the market data — it reads a finished run, and a
figure the run cannot support is reported as nothing rather than invented.

## Design goals

- **No look-ahead bias** — every value is keyed by the time it became available,
  field by field: on a session `t` the open is knowable at the opening auction
  and the close only at the closing one.
- **Look-ahead made unrepresentable** — nothing above the data layer holds a
  reader it can ask about an arbitrary date. What is handed out is a
  `PointInTimeReader` fixed at one instant, whose methods take no `as_of`
  argument at all. A strategy does not even get that: it receives a decision
  context whose every part answers for the same instant, and no attribute of
  it leads back to a reader.
- **Explicit calendars** — real holidays, half days and DST, with a declared
  coverage period and an error outside it rather than an invented session. A
  signal computed after the US close trades at the following European open, and
  that gap is modelled rather than assumed away.
- **Nothing restated is stored** — no `adj_close`. Raw prices plus a corporate
  action table, adjusted at read time with the actions known at the decision
  instant.
- **Reproducible research** — `clean/` is a pure function of the raw archive and
  the committed configuration, and can be deleted and rebuilt identically. A
  provider changing its mind is logged and ignored until someone reviews the
  exact correction in a diff.
- **A window of N sessions really is N sessions** — the reader drops a session
  it cannot serve rather than returning a `NaN`, so twenty observations may span
  twenty-six sessions. A signal declares which of the two it wants, and the
  layer refuses the window rather than computing on the wrong one.
- **Explicit transaction costs** — commission, spread and slippage are named,
  configurable terms; gross and net results reported side by side.
- **A book that could have existed** — an instrument is bought only if the
  registry says it can be bought, in the currency the book is kept in, in the
  units the venue deals in, with money the book holds, and never short. Each of
  those is refused loudly rather than reported as a return: a backtest whose
  orders could not have been placed is not a pessimistic backtest, it is a
  different strategy.
- **Target and actual are two things** — what a strategy asked for, what the
  portfolio allowed, what was filled and what is held are four records, not
  one number overwritten three times. A report that only kept the last would
  describe a strategy that never met a missing price, a lot size or a limit.

## Layout

```
src/quant_backtester/
    data/        providers, Parquet store, trading calendars   (done)
    signals/     information -> forecast scores                (V1 done)
    portfolio/   forecast scores -> target positions           (V1 done)
    execution/   target positions -> fills and costs           (V1 done)
    backtest/    the event loop                                (V1 done)
    analytics/   performance, risk, comparison, plots           (V1 done)
    strategies/  the contract, and strategies written on it     (V1 done)
tests/           mirrors the package layout
market_data/     metadata/ is committed; raw/, clean/ and validation/ are not
```

Dependencies flow one way, left to right; a lower layer never imports a higher one.

```text
MarketDataReader.at(decision) ──┬──> SignalContext ──> SignalEngine ──> SignalSnapshot ──┐
                                │                                                        │
                                └──> StrategyMarketView ──────────────────────────┐      │
                                                                                  ▼      ▼
                                          PortfolioView ──────────────────>  StrategyContext
                                                                                     │
                                                                          Strategy.decide()
                                                                                     │
                                                              TargetAllocation  (what it asked for)
                                                                                     │
                                                    PortfolioModel: admissible? within the limits?
                                                                                     │
                                                              ConstrainedTarget (what it may hold)
                                                                                     │
MarketDataReader.at(execution) ──> opening prices ──>  ExecutionModel: orders, fills, rejects
                                                                                     │
                                                                PortfolioState (what is held)
                                                                                     │
MarketDataReader.at(valuation) ──> closing prices ──>  value_state()  ──>  BacktestRecord
```

A strategy receives that context, never a reader: holding one, it could write
its own `tail(20)` and get twenty observations spanning twenty-six sessions, or
read a price nobody had decided was knowable yet. Every part of the context
answers for the same instant, and the construction refuses a set that does not.

## The data layer

| Module | Role |
|---|---|
| `instruments.py` | the registry: what each series is, when it becomes public, whether it can be bought and in what units |
| `calendars.py` | sessions, real opening and closing instants in UTC |
| `sources/` | one adapter per provider: Yahoo, FRED, ECB, Euronext |
| `normalizer.py` | provider frames to canonical schemas, availability stamped |
| `validator.py` | rules typed by asset class |
| `crosscheck.py` | several sources to one checked series, field by field |
| `revisions.py` | detecting a change is not deciding to apply it |
| `corporate_actions.py` | reviewed corrections to what a provider called an event |
| `bar_corrections.py` | reviewed decisions to drop a bar a provider sent broken |
| `repository.py` | the only module that knows Parquet exists, one change at a time |
| `updater.py` | ingestion, and the replay that proves it reproducible |
| `universes.py` | who was in the universe on the day, not who is in it now |
| `reader.py` | point-in-time reads, vintage by vintage, and nothing else reaches a strategy |

Sources in use: Yahoo Finance (bars and corporate actions), FRED (published
series), ALFRED (the same series as it stood on a declared day), the ECB
reference rates, and the Euronext historical export as a second opinion on
Paris prices.

FRED serves the latest vintage of every observation. For a daily market print
that is an assumption rather than a fact - a correction after release would be
read by decisions taken before it - and for a revised aggregate it is look-ahead
bias outright: US GDP for
the first quarter of 2019 is 21 098.827 to a reader in January 2020 and
21 115.309 to one in June 2021. An instrument served by ALFRED declares the
vintages it wants and how they are read, in committed configuration, so the
same code and the same config fetch the same numbers for ever — and the adapter
refuses to fetch without them.

So every instrument declares, in `instruments.toml`, what its stored history
is: `ARCHIVED_VINTAGES` (each value as it was published - only a vintage
archive), `ASSUMED_UNREVISED` (today's telling, taken as the telling of the
time because values of this kind are not restated) or `RESTATED` (today's
telling of a series known to be revised), with a `history_note` giving the
reason. None is a default, and the loader refuses an instrument that does not
say. US10Y is declared `RESTATED`: H.15 values are occasionally corrected.

There are two honest ways to read such a series, and which one a run used
changes what it saw, so it is declared rather than inferred. `PINNED` reads one
vintage for the whole run: reproducible, and not point-in-time — a decision in
2019 sees numbers restated in 2020, which is fine for a study that says so.
`AS_OF_DECISION` stores the archive, one row per observation *and* vintage, and
each decision is given the latest vintage it could have seen. A revision
published this morning is then invisible to a decision taken last night, and
the same backtest re-run next year still hands the 2020 decision its 2020
number.

A provider occasionally sends a bar that is not a bar: an open above its own
high, a price of zero. The validator refuses the series for it, which is right,
and refusing for ever is not - one impossible row in 2017 kept four years of
good history out of the store. So the decision is committed like the others, in
`bar_corrections.toml`, with the reason on file. A correction **drops** the row
and never repairs it: nothing knows the high the market really made, and a hole
is visible where an invented price is not. Each entry names the defect it was
written for, so the day a provider fixes its own data the ingestion stops
rather than going on dropping a good bar for ever.

One promotion writes the bars, each check source's bars, the verdicts computed
from them, the revision log and the journal of applied fetches. Each write is
atomic on its own, which is not the same thing: a run that died between two of
them left a store whose verdicts described values that were no longer there —
detected by the next update, and repaired by hand. Those writes are now one
transaction, staged under `.pending/` and published together; opening the store
finishes a commit that had been decided and discards a set of files that had
not.

A dated universe is only half of the survivorship problem. The other half is
that nobody can download the prices of a name once the provider stops serving
it — so `--archive` fetches an instrument's whole declared history on purpose,
while it can be, and `--coverage` says which names the store does not hold in
full. A delisted instrument is never fetched past its last session, and never
refetched once its series reaches it: what is in the archive is all there will
ever be.

Membership is dated for the same reason prices are. A universe written as a
list of names is a list of the names that still exist — Yahoo serves nothing
for TWTR, SIVB or CELG — so `market_data/metadata/universes.toml` gives each
member a window, a name that left keeps the date it left on, and the engine
asks what the universe held on the session it is deciding on. A bound left open
in the file is closed with the instrument's own listing dates when it is read:
a fund launched in 2018 is not a member of anything in 2010.

## The signals layer

| Module | Role |
|---|---|
| `types.py` | window modes, price bases, units, and the eight statuses |
| `context.py` | what a signal may read at one instant, and nothing else |
| `windows.py` | a window of N sessions, or the reason it is not one |
| `base.py` | the contract, the result frame and its diagnostics |
| `engine.py` | several signals over one decision |
| `snapshot.py` | what a strategy receives |
| `price/`, `risk/` | the six signals computed from one instrument's own window |
| `level/` | published series: a change in their own units, a z-score |
| `cross_sectional/` | ranking those signals across a universe |
| `engine.py` | and a signal may be asked about a universe of its own |

A published series is not a price, and `level/` is where that is taken
seriously. Nobody holds sessions for a macro release, so its window is counted
in **observations available** rather than in sessions in a row - and the result
carries the dates those observations actually covered, because twenty
observations of a ten-year yield spanned twenty-nine days the last time anyone
asked. Its arithmetic differs too: a yield of 4.20 that becomes 4.45 has moved
twenty-five basis points, not six percent, and a yield that crosses zero makes
the ratio change sign while the move itself is unremarkable. So the change is a
difference in the series' own units, and two such series are compared by
standardising them, never by dividing.

A snapshot is one instant, not one universe. A `SignalRequest` carries the
names a signal is computed for — a list, or a dated universe the engine
resolves for the session being decided, because a basket of gauges changes over
the years like any other — so a rotation between two funds can be gated by
a volatility index or a yield that reaches the same snapshot without ever being
ranked against them — `MomentumVix` is that decision, and it holds the
rotation's choice only while the gauge stays at or below a declared threshold.
What it does when the gauge cannot be read is declared too, because a risk
filter that silently becomes no filter the day its input is late is only ever
noticed afterwards.

A signal never chooses its own instant, never opens a file and never repairs a
window. Every number comes with a status, because "not listed yet", "no history
yet", "a session is missing", "the last value is too old" and "the arithmetic
does not apply" are five different things, and a `NaN` is none of them.

That is also why a ranking excludes an instrument whose own signal is not usable
rather than putting it last: "the worst of the universe" and "we do not know"
must not be the same number, or a strategy selling the bottom of a ranking would
be selling the names whose data is late.

```python
from quant_backtester.signals import (
    MomentumSignal,
    PriceBasis,
    SignalContext,
    SignalEngine,
)

context = SignalContext(market=decision, instruments=..., calendars=...)
snapshot = SignalEngine().compute(
    context,
    [
        MomentumSignal(
            signal_id="momentum_60d",
            lookback_sessions=60,
            price_basis=PriceBasis.ADJUSTED,
        )
    ],
    ["ETF_WORLD", "ETF_SP500_PEA"],
)

snapshot.value("momentum_60d", "ETF_WORLD")  # 0.0259
snapshot.status("momentum_60d", "ETF_WORLD")  # SignalStatus.OK
snapshot.result("momentum_60d").ok()  # the rows a strategy may use
```

## Getting started

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12, on a POSIX system -
Linux, macOS or WSL. The market data store is locked with `flock`, which has
the shared mode a reading run needs and which native Windows does not
provide; importing the store there fails with a message saying so.

```bash
uv sync                          # create the environment from uv.lock
git config core.hooksPath .githooks   # once per clone: the commit-message hook
uv run pytest                    # offline suite
uv run pytest -m network         # the live provider checks, opt in
uv run ruff check . && uv run ruff format --check .
uv run pyright
```

Fetch the committed instruments into the local store, then read it at a decision
instant:

```bash
uv run python scripts/update_market_data.py              # extend every series
uv run python scripts/update_market_data.py --rebuild    # replay raw/ into clean/
uv run python scripts/update_market_data.py --archive --only ETF_WORLD
uv run python scripts/update_market_data.py --coverage   # what the store is missing
```

```python
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from quant_backtester.data.calendars import CalendarRegistry
from quant_backtester.data.instruments import InstrumentRegistry
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.repository import MarketDataRepository
from quant_backtester.data.universes import UniverseRegistry

root = Path("market_data")
instruments = InstrumentRegistry.from_toml(root / "metadata" / "instruments.toml")
calendars = CalendarRegistry.from_directory(root / "metadata" / "calendars")
reader = MarketDataReader(
    repository=MarketDataRepository(root),
    instruments=instruments,
    calendars=calendars,
    reference_calendar_id="XPAR",
)
universes = UniverseRegistry.from_toml(root / "metadata" / "universes.toml", instruments)

# 23:00 in Paris: the US and European closes of the day are knowable.
decision = reader.at(datetime(2026, 9, 17, 23, 0, tzinfo=ZoneInfo("Europe/Paris")))
prices = decision.history("SP500")  # nothing after the decision instant
state = decision.values(["SP500", "VIX"])  # value, age in sessions, and why
```

## A run, end to end

The engine below is the primitive, and the sections after this one show the
façade that a user actually writes against. It is here because everything the
façade does is *this*, with the configuration filled in once:

```python
from quant_backtester.analytics import AnalyticsConfig, PerformanceReport
from quant_backtester.provenance import git_source_state

engine = BacktestEngine(
    reader=reader,
    calendars=calendars,
    strategy=MomentumRotation(lookback_sessions=60, top_n=1),  # declares its own signals
    universe=universes.get("ROTATION_2"),  # two PEA funds, dated memberships
    config=BacktestConfig(
        start=date(2025, 1, 2),
        end=date(2026, 9, 17),
        initial_cash=100_000.0,
        base_currency="EUR",
        reference_calendar="XPAR",
        schedule=EverySession(),
        timetable=BacktestTimetable(),  # fill at 09:01, value and decide at 23:00, Paris
    ),
    execution=ExecutionModel(
        costs=CostModel(
            commission_rate=0.0005,
            minimum_commission=1.0,
            half_spread_rate=0.0002,
            slippage_rate=0.0001,
        ),
        minimum_trade_value=500.0,
    ),
    portfolio=PortfolioModel(PortfolioLimits(max_weight_per_instrument=1.0, max_gross=1.0)),
    source=git_source_state(Path(".")),  # the commit, and whether the tree was clean
)
result = engine.run()
report = PerformanceReport.of(result, AnalyticsConfig(sessions_per_year=255, risk_free_rate=0.02))
print(report.render())
```

```text
437 sessions, 1.71 years, 255 sessions/year, risk-free 2.00%

                               gross         net
total return                  19.31%      16.19%
annualised return             10.90%       9.20%
annualised volatility         14.32%      14.39%
max drawdown                 -21.60%     -21.65%
sharpe ratio                    0.65        0.54

costs                       3,119.40
  commission                1,949.63
  spread                      779.85
  slippage                    389.92
  drag on the return           3.12%
  share of gross              16.16%
  rebalancings                    20
  per rebalancing             155.97
  turnover                    37.84x
  turnover a year             22.18x

by instrument                    net       gross        cost    held
  ETF_SP500_PEA            15,742.11   17,260.63    1,518.52     165
  ETF_WORLD                   446.51    2,047.40    1,600.88     210

sessions valued on an older price              1
sessions without an execution price            2
purchases cut for want of cash                11
sessions with nothing to choose from          61
sessions missing a line of the target          0
average cash                              14.27%
largest weight held                      100.00%
orders, fills, rejects                37, 37, 13
  INSUFFICIENT_CASH                           11
  NO_EXECUTION_PRICE                           2

assumptions
  fills: OPEN_AUCTION_NOTIONAL - sized and filled at the next opening price
  gross: the same fills with no cost taken out - not a separate cost-free run
  cash: earns nothing; the risk-free rate is used by the Sharpe ratio only
  limits: cap target weights, before costs
  a decision lives: one execution; a refused order is not retried
  history read: ASSUMED_UNREVISED ETF_SP500_PEA, ETF_WORLD
```

Three points of return went to execution — **a sixth of everything the idea
earned** — and a Sharpe ratio of 0.65 that an investor would have experienced
as 0.54. Twenty switches in twenty-one months is not a hyperactive strategy,
and it still costs that much: the kind of fact a backtest without a cost model
cannot show, which is why this one refuses to report a return without one.

The instrument block is the one that should worry its author. The world ETF
was held for 210 of the 375 invested sessions and returned 447 euros of the
16,189: it paid 1,601 in costs to earn 2,047 gross. Practically the whole
result is the other leg. A rotation between two funds whose gain comes from one
of them is not a rotation that works - it is a strategy that was right once,
and the total return alone cannot tell the difference. The decomposition is
exact: every instrument's share is computed from the quantities, the fills and
the closes the run itself recorded, and what it fails to explain is reported
rather than absorbed.

The last block is not decoration. Sixty-one sessions had nothing to choose
from, and they are one story: on 24 October 2025 the two providers disagreed
on the world ETF's bar, so the reader serves that session as a hole rather than
as a price. A sixty-session momentum needs sixty sessions in a row, and it took
sixty-one for the hole to leave the window - during which the ranking had one
instrument where it needs two, the strategy had nothing to choose from, and the
book stood in cash: that is most of the fourteen percent of average cash. The
same session is the one valued on an older price and one of the two on which
an order met no opening price of its own. Eleven purchases were cut, because a
switch pays the sale's costs out of its proceeds and the commission on top of
the purchase, and execution lends nothing: each cut is a reject on the record,
with the units it cost.

These figures are the same, to the cent, as before the execution layer was
rebuilt around the specification: a purchase is now sized at the price it will
be paid rather than at the open, and in whole shares both routes land on the
same quantity once the cash has had its say. What changed is what the record
can say about it - the spread and the slippage apart, every refusal with its
reason, the orders against the fills.

Those lines are the caveats the figures above have to be read with. A single
contested bar cost this strategy a quarter of its year, and a report that left
that out would be describing a strategy nobody ran.

Inside a session the order is fixed, and it is what stops a strategy buying at
the close it just read. The three instants are declared in the run's
`BacktestTimetable` and recorded with it:

```text
09:01 on session s   execution   the target decided on s-1 is filled at s's open
23:00 on session s   valuation   the book is marked at s's closes
23:00 on session s   decision    the signals run, and the target for s+1 is decided
```

An order is filled at an opening price **of its own session** or not at all. A
Friday decision is filled on Monday, one taken before Easter on the Tuesday
after it, and an execution time set before the auction finds only yesterday's
open - which the reader rightly calls the latest there is, and which is still
not a price anyone could trade at that morning. Valuation may estimate - a
close that did not print is marked at the last price known, and named -
execution never does.

## What a run records

One immutable `BacktestRecord` per session, and every table is a view of those:

| Asked of a result | What it holds |
|---|---|
| `result.records` | the records themselves, the source of truth - `records()` on what a runner hands back |
| `result.frame()` | one row per session: the three instants, net and gross, target and actual invested, costs term by term |
| `result.fills()` | every trade: market price, fill price, commission, spread, slippage |
| `result.orders()` | every order the targets called for, with `FILLED`, `PARTIALLY_FILLED` or `REJECTED` |
| `result.rejects()` | every refusal with its reason: no price, a stale one, below the minimum trade, not enough cash, left the universe |
| `result.holdings()` | the quantity of every instrument and the cash, after each session |
| `result.weights()`, `result.target_weights()` | what the book actually was, against what it was traded towards |
| `result.costs()`, `result.equity()` | the bill per session, and the two books |

A decision is kept whole: what the strategy returned - with how many
instruments it chose among and why the others were not eligible - and what
the portfolio allowed of it. A limit that cut a weight says which limit it was;
an instrument the book may not hold at all is not cut to nothing, it stops the
run. Positions carry the average price actually paid for them, costs included,
which is what a stop or a take-profit is measured against.

The run also records what it was made with - period, universe, calendar,
schedule, timetable, limits, cost and execution models, the lot size of every
instrument it could hold, the strategy's definition and fingerprint - and the
state of the code: the commit and whether the tree had uncommitted changes, as
`git_source_state` found them when the script that ran it asked. The library
never shells out to git on its own.

What this version does not model is refused rather than approximated. A split
or a dividend on a position the book holds stops the run: the funds traded here
accumulate and have not split, and a position halving overnight, or a dividend
that never reached the cash, would be worse than a run that says it cannot
continue. Execution is the next open and nothing else; the book is long-only
and kept in one currency.

## Writing a strategy

A strategy is a name, the signals it needs, and one decision:

```python
from quant_backtester.strategies import Strategy


class MomentumVix(Strategy):
    strategy_id = "momentum_vix"

    def required_signals(self):
        momentum = MomentumSignal(
            signal_id="mom60", lookback_sessions=60, price_basis=PriceBasis.ADJUSTED
        )
        return (
            momentum,
            CrossSectionalRank(signal_id="rank", source=momentum),
            SignalRequest(LevelZScoreSignal(signal_id="vix_z", window_observations=60), ("VIX",)),
        )

    def decide(self, ctx):
        gauge = ctx.signal_value_or_none("vix_z", "VIX")
        if gauge is None or gauge > 1.5:
            return ctx.cash()
        return ctx.equal_weight(ctx.top("rank", 2))
```

Nothing in it knows that Parquet, Yahoo, corporate actions, trading calendars
or fill prices exist. `ctx` is the decision instant, and everything in it
answers for that instant:

| What it holds | For |
|---|---|
| `ctx.signals` | the snapshot, read through `signal_value`, `signal_status`, `top`, `bottom`, `where` |
| `ctx.market` | the latest value of any series, and windows of it |
| `ctx.portfolio` | the book as it stands: cash, positions, weights |
| `ctx.universe` | the names this session's universe allows |

and the decision is expressed through `ctx.weights`, `ctx.equal_weight`,
`ctx.cash` and `ctx.hold_positions`, which refuse a book nobody could hold: a
negative weight, a sum above one, a name outside the universe, an instrument
the registry declares untradable.

`ctx.market` exists so that a rule like *stand aside above thirty* does not
need a new signal class. It costs nothing in safety, because staleness is never
hidden:

```python
vix = ctx.market.value("VIX")
if not vix.usable(max_age_sessions=1):
    return ctx.hold_positions()
if vix.value > 30:
    return ctx.cash()
```

A reading carries its status, the day it describes and its age in sessions, and
`require()` refuses to hand back a number that is too old rather than returning
a stale one. A window goes through the loader every signal uses, so twenty
observations spanning twenty-six sessions are refused here exactly as they are
there. The rule of thumb: a *decision* belongs in a strategy, and a
*transformation* worth reusing belongs in a signal.

`hold_positions()` is there for the day a signal cannot be computed. Standing
aside and not trading on bad data are both defensible, they are different
strategies, and a framework offering only `cash()` would quietly make every
strategy choose the first. It keeps the positions and sends no order - which is
not the same as asking for the weights the book has: those are the weights of
the close, two funds drift apart overnight, and a target restated in weights
trades that drift every morning. An earlier version did exactly that, and only
the minimum trade value kept it still: without one, buy and hold on both funds
traded 106 times over this README's period instead of once. A risk limit the
kept book breaches still trades it down to the limit.

It is also what makes a baseline honest. `BuyAndHold` buys its basket, completes
it with the cash left if a name could not be bought the first time
(`ctx.keep_and_buy`: the names held are kept, never traded back to equal
weights), and keeps its positions afterwards; `EqualWeightRebalance` restates
the same target at every decision. Over this README's period they are two
different strategies — one session of trading against four (two fills against
seven), 80 euros of costs against 86,
no refused order against 375, most of them rebalancings too small to send — and
calling the second one "buy and hold", as an earlier version of this project
did, hides the very thing the comparison exists to measure.

## Running one

```python
runner = StrategyRunner(
    reader=reader,
    calendars=calendars,
    reference_calendar_id="XPAR",
    base_currency="EUR",
    analytics=AnalyticsConfig(sessions_per_year=255, risk_free_rate=0.02),
    execution=ExecutionModel(costs=CostModel(commission_rate=0.0005, minimum_commission=1.0)),
    universes=universes,
    initial_cash=100_000.0,
    source=git_source_state(Path(".")),
    benchmark="ETF_WORLD",
)

result = runner.run(
    MomentumRotation(lookback_sessions=60, top_n=1),
    universe="ROTATION_2",
    start="2025-01-02",
    end="2026-09-17",
)

result.report().render()
result.plot()  # against the declared benchmark
result.compare().render()
result.fills(), result.holdings(), result.rejects()
```

The cost model is required: a runner that defaulted to free trading would
report returns no account could have had, from a line nobody wrote.

Every strategy the package exports is runnable as it stands: it declares the
signals it reads, so those four arguments are the whole of what a user writes.
A rule needing its signals wired in from outside would look identical in an
import list and fail at the first decision, so there is no such thing.

`start` is where the *performance* starts, not where the data does: a
sixty-session momentum run from January reads the previous October, because the
reader has always been allowed to look back and never forward. A bound that is
not a session moves inwards to one that is. And the result carries what the
numbers depend on — period, universe, calendar, rebalancing schedule, starting
cash, limits, costs, fill model and timetable, annualisation convention — beside
the strategy's own definition and fingerprint, because a Sharpe ratio without
them is not a result. All of it frozen: a record of an experiment that can be
edited afterwards is a record of nothing.

The data is part of it too. A run holds the store for reading from its first
session to its last - an ingestion started meanwhile is refused, not
interleaved - and records the SHA-256 of every file under `clean/` and
`metadata/`. The declared benchmark is valued inside that hold and kept; any
other benchmark asked for later is valued only if the store still has the same
digest, and `StoreChanged` is raised otherwise, since a revised close would
otherwise move the conclusion of a finished run. `run_id` hashes the whole
record - the calendars and instruments the run was handed, and its
environment: Python, the digest of `uv.lock` and the versions of the numerical
libraries: the same question asked of other data, or in another environment,
is another run.

A fingerprint hashes a *configuration*, never the source that read it, so two
runs of an edited `decide` share one. What tells them apart is the state of the
code - the commit, and whether the tree had changes nobody committed - given
to the runner and recorded as given, `UNRECORDED` when nobody said. Scripts get
it from `git_source_state`; the library never guesses it. Nor does a
fingerprint see what a function closes over: the engine checks that the
declared definition did not change during a run, and a counter kept in a
closure changes the decisions without changing it. Build a fresh strategy per
run.

The rebalancing calendar is declared per run rather than inside the strategy,
so one rule can be tested at several frequencies without being written twice:

```python
runner.run(strategy, "ROTATION_2", "2025-01-02", "2026-09-17", schedule=Monthly())
```

On a session the schedule does not decide on, the strategy is not called, no
order is sent, and the record carries the target still standing with
`decided = False` beside it.

Measured against simply holding the world ETF, the rotation of this README is
behind:

```text
437 sessions, strategy against ETF_WORLD

                            strategy     ETF_WORLD
total return                  16.19%        20.19%
annualised return              9.20%        11.39%
annualised volatility         14.39%        14.69%
max drawdown                 -21.65%       -21.66%
sharpe ratio                    0.54          0.67
excess return                 -4.01%

ETF_WORLD is a yardstick, not an alternative that was traded: one share
held from the first close, with no cost, no lot and no cash left over. The
strategy starts in cash and trades at the next open on its own schedule.
```

Four points of it are the single contested bar of 24 October 2025: the strategy
held nothing for the sixty-one sessions its sixty-session window needed to
clear the hole, and the benchmark kept moving. A picture makes that plateau
obvious where a table does not, which is what `result.plot()` is for — it
returns a figure and never calls `show`, so a notebook displays it, a script
saves it and a test inspects it.

Against the index the strategy trails by four points, and against the fund it
could actually have bought instead - the world fund bought once, under the same
costs, lots and cash - the question is whether that gap means anything. The
readme suite answers with a paired block bootstrap of the two books, the same
blocks of ten sessions drawn for both, 2 000 draws, seed 20260926:

```text
== reference_rotation against the executable control, control_world
difference      estimate       low      high   level
mean_return       -0.023    -0.063     0.017     90%
sharpe            -0.142    -0.445     0.151     90%
```

Both intervals hold zero. Over 437 sessions the rotation is neither better
nor worse than keeping the world fund, and no figure of this README says
otherwise - which is what `research/PROTOCOL.md` is for.

Nor does the gap depend much on how the orders are simulated.
`scripts/sensitivity.py` runs both books with quantities fixed at the
decision's close instead of the opening auction's notional, and at twice the
declared costs:

```text
scenario              book                      net  sharpe     costs  rejects
notional, costs x1    reference_rotation     16.19%    0.54     3,119       13
notional, costs x1    control_world          20.71%    0.69        80        0
notional, costs x2    reference_rotation     12.84%    0.43     6,146       15
notional, costs x2    control_world          20.63%    0.69       160        0
overnight, costs x1   reference_rotation     16.10%    0.54     3,118       64
overnight, costs x1   control_world          20.59%    0.69        79        0
overnight, costs x2   reference_rotation     12.76%    0.42     6,139       38
overnight, costs x2   control_world          20.51%    0.69       159        0
```

Fixing the quantities overnight costs the rotation a tenth of a point and
turns more purchases into cuts - an open above the close leaves an order
bigger than the cash. The costs are what it is sensitive to: twice them take
three and a half points from the rotation and nothing from the fund it is
measured against.

The benchmark is read at the run's own decision instants, so adding data after
the last session changes none of its figures; a session its venue did not hold
is marked at the last close that existed and named; and one quoted in another
currency is refused rather than drawn, because without an FX conversion the
difference between the two curves is an exchange rate.

## Four baselines, several periods

`scripts/run_baselines.py` runs the four reference strategies over the whole
history both funds share and over three regimes inside it, with the costs of
this README - five basis points of commission with a one-euro floor, two of
half spread, one of slippage, no order under five hundred euros - and 100,000
euros each time. Every line is a `StrategyResult` carrying its configuration,
its fingerprint and the state of the code, followed by its refused orders by
reason; `--suite all` takes a little over two minutes. `--suite readme` prints
every other figure of this README, and `--records DIR` writes each run's
sessions, orders, fills, rejects and holdings so that two versions of the code
can be compared run for run.

```text
strategy            period                         net    gross   a year  sharpe   max dd     costs  rebal.  fills  rejects  est.  vs world
buy_and_hold        2018-07-16 2026-09-17      164.10%  164.18%   12.62%    0.71  -33.59%        80       1      1        0     1     0.44%
equal_weight        2018-07-16 2026-09-17      182.29%  182.42%   13.54%    0.74  -33.57%       127      23     40      106     1    18.63%
                    rejects: BELOW_MINIMUM_TRADE 92, INSUFFICIENT_CASH 14
momentum_rotation   2018-07-16 2026-09-17      160.40%  183.22%   12.42%    0.68  -33.62%    22,824      86    169       65     1    -3.26%
                    rejects: INSUFFICIENT_CASH 63, NO_EXECUTION_PRICE 2
momentum_vix        2018-07-16 2026-09-17      124.37%  161.29%   10.39%    0.66  -23.11%    36,920     214    289      108     1   -39.29%
                    rejects: INSUFFICIENT_CASH 106, NO_EXECUTION_PRICE 2

buy_and_hold        2019-01-02 2021-12-31       82.30%   82.38%   22.20%    1.08  -33.61%        80       1      1        0     0     1.37%
equal_weight        2019-01-02 2021-12-31       77.41%   77.50%   21.09%    1.02  -33.56%        90       6     10       45     0    -3.51%
                    rejects: BELOW_MINIMUM_TRADE 41, INSUFFICIENT_CASH 4
momentum_rotation   2019-01-02 2021-12-31       92.21%   97.34%   24.38%    1.14  -33.62%     5,130      24     47       17     0    11.29%
                    rejects: INSUFFICIENT_CASH 17
momentum_vix        2019-01-02 2021-12-31       78.91%   88.94%   21.44%    1.26  -12.21%    10,025      69     91       39     0    -2.01%
                    rejects: INSUFFICIENT_CASH 39

buy_and_hold        2022-01-03 2023-12-29        2.13%    2.21%    1.07%    0.01  -16.99%        80       1      1        0     0    -0.82%
equal_weight        2022-01-03 2023-12-29        9.34%    9.42%    4.60%    0.24  -15.54%        83       4      5       30     0     6.39%
                    rejects: BELOW_MINIMUM_TRADE 28, INSUFFICIENT_CASH 2
momentum_rotation   2022-01-03 2023-12-29       -1.05%    2.61%   -0.53%   -0.08  -18.75%     3,662      26     51       18     0    -4.00%
                    rejects: INSUFFICIENT_CASH 18
momentum_vix        2022-01-03 2023-12-29       -8.83%   -3.23%   -4.55%   -0.39  -23.31%     5,605      63     83       30     0   -11.78%
                    rejects: INSUFFICIENT_CASH 30

buy_and_hold        2024-01-02 2026-09-17       53.43%   53.51%   17.13%    1.09  -21.61%        80       1      1        0     1    -0.19%
equal_weight        2024-01-02 2026-09-17       49.50%   49.59%   16.01%    0.99  -22.46%        90       6     11       25     1    -4.13%
                    rejects: BELOW_MINIMUM_TRADE 22, INSUFFICIENT_CASH 3
momentum_rotation   2024-01-02 2026-09-17       47.99%   54.51%   15.58%    0.98  -21.62%     6,522      35     67       23     1    -5.63%
                    rejects: INSUFFICIENT_CASH 21, NO_EXECUTION_PRICE 2
momentum_vix        2024-01-02 2026-09-17       37.65%   47.78%   12.53%    0.96  -13.47%    10,124      76    107       34     1   -15.97%
                    rejects: INSUFFICIENT_CASH 32, NO_EXECUTION_PRICE 2
```

Over eight years the simplest things win. Half and half, rebalanced monthly,
beats everything; the rotation earns, gross, what the equal weight keeps net,
and hands twenty-three points of it to 86 sessions of switching. The VIX gate does what it
says - its worst fall is a third smaller over the whole history, and its
Sharpe ratio is the best of 2019-2021 - and pays for it twice: 214 sessions of trading, and
the rebounds it sits out. In 2022-2023 both rotations lose money net, the gated
one even before costs. None of this is a verdict on momentum: two funds are
the thinnest universe a ranking can have, and over these years the S&P 500
fund simply outran the world one. It is what the chain was built to be able to
say.

The refused orders say what each strategy runs into: the equal weight's are
mostly rebalancings too small to send, the rotations' are purchases cut to the
cash a switch leaves once the sale has paid its costs, and buy and hold has
none at all - it keeps its positions and sends nothing. `est.` counts the
sessions a position was valued on an older close: the contested bar of
24 October 2025.

## Research: what is left to test, and how

Every session of 2018 to 2026 on `ROTATION_2` has been looked at, and those
results shaped choices, so none of that history is out of sample any more. The
test left is the future. [`research/PROTOCOL.md`](research/PROTOCOL.md) writes
the rules down before any experiment they govern:

- two paper plans, committed before their start on 2026-10-01 and fixed by the
  strategy's fingerprint - the reference rotation, and buy and hold of the
  world fund as its control. `scripts/paper_trade.py` runs them forward and
  appends each new session to a log that is never rewritten; a changed rule, or
  a logged session that comes out differently, stops it;
- every research backtest appended to `research/registry.jsonl`, rejected ones
  included and only from committed code, so a result is always read with the
  number of variants it took (`run_baselines.py --register` registers the
  suites' runs);
- neighbourhoods rather than points, rolling start dates, twice the costs, and
  an executable baseline over the same sessions before any variant is kept.

## What a strategy may not do

Both names of `ROTATION_2` are funds a PEA can hold, in euros, on Euronext
Paris. The S&P 500 index itself is in the registry and is declared
`tradable = false`: a signal may read it, `ctx.market` may read it, and
`ctx.weights({"SP500": 1.0})` is refused — as is a run that puts it in a
trading universe at all. An earlier version of this README rotated into the
index, and its orders were simply never sent: 216 sessions of a 437-session
run, reported as a strategy.

A name whose signal is not usable is never held, and the allocation says which
of the reasons it was. A rotation meant to hold two names that can only find
one holds it at half the capital rather than doubling a bet because a provider
was late.

An allocation is also a thing a portfolio could hold, checked where it is
built: a weight is a finite fraction between zero and one, the selection and
the weights describe the same book, and the count of instruments considered
cannot be below the number chosen. A forecast model produces negative scores
for half a universe by construction, and the keystroke that turns one into a
weight is a short position nobody financed — so the refusal is at the boundary
rather than in a comment.

Four tests stand behind those sentences rather than the prose: a strategy that
imports the data layer or a network library fails the build, the context hands
back no reader, a decision taken on a store that knows what happens tomorrow is
identical to one taken without it, and every part of a context must answer for
the same instant or it cannot be built.

Other scripts: `run_baselines.py` runs the named experiments every figure of
this README comes from (`--suite readme`, `--suite baselines`, `--records` to
keep every run's sessions, orders and fills), `generate_calendars.py` rewrites
the committed calendars from
`exchange_calendars`, `check_calendar_coverage.py` says when they need
extending, and `accept_revision.py` builds the entry that approves one detected
correction.

Development rules live in [CLAUDE.md](CLAUDE.md).
