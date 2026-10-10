# Changelog

## Unreleased

### SA11 - GARCH vol control (specification of 2026-10-10)
- **New strategy `SA11`** (`GarchVolControl`): the exposure to `ETF_WORLD` is
  `min(1, 12% / max(sigma, 5%))` with `sigma` the one-step forecast of a
  zero-mean GARCH(1,1) with Student innovations, estimated again at every
  decision on the 756 log returns known then. A fit refused on valid data
  falls back on an EWMA (0.94) of the same window, and says so. Its control,
  `EwmaVolControl`, applies the same rule to the EWMA alone and has no
  catalogue code.
- **New signals** `GarchVolatilitySignal` and `EwmaVolatilitySignal`
  (`signals/models/garch.py`), with `forecast_garch`, a pure function of its
  returns and configuration, in decimal units.
- **New optional dependency**: the `stats` extra (`arch`). Every other
  strategy, the catalogue and the class of `SA11` import without it; a run of
  `SA11` without it stops at `validate()` with `MissingDependency`.
- **New module** `analytics/volatility_forecast.py`: ex-post pairing of a
  forecast with the next session's return, QLIKE with a counted metric floor.
- **`scripts/run_garch_study.py`**: the common-period comparison
  (2021-04-01 to 2026-10-09), ranked by `QUALITY_V1` with an explicit register
  of trials, the forecast evaluation, the paired bootstrap and a second real
  run with every cost doubled.
- **`scripts/run_etf_strategies_comparison.py`** takes `--start` and `--end`,
  runs `SA11` when its estimator is installed (and names it as left out
  otherwise), and writes `quality_details.csv`. Its default period is
  unchanged, so the table of 2026-10-04 is reproduced by the same command;
  `SA11` holds cash there until its window is full, and the script says so.
  `quality_scores()` is unchanged; `quality_details()` takes the number of
  trials and their dispersion explicitly.
- **CI** installs both extras and fails if either is missing, so that the
  GARCH suite is executed and not skipped.
- Hypothesis `sa11_garch_vol_control` registered before the first run.
- **`scripts/write_strategy_reports.py`** writes one
  `strategy<CODE>_ResultsAndAnalysis_<DDMMYYYY>.md` per strategy from the
  study's exports: the global indicators, an analysis (measured stretches,
  then a written commentary read from `commentary.toml`) and the session by
  session history of the closes, the signals read, the weights and the value.
  The reports of 2026-10-10 are in `research/reports/2026-10-10/`.
- **Review of the analyses (2026-10-10).** The commentaries were rewritten
  after an independent review of commit `4e04eae`: positions are told by the
  dates, signals and weights the histories publish, each point says whether it
  is a measured fact or a reading, and causal claims nobody measured are gone
  or listed as open. The reports now give the day each drawdown's peak was
  reached again, months by sign (idle months apart), partial years, valuations
  and returns as two counts, the geometric relative return, the even split
  beside the fund held, and a report for each of the two references. The
  study gives an interval on the differences of QLIKE and says that `REFUTED`
  is the registered criteria not being met, not a proof of inferiority. No
  global figure changed.
- **Result.** On 2021-04-01 to 2026-10-09 the hypothesis is refuted: `SA11`
  has the best variance forecast (QLIKE) and a net Sharpe ratio of 0.87,
  below `SA6` (0.90) and the EWMA control (0.93), with a deeper drawdown and
  2.5 times the costs. The simple rule is kept; `SA11` stays in the catalogue
  as a fixed reference.

### Audit 13 (strategies and performance), C01 to C04
- **C01.** Returns that are constant in theory have no Sharpe ratio: the
  report gives `None` and the bootstrap raises `UndefinedStatistic`, under
  `RETURN_STD_TOLERANCE`, now in `analytics/config.py` and shared by every
  figure that divides by a spread. It used to print 1.7e14.
- **C03.** `StrategyResult.reading()` hands the store to a read made after a
  run only while its digest is the run's, and raises `StoreChanged` otherwise.
  `benchmark()`, the figures of the exercise and study scripts, the ETF
  comparison and the export of ML1's decisions go through it, before writing.
- **C02.** `StrategyResult.weight_of()` is zero for a fund never held; the
  figures of a run that stayed in cash are written instead of failing.
- **C04. Records change, results do not.** A decision now records what it was
  taken among: `considered` counts the instruments whose signal was usable,
  whatever the rule answered, through `ctx.considering()` in the one-fund
  examples and the readable count of `SignalReader` in the SA rules; ML1 does
  the same. Orders, fills and P&L are identical. The field `considered` of a
  stored record is not: it was 0 on every day a rule answered cash, and is now
  0 only when no signal could be read, so "sessions with nothing to choose
  from" falls for every rule that stands aside by decision. A records file
  written before this change differs from one written after it on that field
  alone.

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

### Study: the night against the session
- `analytics/segments.py` splits a close-to-close return into its night
  (previous close to open) and its day (open to close), adds them up and
  compounds the books that hold one segment only, gross and net of costs.
- `scripts/run_session_segments_study.py` runs it on `ETF_WORLD` (discovery)
  and on `ETF_SP500_PEA` before 2019-04-01 (validation), and draws the price
  above the profit and loss of the books. Hypothesis `session_segments` was
  written in `research/hypotheses.toml` before the first run, and is refuted:
  the night carries 92.5% of the log return on the discovery window and 47.2%
  on the validation one, and a night-only book loses 89% net of costs.

### Study: a trend rule that holds through a hedged panic
- `ReturnLevelCorrelationSignal` (`signals/cross_asset/correlation.py`): the
  correlation of a fund's log returns with the changes of a published series,
  over the last dates both hold. `SignalUnit.CORRELATION` is new.
- `RateRegimeTrend` (`strategies/examples/rate_regime_trend.py`): hold a fund
  above its 200-session average, and below it only while shares and the
  ten-year yield move together and the VIX is in a panic.
- `scripts/run_rate_regime_study.py` runs it against buy and hold and the plain
  trend rule on `ETF_WORLD`, then on the S&P 500 index from 1991 to 2018, a
  paper run on a copy of the registry in which the index is tradable.
  Hypothesis `rate_regime_trend` was written before the first run. On the
  validation window its net Sharpe is 0.404 against 0.393 for buy and hold, a
  difference of +0.011 with a 95% interval of [-0.238, +0.243]: met to the
  letter, and no evidence of anything. On `ETF_WORLD` it is below both.

### Figures: trades are crosses
- The buys and sells of the moving-average figures are a green and a red
  cross instead of two filled triangles, which hid the price under them.
  `docs/figures/golden_cross_moving_averages.png` is redrawn; no number moved.

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

### Exercise 3: in above one average, out below another
- `MovingAverageEntryExitETF` (`strategies/examples/moving_average_entry_exit.py`):
  buy one fund when its close is above its 50-session average, sell it only
  when its close is below its 100-session one. The sale comes first: below the
  exit average nothing is bought, whatever the entry average says. Otherwise,
  and when either signal cannot be computed, the book is kept as it is.
- `scripts/run_moving_average_entry_exit_exercise.py` runs it with the runner,
  costs, period, benchmark and figure of exercise 1.

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
