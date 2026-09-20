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

**Portfolio, execution and the event loop run a strategy end to end**, with
costs charged against it and the economics of the book enforced rather than
assumed: the trading universe holds only instruments the registry says can be
bought, all quoted in the book's own currency, weights are long-only fractions
of capital, orders are placed in whole shares where the venue deals in them,
and nothing is ever bought with cash the book does not hold. Two strategies sit
on top — hold the best-ranked instruments of a universe, and the same gated by
a gauge that is never traded — and they are there to prove a boundary as much
as to make money: they import nothing from the data layer, and take a
`SignalSnapshot` as their only argument.

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
  `PointInTimeReader` fixed at one decision instant, whose methods take no
  `as_of` argument at all. A strategy does not even get that: it receives a
  `SignalSnapshot`, so it cannot write its own window either.
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

## Layout

```
src/quant_backtester/
    data/        providers, Parquet store, trading calendars   (done)
    signals/     information -> forecast scores                (V1 done)
    portfolio/   forecast scores -> target positions           (V1 done)
    execution/   target positions -> fills and costs           (V1 done)
    backtest/    the event loop                                (V1 done)
    analytics/   performance and risk                          (V1 done)
    strategies/  concrete strategies                           (two)
tests/           mirrors the package layout
market_data/     metadata/ is committed; raw/, clean/ and validation/ are not
```

Dependencies flow one way, left to right; a lower layer never imports a higher one.

```text
MarketDataReader.at(decision)  ->  SignalContext  ->  SignalEngine
                                                           |
                                                     SignalSnapshot
                                                           |
                                                       Strategy
MarketDataReader.at(execution) ->  Execution
```

A strategy receives the snapshot, never a reader: holding one, it could write
its own `tail(20)` and get twenty observations spanning twenty-six sessions.

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
| `reader.py` | point-in-time reads, and nothing else reaches a strategy |

Sources in use: Yahoo Finance (bars and corporate actions), FRED (published
series), ALFRED (the same series as it stood on a declared day), the ECB
reference rates, and the Euronext historical export as a second opinion on
Paris prices.

FRED serves the latest vintage of every observation, which is harmless for a
daily market rate and is look-ahead bias for a revised aggregate: US GDP for
the first quarter of 2019 is 21 098.827 to a reader in January 2020 and
21 115.309 to one in June 2021. An instrument served by ALFRED declares the
`vintage_date` it is pinned to, in committed configuration, so the same code
and the same config fetch the same numbers for ever — and the adapter refuses
to fetch without one.

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
ranked against them — `RiskGatedRotation` is that decision, and it holds the
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
            price_basis=PriceBasis.TOTAL_RETURN,
        )
    ],
    ["ETF_WORLD", "ETF_SP500_PEA"],
)

snapshot.value("momentum_60d", "ETF_WORLD")  # 0.0259
snapshot.status("momentum_60d", "ETF_WORLD")  # SignalStatus.OK
snapshot.result("momentum_60d").ok()  # the rows a strategy may use
```

## Getting started

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12.

```bash
uv sync                          # create the environment from uv.lock
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

```python
from quant_backtester.analytics import AnalyticsConfig, PerformanceReport

engine = BacktestEngine(
    reader=reader,
    calendars=calendars,
    reference_calendar_id="XPAR",
    signals=[momentum, CrossSectionalRank(signal_id="momentum_60d_rank", source=momentum)],
    strategy=TopRankRotation(signal_id="momentum_60d_rank", top_n=1),
    universe=universes.get("ROTATION_2"),  # two PEA funds, dated memberships
    initial_cash=100_000.0,
    base_currency="EUR",
    limits=PositionLimits(max_weight=1.0, max_gross=1.0),
    execution=ExecutionModel(
        costs=CostModel(
            commission_rate=0.0005, minimum_commission=1.0, half_spread=0.0002, slippage_rate=0.0001
        ),
        minimum_trade_value=500.0,
    ),
    timetable=Timetable(),  # decide at 23:00 Paris, fill at 09:01 the next session
)
result = engine.run(date(2025, 1, 2), date(2026, 9, 17))
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
  spread and slippage       1,169.77
  drag on the return           3.12%
  share of gross              16.16%
  rebalancings                    20
  per rebalancing             155.97
  turnover                    37.84x
  turnover a year             22.18x

by instrument                    net       gross        cost    held
  ETF_SP500_PEA            15,742.11   17,260.63    1,518.52     165
  ETF_WORLD                   446.51    2,047.40    1,600.88     210

sessions valued on an older close            1
sessions an order could not be sent on       2
sessions with nothing to choose from        61
sessions a purchase was cut down on         11
sessions ending on borrowed cash             0
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
instrument where it needs two, held what it already held, and traded nothing.
That same session is the one valued on an older close and one of the two the
order could not be sent on. Eleven purchases were cut down, because a target of
the whole book costs slightly more than the book is worth and execution is not
allowed to borrow the difference; the last line reads zero, and it is a guard
rather than a statistic.

Those lines are the caveats the figures above have to be read with. A single
contested bar cost this strategy a quarter of its year, and a report that left
that out would be describing a strategy nobody ran.

Inside a session the order is fixed, and it is what stops a strategy buying at
the close it just read:

```text
open of session s     the target decided on s-1 is filled here
close of session s    the portfolio is valued
after that close      the signals run, and s+1's target is decided
```

## A decision, end to end

```python
momentum = MomentumSignal(
    signal_id="momentum_60d",
    lookback_sessions=60,
    skip_recent_sessions=0,
    price_basis=PriceBasis.TOTAL_RETURN,
)
snapshot = SignalEngine().compute(
    context,
    [momentum, CrossSectionalRank(signal_id="momentum_60d_rank", source=momentum)],
    ["ETF_WORLD", "ETF_SP500_PEA"],
)

TopRankRotation(signal_id="momentum_60d_rank", top_n=1).decide(snapshot)
# selected ('ETF_SP500_PEA',)  weights {'ETF_SP500_PEA': 1.0}
# invested 100%  considered 2
```

Both names of that universe are funds a PEA can hold, in euros, on Euronext
Paris. The S&P 500 index itself is in the registry and is declared
`tradable = false`: a signal may read it, and a run that put it in a trading
universe is stopped on the session it would have been chosen on. The earlier
version of this example rotated into the index, and its orders were simply
never sent — 216 sessions of a 437-session run, reported as a strategy.

`decide` takes the snapshot and nothing else. A strategy holding a reader could
write its own `tail(20)`; a strategy holding a repository could read a price
nobody had decided was knowable yet. It holds neither, and a test reads the
source of `strategies/` to check that no import of the data layer has appeared.

A name whose signal is not usable is never held, and the allocation says which
of the reasons it was. A rotation meant to hold two names that can only find one
holds it at half the capital rather than doubling a bet because a provider was
late.

An allocation is also a thing a portfolio could hold, checked where it is
built: a weight is a finite fraction between zero and one, the selection and
the weights describe the same book, and the count of instruments considered
cannot be below the number chosen. A forecast model produces negative scores
for half a universe by construction, and the keystroke that turns one into a
weight is a short position nobody financed — so the refusal is at the boundary
rather than in a comment.

Other scripts: `generate_calendars.py` rewrites the committed calendars from
`exchange_calendars`, `check_calendar_coverage.py` says when they need
extending, and `accept_revision.py` builds the entry that approves one detected
correction.

Development rules live in [CLAUDE.md](CLAUDE.md).
