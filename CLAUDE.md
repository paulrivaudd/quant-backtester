# CLAUDE.md

Development rules for the `quant-backtester` project. Read this before writing code.

## What this project is

A daily-frequency backtesting framework for systematic strategies, built to be
correct and reproducible rather than fast or feature-complete. Research quality
is judged by whether a result can be trusted and reproduced, not by the Sharpe
ratio it prints.

## Environment

- Python **3.12** (pinned in `.python-version`; `requires-python = ">=3.12,<3.13"`
  so the lockfile resolves for exactly one interpreter).
- **uv** manages the environment and the lockfile. Never call `pip` directly.

```bash
uv sync                  # create/refresh .venv from uv.lock
uv add <pkg>             # runtime dependency
uv add --dev <pkg>       # dev dependency
uv run pytest            # tests
uv run ruff check .      # lint
uv run ruff format .     # format
```

`uv.lock` is committed and must stay in sync with `pyproject.toml`.

## Architecture

```
src/quant_backtester/
    data/         providers, local Parquet store, trading calendars
    signals/      information -> forecast scores
    portfolio/    forecast scores -> target positions
    execution/    target positions -> fills, slippage, transaction costs
    backtest/     the event loop that advances time
    analytics/    performance, risk, attribution, reporting
    strategies/   concrete strategies composed from the layers above
tests/            mirrors the package layout
market_data/      metadata/ is committed; raw/, clean/ and validation/ are not
```

Dependencies flow one way: `data -> signals -> portfolio -> execution ->
backtest -> analytics`. A lower layer must never import a higher one. If a
layer needs something from above, the dependency is wrong - pass it in.

## Design principles

These are not preferences; a change that violates one is a bug.

### 1. No look-ahead bias

- Every computation is keyed by the timestamp at which the information became
  **available**, not the timestamp it describes.
- Use timezone-aware UTC timestamps internally. Convert to exchange-local time
  only at display or calendar boundaries. Never use naive datetimes.
- Rolling/statistical windows must be strictly backward-looking. No centred
  windows, no full-sample normalisation, no fitting on data the decision point
  cannot see.
- A rolling signal declares whether it needs **N expected sessions in a row** or
  **N available observations**, and the API enforces the one it asked for.
  `tail(N)` is not a window contract: the reader drops a session it cannot serve
  rather than returning a `NaN`, so twenty observations may span twenty-six
  sessions, and a twenty-day momentum computed on them is not a twenty-day
  momentum.
- Only the `backtest` layer advances time. Signals and portfolio code receive a
  decision timestamp and the history available at it - nothing else.
- Provider revisions matter: prices, splits and dividends are restated. Prefer
  point-in-time data; where only a restated series exists, say so explicitly in
  the module docstring.

### 2. Explicit calendars and timestamps

- Trading calendars are data, not assumptions. Holidays, half-days and DST
  shifts are handled by the calendar in `data/`, never by `freq="B"`.
- The canonical timeline is a cross-market one: a signal computed after the **US
  close** may be executed at the **following European open**. That gap is
  modelled explicitly, never approximated as "next bar".
- Every function that takes a date takes a decision timestamp with a timezone
  and a documented meaning ("as of", "trade at", "settled on").

### 3. Data handling

- Market data is stored locally as **Parquet** under `market_data/`, never
  committed. Its `metadata/` is the exception: instrument registry, calendars,
  cross-check tolerances and reviewed decisions are configuration, and a result
  follows from committed code plus committed configuration.
- Multiple providers are supported behind one interface. Provider-specific
  quirks (column names, adjustment conventions, symbology) are normalised
  inside the provider adapter, never leaked downstream.
- Anything outside `data/` performs no network I/O. Tests never hit the network
  unless marked `@pytest.mark.network`.
- Raw downloads are immutable: transformations write new files instead of
  editing what was fetched.

### 4. Transaction costs are explicit

- No backtest reports a return without a cost model attached. Commission, spread
  and slippage are separate, named, configurable terms living in `execution/`.
- Fill assumptions (which price, which timestamp, what participation limit) are
  stated in configuration, not buried in the engine.
- Report gross and net results side by side.

### 5. Reproducibility

- A result is reproducible from committed code plus a committed config: same
  inputs, same numbers, bit for bit.
- Seed every source of randomness explicitly; no implicit global RNG state.
- No hidden defaults for research parameters - lookbacks, thresholds, cost
  assumptions and universes are declared in the strategy config.
- Never silently alter historical output. Changing a result is a reviewed,
  documented change.

## Testing

- Every non-trivial component gets unit tests: `tests/` mirrors the package
  layout (`tests/data/test_calendar.py` for `data/calendar.py`).
- Tests are deterministic and offline: fixed seeds, synthetic or committed
  fixture data, no wall-clock or network dependence.
- For each new layer, test at minimum:
  - the intended behaviour on a small hand-checkable example;
  - the boundary case (empty input, single observation, missing bar, holiday);
  - **the look-ahead guard** - feed data containing a future value and assert
    the result does not change.
- Mark slow tests `@pytest.mark.slow` and network tests `@pytest.mark.network`.
- Warnings are errors (`filterwarnings = ["error"]`). Fix the cause, don't
  silence it.

## Code style

- `ruff` is the single source of truth for lint and formatting; both must be
  clean before a commit.
- Full type annotations on public functions. `from __future__ import annotations`
  at the top of every module.
- Numpy-style docstrings on every public module, class and function. State
  units, timezone conventions and the availability timestamp of any input.
- Prefer explicit, boring code over clever vectorisation. Where a vectorised
  form is genuinely needed, add a test comparing it against a naive loop.
- Small, pure functions; pass dependencies in rather than reaching for globals.

## Workflow

- Explain the intent before making non-trivial changes.
- Keep commits focused; run `uv run ruff check . && uv run ruff format --check . &&
  uv run pytest` before committing.
- Don't add dependencies casually - each one must earn its place.
