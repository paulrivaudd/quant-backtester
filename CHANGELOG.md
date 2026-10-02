# Changelog

## Unreleased

### History rewritten on 2026-10-02
- The 21 commits of 2026-09-20 that carried a `Co-Authored-By: Claude` line
  were rewritten without it, and the 89 commits after them with them: 110
  hashes changed, from `101f1e5` onwards. Trees, authors, dates and the rest of
  every message are identical, checked commit by commit.
- `docs/HISTORY_REWRITE_2026-10-02.md` maps each old hash to its new one.
  `research/registry.jsonl` is left as it was written: its 19 lines name
  `5eb5b07`, which is now `61a017c`, and their `run_id` was computed with the
  old hash. A run repeated on the new commit has another `run_id` and the same
  numbers.

### Exercise 1: the golden cross
- `GoldenCrossETF` (`strategies/examples/golden_cross_etf.py`), its runner
  `scripts/run_golden_cross_exercise.py`, and a README section on what the
  rule is, why it was tested and what its run shows.

### Exercise 2: the price against its moving average
- `MovingAverageBandETF` (`strategies/examples/moving_average_band.py`): buy
  one fund when its close passes above its 50-session average, sell it when it
  passes below. `buy_above` and `sell_below` are multiples of the average, both
  1.0 by default; two different levels leave a band inside which the book is
  kept as it is, as it is when the signal cannot be computed. It reads the
  existing `MovingAverageTrendSignal` on adjusted closes.
- `scripts/run_moving_average_band_exercise.py` runs it with the runner, costs,
  period and benchmark of exercise 1, and draws the close, its average, the
  levels and the trades (`moving_average_band.png`).

### Analytics: alpha, beta and information ratio
- `analytics.relative.RelativePerformanceStats`: regression alpha against the
  benchmark (per session and times `sessions_per_year`), beta, annualised
  active return, tracking error, information ratio and R squared, on simple
  per-session returns; `None` with a stable diagnostic code when the sample
  cannot identify a figure, never a zero or an infinity.
- `analytics.curves.aligned_equity_curves`: two curves on one period, ends
  trimmed, a session missing on one side inside it refused. `compare()` uses it
  instead of an intersection, which bridged a missing session with a
  multi-session return counted as one.
- `Comparison` gains `relative`, `benchmark_spec`, `book` and `relative_frame()`;
  `compare(..., book=)`; `PerformanceReport` gains `gross_comparison`,
  `net_comparison` and `relative_frame()`, and `of(..., benchmark=)` refuses a
  benchmark that does not cover the whole run. The runner passes the benchmark
  it already valued; `StrategyResult.report(benchmark=...)` builds an
  exploratory report without touching the kept one;
  `StrategyResult.relative_records()` exports the figures with their provenance.
- `run_baselines.py` prints a relative table (net book, against `ETF_WORLD`)
  after each table and writes `<run>_relative.csv` with `--records`; `vs world`
  keeps its meaning.
- A missing absolute figure in a comparison prints as a dash, not `nan`.
- No record changes: the 20 records of the readme suite are identical byte for
  byte to the last snapshot.

### Breaking
- `RealizedVolatilitySignal.annualization` has no default any more: it is a
  research convention (252 for XNYS, 255 for XPAR), and the default of 252
  disagreed with the 255 the Paris reports are annualised by. No committed
  strategy or suite builds one, so no record and no `run_id` moves.
- `quant_backtester.data.normalizer.bars_frame` (was `_bars_frame`) is public:
  it is the step every bar normalizer ends in, a new source's included.

### Added
- `quant_backtester.demo` and `scripts/demo.py`: two funds drawn from a seed on
  a synthetic calendar, written to a temporary store and run through the real
  reader, engine, execution model and report - a first backtest with nothing
  downloaded.
- `docs/DONNEES.md` (the data layer, adding an instrument or a source),
  `docs/FORMULES.md` (every formula of the code), `docs/OPERATIONS_SUR_TITRES.md`
  (what is and is not done with a corporate action), `docs/GLOSSAIRE.md`.

### Documentation
- `docs/ARCHITECTURE.md`: `backtest/runner.py` named as the one composition
  facade allowed to import upwards; `portfolio` works in weights and
  `execution` in quantities and lots; the ten reject reasons; the corporate
  action check before each open; every module, the delivered strategies, the
  scripts, the POSIX requirement and `pydoc` as the API reference.

### Removed
- The empty `data/raw/` and `data/processed/` of the first scaffold; the store
  lives under `market_data/`.

### Performance
- The reader prepares each series once per file version - contested sessions
  and missing values removed, sorted - and each instant only slices and
  filters it; corporate actions are sorted once per version of their table.
  The records of every suite are identical byte for byte.

### Research
- A kept run (`research.archive`): read back without recomputing, recomputable
  from a checked copy of the store it read; `run_baselines.py --keep DIR`.
- Hypotheses written in `research/hypotheses.toml` before their runs; verdicts
  as events beside the register; a paired block bootstrap of a strategy against
  its executable control, printed by the readme suite.
- Paper plans commit to a `contract_id`, log each session's whole economic
  state, advance only on committed code and only once a session is ready, and
  their journals are appended under a lock.
- `quant_backtester.research`: an append-only experiment register that counts
  every variant, rejected ones included, and only accepts committed code; paper
  plans fixed by fingerprint, whose logs are never rewritten.
- `research/PROTOCOL.md`; two paper plans starting 2026-10-01;
  `scripts/paper_trade.py`; `run_baselines.py --register`.

## 0.2.0 — 2026-09-26

The fixes of two audits of 2026-09-26: the first (A01–A18, decisions D1–D10)
and the audit of those fixes (R01–R11, decisions D11–D16). The figures of the
README are unchanged to the printed precision; the run records they come from
are archived with the state of the store that produced them.

### Migrating from 0.1.0

| 0.1.0 | 0.2.0 | What to do |
|---|---|---|
| Any platform with Python 3.12 | POSIX only: Linux, macOS, WSL | Run under WSL on Windows. The store is locked with `flock`. |
| `PriceBasis.TOTAL_RETURN` | `PriceBasis.ADJUSTED` | Rename. The series is an adjusted price (`1 - D / C_prev`), not a reinvested wealth. |
| `reader.total_return_history(...)` | `reader.adjusted_history(...)` | Rename. |
| `BenchmarkSpec(..., price_basis=PriceBasis.RAW)` | `BenchmarkSpec(..., basis=BenchmarkBasis.PRICE_RETURN)` | Migrate. A price-return benchmark now neutralises splits. |
| `BenchmarkSpec(..., price_basis=PriceBasis.TOTAL_RETURN)` | `basis=BenchmarkBasis.TOTAL_RETURN` (the default) | Migrate. Dividends are reinvested at the ex-date close. |
| `instruments.toml` entries | `history_basis` and `history_note` required | Declare both for every instrument, custom registries included. |
| `metadata/` | `known_gaps.toml` required | Commit one, empty if nothing is known. |
| `MarketDataUpdater(...)` | `known_gaps=` required | Pass `KnownGaps.from_toml(...)`. |
| `schedule.decision_sessions(sessions)` | `decision_sessions(sessions, following=...)` | Pass the calendar's next session, or `None` at the end of its coverage. |
| `StrategyResult(...)` built by hand | `data_state` required | Build results through `StrategyRunner`. |
| `RunQuality(...)` built by hand | `max_realised_weight` required | Build it with `RunQuality.of`. |
| `HistoryCoverage.complete` (ends only) | `spans_declared_window` (ends only); `complete` counts every session | Use the one you mean. |
| `BenchmarkCurve.equity` was a stored series | A new series on every read | Nothing to do; mutating it no longer changes the result. |
| `ctx.keep_and_buy({name: weight})` | `ctx.keep_and_buy({name: share of cash})` | The values are now shares of the cash at the next open. |
| `clean/vintages/*.parquet` without `withdrawn` | Refused with `StoreFormatError` | Rebuild from `raw/` (`--rebuild --only <id>`). |
| A session only a check source serves | Not served; reported `SECONDARY_ONLY_SESSION` | Nothing to do; the checked series covers the primary's sessions. |
| The table's `trades` column | `rebal.` and `fills` | Read `rebal.` as sessions traded, `fills` as orders done. |

### Data and storage
- An infinite price, volume, level or action value is refused (A11).
- A merged bar is validated, and a broken merge refuses the whole promotion (A03).
- A check source confirms the primary's sessions and adds none (A06, D8).
- One writer holds the store (`flock`); a second gets `StoreBusy`; opening the store never deletes live work (A02).
- A run reads a complete generation, finishing an interrupted commit first (R03, D14).
- A rebuild is one transaction and decides what to replay under the lock (A16, R04).
- A promotion that finds an error is refused whole, journal of applied fetches included (R09).
- The stored action table is validated, not only the fetch; a split and a distribution on one ex-date are refused (D2, R08).
- A vintage that withdraws an observation is stored as a withdrawal (A09); vintage archives are found by every helper (A10).
- Coverage counts every session inside the span, contested sessions apart, and reviewed gaps apart (A12).
- Older formats are named: an older commit manifest is finished; an older clean file raises `StoreFormatError` (R11, D16).
- Every instrument declares its `history_basis` (D10); `known_gaps.toml` records reviewed gaps, which are never filled.

### Results
- The benchmark is a wealth chained from raw closes over its own sessions, with actions counted when known (A01, R02, D1, D13).
- A benchmark is not carried past its delisting (A15, D7).
- A run pins the digest of the store and of the registries it was handed; `run_id` identifies the whole experiment; a later comparison on a changed store raises `StoreChanged` (A05, R07, D15).
- The kept benchmark cannot be rewritten through a series it hands out (R06).
- The market view answers an absence instead of raising (A04).
- The recorded configuration holds the whole statistical convention (A13).

### Strategies and schedules
- Buy and hold completes its basket with the cash at the next open, then keeps it (A07, R05, D5, D12).
- A week or a month ends on the market's calendar, not at the run's end, and a run may end on the last covered session (A18, R10).
- The mutation guard is documented for what it checks: the declared definition (A14).

### Reports
- The report states its assumptions: fill model `OPEN_AUCTION_NOTIONAL`, what gross is, what cash earns, what limits cap, how long a decision lives, and the history basis of what was read. It also reports the largest weight held (section 5, D4, D6, D9).
- The table counts rebalancings and fills (A17). A comparison says its benchmark is a yardstick.
