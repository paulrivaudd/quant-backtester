# SA17 — corrected data and research protocol

Written 2026-11-07, before any SA17 performance run. This document supersedes
the sourcing alternatives in the initial proposal and README. Status:
**DATA_PREPARATION / NOT_TESTED**, not a selected executable strategy.

## Separate ranking, risk and execution

Ranking uses official accumulating-fund NAVs in **USD**, paired with the USD
S&P 500 total-return market on the same US observation dates. EUR-listed
exchange closes, ECB fixings and State Street's reference EUR NAVs are not
ranking inputs. Portfolio currency/hedging is a separate choice. The initial
portfolio is unhedged, long-only, no leverage, EUR 100,000 and whole units.
Accumulating NAVs retain income net of fund expenses and applicable taxes;
they are not gross sector total-return indices. The S&P gross-versus-net
market choice remains an explicit mismatch to audit; an intercept does not
guarantee that time-varying withholding differences vanish.

Nine issuer NAV histories begin 2015-07-07; communications begins 2018-08-15.
See `nav_source_evidence.json` for all ten ISINs, source URLs, hashes, coverage
and retrieval times. Archive: `runs/sa17_nav_inputs_20261107_v2`. NAVs are
nontradable **LEVEL** inputs, never manufactured OHLC or execution prices.
Current histories are conservatively `RESTATED`; retrieval is not a historical
vintage. Fund splits, historical classifications, inception eligibility and
survivorship must still be audited before admitting a performance experiment.

Every fund supplement states a valuation point at **22:15 Europe/Dublin**
(23:15 Paris), based on last-traded prices. The umbrella prospectus (19 February
2026, printed p.55) describes publication on the following business day.
Neither is proof that a NAV was public at the US close or at 23:00 Paris.
The historical XLSX files contain dates, not release timestamps. Therefore
the initial normalized store stamps retrieval-only availability and cannot
support historical decisions. A dated RNS publication can supply observed
availability for its own rows; it cannot justify backdating the whole XLSX.

The corrected monthly rule reads the **previous completed US month**, on a
decision after its NAV releases are established. A common explicit observation
cutoff fixes sector, market and covariance dates; no partial current month is
substituted. Retain the project's 23:00 Paris decision and next tradable open;
choose the first eligible monthly decision from validated publication evidence
before freezing the execution schedule. Merely delaying by one day without
evidence is a sensitivity assumption, not verified historical availability.
Amended 2026-11-07, after review and before any run: the strategy holds no
configurable cutoff. Each decision's cutoff is the previous completed month of
that decision, recorded in the signal definitions; a fixed date reused across a
run would freeze every later window. An explicit cutoff given to a signal must
resolve to the last XNYS session of that month: a mid-month session would score
a partial month as a completed one.

The OLS window stays 36 monthly returns with an intercept; score the mean of
the 11 residuals excluding the latest month over their sample standard
deviation. Hold the top three sectors, equal within the sleeve. The risk budget
stays 15% annualized, using 63 daily simple returns and sample covariance.
Risk inputs are separate NAV series, converted to EUR by **USD NAV / USD per
EUR**, with matching observation dates and validated valuation timestamps.
Both the FX and NAV must be available at the decision. Official reference EUR
NAVs use WM 16:00 London FX, explicitly disclosed on issuer pages: they are
not synchronous US-close FX. No suitable historical synchronous FX feed has
yet been admitted. No ECB substitution or implicit FX hedge is allowed.

## Gaps, fallback and executable prices

Use primary issuer NAVs and an identified secondary NAV distribution channel
(official LSE RNS announcements), validating ISIN, currency, date, type and
publication time. Reconcile overlapping observations; a material disagreement
requires review, never arbitrary selection. Preserve source/fetch lineage and
availability when filling a missing row. A different locale of the same XLSX
is not an independent source. RNS also originates with the issuer: it provides
distribution redundancy and publication evidence, not an independent valuation.

The acquired RNS notice published **2026-11-06 10:20:21 UTC** reports the NAVs
of 2026-11-05. All ten requested funds agree exactly with their issuer XLSX;
`lse_nav_validation.json` records the check and provenance. The reproducible
replay is `runs/sa17_lse_nav_20261107_v2`. The source adapter filters availability
before reconciling, fills primary gaps, and refuses unreviewed conflicts beyond
USD 0.00005. A review is bound to both values and its own timestamp. One notice
does not establish full historical coverage; no such coverage is claimed.

A single provider outage must trigger acquisition/reconciliation before a
decision is abandoned. If both validated sources are missing, the safe guard
still prevents a fabricated signal or silently reduced ranking universe.
The two Yahoo Xetra holes must be checked against actual NAV coverage; this
does not fill missing execution opens for the traded ETF or external books.

Zero reported volume does **not** establish inability to trade or absence of
market-maker quotes. Xetra designated sponsors quote two-sided prices under
venue requirements. Conversely, their presence does not prove an arbitrary
historical opening price was executable. The engine has no volume-based veto;
retain valid prices, flag stale/suspect bars and acquire another price/quote
source for missing execution observations. Never trade at NAV or at a previous
close to hide an execution-data gap. The opening-price-plus-cost model remains
an approximation requiring quote evidence, especially when US markets are shut.

The actual NAV audit (`nav_calendar_coverage.json`) confirms both 2025-10-24
and 2026-03-06 in all ten funds. It also finds **26 missing XNYS dates** for
nine funds and **18** for communications through 2026-10-30. Many are European
holidays, including Easter Mondays; the initial month-end 2015-08-31 is absent.
Thus NAV publication is not identical to the NYSE calendar. Some observations
also exist when NYSE is shut. Audit the historical **fund dealing calendar**
before defining a common observation grid; do not turn a fund nonvaluation day
into a provider outage, fabricate a NAV, or silently drop expected dates.
The current strict XNYS contract correctly refuses these incomplete windows.
An official common-calendar extension must be registered before a run.

All ten NAV series were normalized through the framework into
`runs/sa17_nav_store_20261107_v3`, with zero validation errors. Its registry
pins `publication_rule.not_before_utc` to each fetch: a general availability
floor validated by the ordinary validator, not a source-specific bypass.
`nav_instruments.toml` records that snapshot. Earlier unsuccessful preparation
directories are retained; none produced a performance run.

## Costs fixed before runs

`costs.toml` declares a separate half-spread for each fund, commission 5 bp
with EUR 1 minimum per order, and slippage 5 bp. These are **research assumptions**,
not a historical fee schedule or reconstructed bid/ask archive. The quoted
issuer snapshot is dated 2026-11-06. Full spread is recomputed from displayed
bid/ask; inconsistent printed spread rounding is not silently copied.
The technology bid exceeds its offer and is rejected as a crossed quote;
its declared 15 bp half-spread is an explicitly provisional stress assumption.
Other half-spreads follow the predeclared conservative formula in the file.

`load_sector_costs` supplies `ExecutionModel.costs_by_instrument`; all sizing,
cash affordability and fills use the instrument model. At doubled costs,
double commission, its floor, half-spread and slippage in a real second run.
Declare reference-book and monetary-fund models before that run as well.
Publish gross/net results, spread/commission/slippage, rejects, cash, turnover,
mean/max orders from `result.orders()` and intervention days. Max 20 orders
per session, target 1–10 on intervention days. No performance run in this task.

## Power: significance is not high probability of detection

Under IID stationary Gaussian active returns, annual active information ratio
IR gives approximately `t = IR * sqrt(T_years)`. For 8.25 years, the two-sided
5% critical observed IR is **0.682** (the rough `2/sqrt(8.25)` is 0.696).
This is a rejection threshold, **not 80% power**. A true IR near that threshold
gives only about 50% power. The approximation for 80% power is
`(1.960 + 0.842)/sqrt(8.25) = 0.975`.

| Assumed true IR | Power over 8.25 years | Approx. years for 80% power |
| --- | ---: | ---: |
| 0.3 | 13.8% | 87.2 |
| 0.5 | 30.1% | 31.4 |
| 0.7 | 52.0% | 16.0 |

These IRs are **scenarios supplied for planning**, not established estimates
for this exact long-only residual-NAV strategy. See tested calculations in
`quant_backtester.research.power` and `power.json`. Serial dependence,
nonstationarity, estimated variance and multiple comparisons weaken the simple
calculation. A large cross-section does not multiply independent years.
An eight-year executable backtest chiefly tests implementation and realistic
costs; it can provide evidence but generally cannot settle a modest edge.
`UNCERTAIN` is a plausible result, not a verdict fixed before observation.

## Long mechanism study, separate from execution

Ken French monthly value-weighted **10 industries** and the matching broad US
market (`Mkt-RF + RF`) are the primary mechanism data. **49 industries** are a
prespecified breadth robustness check, never an alternative selected after
results. Files include dividends and begin July 1926. The acquired vintage
has 1,203 monthly observations through September 2026, archived separately in
`runs/sa17_french_inputs_20261107`; hashes in `ken_french_source_evidence.json`.

The library uses SIC, not GICS; the market is the broad CRSP US universe,
not S&P 500. These research portfolios are not UCITS ETFs and cannot be used
as executable pre-inception prices. Data are rebuilt and revised (`RESTATED`),
including the FIZ/CIZ transition in 2025: dividend reinvestment changes from
month-end to ex-date compounding. Missing -99.99/-999 cells remain missing;
no zero fill, annual table or equal-weight table substitutes for monthly VW.

Use the same 36/11/1 residual score and compare to plain 12–1 momentum and
equal-weight industry controls. The monthly-only study tests selection,
**not the daily 63-return volatility mechanism**. Any monthly risk-control
extension needs its own hypothesis. These well-known portfolios have been
used extensively in prior research; this is replication/robustness, not a
new discovery or independent validation. Prespecify 1929–1969, 1970–1999,
2000–2017, 2018–2026 descriptive regimes; disclose all, select none.

## Mechanism study: frozen design

Written 2026-11-07, before any score, weight or portfolio return was computed
on the French data. Only the archive's coverage (columns, first and last
month, hashes) had been read. Every parameter is in
[`mechanism.toml`](mechanism.toml); the run reads it and nothing else. A
change after the run is a new hypothesis, not a correction.

**Inputs.** The three archived ZIPs of `runs/sa17_french_inputs_20261107`,
replayed offline through the Ken French adapter and refused if their SHA-256
differs from `coverage.json`: monthly value-weighted 10 and 49 industries, and
the factors, with `Mkt = Mkt-RF + RF`. Returns are USD fractions labelled by
month, restated, not point-in-time.

**Formation.** At the end of month *t*, an industry is eligible when its 36
returns *t−35..t* are all present. `residual_fit` (the function SA17's signal
uses) regresses them on the market's with an intercept and scores the mean of
the 11 residuals *t−11..t−1*, the latest month skipped, over their sample
standard deviation. A fit that `residual_fit` refuses leaves the industry
ineligible that month; such months are counted.

**Books.** Each holds its industries in equal weight over month *t+1*,
rebalanced every month:

- `RESIDUAL` (the candidate): the top 3 of 10 by score, or the top 15 of 49
  (the same 30% share);
- `C1_MOMENTUM_12_1`: the same count, ranked by the compounded return of the
  same months *t−11..t−1*;
- `C2_EQUAL_WEIGHT`: every eligible industry;
- `MARKET`: `Mkt`, held at no cost, descriptive only.

Ties go to the earlier column of the file. With fewer eligible industries than
a book holds, that book holds the risk-free rate for the month. A held
industry whose return for *t+1* is missing earns `RF` that month; these cases
are counted and reported.

**Costs.** These are hypothetical, since the portfolios are not tradable: 10 bp of
the traded value, one way. At each rebalancing, turnover is the sum over
industries of the absolute difference between the target weight and the
weight drifted by the month's returns; moves to and from `RF` are free. The
first formation buys from cash. The month's net return is
`(1 − cost × turnover)(1 + gross) − 1`. Doubled costs (20 bp) are a second
real run.

**Window.** Holding months July 1929 to September 2026: the first formation is
the first month with 36 returns behind it. The 10- and 49-industry studies
share the window.

**Statistics.** Each book's monthly returns are taken in excess of `RF`. The
primary statistic is the Sharpe ratio of excess returns (mean over sample
standard deviation, times √12). CAGR, maximum drawdown and, against each
control, active mean, tracking error and information ratio are reported. So
are the turnover and cost paid by each book.

**Inference.** The candidate is compared with each control by a paired
stationary bootstrap (Politis–Romano: geometric block lengths, circular wrap,
the same indices for both books). Excess returns are resampled, with an
expected block of 12 months, 10,000 draws, seed 20261107. The 95% intervals
are percentile intervals. The two-sided p-value of a zero difference is
`(1 + #{|d* − d| ≥ |d|}) / (draws + 1)`, from the resampled differences
centred on the estimate. Holm's adjustment is applied within the family
{vs `C1_MOMENTUM_12_1`, vs `C2_EQUAL_WEIGHT`}. Blocks of 6 and 24 months are
reported as sensitivities, never selected.

**Verdict.** It is read on 10 industries at the declared costs, one per
comparison:

- vs `C1_MOMENTUM_12_1` judges the market adjustment;
- vs `C2_EQUAL_WEIGHT` judges the selection.

`SUPPORTED_RETROSPECTIVE` requires a positive Sharpe difference, a Holm
p-value below 0.05, and a difference still positive at doubled costs.
`UNCERTAIN` is a positive difference that misses either. `NOT_SUPPORTED` is a
difference at or below zero. The 49-industry study, the block sensitivities and
the four regimes (holding months 1929-07–1969-12, 1970–1999, 2000–2017,
2018-01–2026-09) are reported in full and cannot change a verdict.

## Future comparison and admission gates

Fixed executable references remain SA16_it2 as archived and Nasdaq held; four
sector controls remain plain momentum, residual without vol target, all
eligible sectors equal-weight, and that basket with the same vol target.
Compare common dates, capital, EUR, clocks and costs. CAGR and Sharpe net must
both exceed references; drawdown may be at most 2 percentage points deeper.
Report 2018–2019, 2020, 2021, 2022 and later annual regimes, including failures.

Use paired stationary bootstrap from `analytics.uncertainty`, seed 20261107,
10,000 resamples, expected block 20 daily sessions; blocks 5/60 as sensitivity.
For the long monthly study use 12-month blocks, with 6/24 sensitivities.
Report unadjusted descriptive intervals and Holm-adjusted tests within each
declared family of reference comparisons, with all controls/configurations
counted. Deflated Sharpe, neighboring parameters, actual shifted-start runs
and doubled-cost runs do not turn retrospective selection into validation.

Before the first executable fit/run, resolve publication coverage, synchronous
FX, historical classifications/actions, second-source conflict checks and
missing executable prices. Freeze the admitted metadata and schedule in a
new store. No `selected.json` or claim of superiority exists at this stage.

## Sources checked 2026-11-07

- Ten issuer pages and supplements: linked per ISIN in `nav_source_evidence.json`.
- [Umbrella prospectus, publication p.55](https://www.ssga.com/library-content/products/fund-docs/etfs/emea/2-GENERIC-EN-FP-IRISH-SPDR-II.pdf).
- [Dated official NAV announcement](https://www.londonstockexchange.com/en/news/article/net-asset-value-s/fec6-0e-4b-b8-87-40e8b9).
- [Xetra designated sponsors](https://www.cashmarket.deutsche-boerse.com/cash-en/trading/Xetra/Designated-Sponsor-and-Market-Maker).
- [French library, revisions and FIZ/CIZ](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html),
  [industry construction](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/det_10_ind_port.html),
  [factor construction](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/f-f_factors.html).

Search/browser extraction incidentally exposed issuer performance tables and
search snippets; no SA17 portfolio performance was calculated or used to tune
the rule. Such exposure is not described as a pristine unseen sample.
