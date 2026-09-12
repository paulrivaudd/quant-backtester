# quant-backtester

A daily-frequency backtesting framework for systematic strategies, built around
one priority: results you can trust and reproduce.

## Status

Early setup. The project structure, tooling and development rules are in place;
the engine itself is not implemented yet.

## Design goals

- **No look-ahead bias** - every value is keyed by the time it became available.
- **Explicit calendars** - real trading calendars, timezone-aware timestamps. A
  signal computed after the US close trades at the following European open, and
  that gap is modelled rather than assumed away.
- **Explicit transaction costs** - commission, spread and slippage are named,
  configurable terms; gross and net results are reported side by side.
- **Local Parquet data** - multiple providers behind one interface, cached
  locally, never committed.
- **Reproducible research** - a result follows from committed code plus a
  committed config, with every random seed fixed.

## Layout

```
src/quant_backtester/
    data/        providers, Parquet store, trading calendars
    signals/     information -> forecast scores
    portfolio/   forecast scores -> target positions
    execution/   target positions -> fills and costs
    backtest/    the event loop
    analytics/   performance and risk
    strategies/  concrete strategies
tests/           mirrors the package layout
```

Dependencies flow one way, left to right; a lower layer never imports a higher one.

## Getting started

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12.

```bash
uv sync                # create the environment from uv.lock
uv run pytest          # run the tests
uv run ruff check .    # lint
uv run ruff format .   # format
```

Development rules live in [CLAUDE.md](CLAUDE.md).
