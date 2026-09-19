# quant-backtester

A daily-frequency backtesting framework for systematic strategies, built around
one priority: results you can trust and reproduce.

## Status

The **market data layer is complete and in use**: providers, calendars, a local
Parquet store, validation, multi-source cross-checking, a revision policy and a
point-in-time reader. It ingests five instruments end to end, and deleting the
derived layer and rebuilding it from the raw archive gives the same files byte
for byte.

The **signals layer has its first version**: a window loader that refuses a
window which is not what it claims to be, six signals built on it — return,
momentum, moving-average trend, realised volatility, current drawdown and mean
reversion — and a cross-sectional ranking over any of them.

Portfolio construction, execution, the event loop and analytics are not written
yet. Those packages exist with their contracts stated and nothing else.

## Design goals

- **No look-ahead bias** — every value is keyed by the time it became available,
  field by field: on a session `t` the open is knowable at the opening auction
  and the close only at the closing one.
- **Look-ahead made unrepresentable** — a strategy never holds a reader it can
  ask about an arbitrary date. It receives a `PointInTimeReader` fixed at one
  decision instant, whose methods take no `as_of` argument at all.
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
- **Explicit transaction costs** — commission, spread and slippage will be
  named, configurable terms; gross and net results reported side by side.

## Layout

```
src/quant_backtester/
    data/        providers, Parquet store, trading calendars   (done)
    signals/     information -> forecast scores                (V1 done)
    portfolio/   forecast scores -> target positions           (to write)
    execution/   target positions -> fills and costs           (to write)
    backtest/    the event loop                                (to write)
    analytics/   performance and risk                          (to write)
    strategies/  concrete strategies                           (to write)
tests/           mirrors the package layout
market_data/     metadata/ is committed; raw/, clean/ and validation/ are not
```

Dependencies flow one way, left to right; a lower layer never imports a higher one.

## The data layer

| Module | Role |
|---|---|
| `instruments.py` | the registry: what each series is, and when it becomes public |
| `calendars.py` | sessions, real opening and closing instants in UTC |
| `sources/` | one adapter per provider: Yahoo, FRED, ECB, Euronext |
| `normalizer.py` | provider frames to canonical schemas, availability stamped |
| `validator.py` | rules typed by asset class |
| `crosscheck.py` | several sources to one checked series, field by field |
| `revisions.py` | detecting a change is not deciding to apply it |
| `corporate_actions.py` | reviewed corrections to what a provider called an event |
| `repository.py` | the only module that knows Parquet exists |
| `updater.py` | ingestion, and the replay that proves it reproducible |
| `reader.py` | point-in-time reads, and nothing else reaches a strategy |

Sources in use: Yahoo Finance (bars and corporate actions), FRED (published
series), the ECB reference rates, and the Euronext historical export as a second
opinion on Paris prices.

## The signals layer

| Module | Role |
|---|---|
| `types.py` | window modes, price bases, units, and the seven statuses |
| `context.py` | what a signal may read at one instant, and nothing else |
| `windows.py` | a window of N sessions, or the reason it is not one |
| `base.py` | the contract, the result frame and its diagnostics |
| `engine.py` | several signals over one decision |
| `snapshot.py` | what a strategy receives |
| `price/`, `risk/` | the six signals computed from one instrument's own window |
| `cross_sectional/` | ranking those signals across a universe |

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
    ["ETF_WORLD", "SP500"],
)

snapshot.value("momentum_60d", "ETF_WORLD")  # 0.0260
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
```

```python
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from quant_backtester.data.calendars import CalendarRegistry
from quant_backtester.data.instruments import InstrumentRegistry
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.repository import MarketDataRepository

root = Path("market_data")
reader = MarketDataReader(
    repository=MarketDataRepository(root),
    instruments=InstrumentRegistry.from_toml(root / "metadata" / "instruments.toml"),
    calendars=CalendarRegistry.from_directory(root / "metadata" / "calendars"),
    reference_calendar_id="XPAR",
)

# 23:00 in Paris: the US and European closes of the day are knowable.
decision = reader.at(datetime(2026, 9, 17, 23, 0, tzinfo=ZoneInfo("Europe/Paris")))
prices = decision.history("SP500")  # nothing after the decision instant
state = decision.values(["SP500", "VIX"])  # value, age in sessions, and why
```

Other scripts: `generate_calendars.py` rewrites the committed calendars from
`exchange_calendars`, `check_calendar_coverage.py` says when they need
extending, and `accept_revision.py` builds the entry that approves one detected
correction.

Development rules live in [CLAUDE.md](CLAUDE.md).
