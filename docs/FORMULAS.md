# Formulas

State on 2026-09-27. Each formula is the code's, with the file that computes
it. The financial definitions are in the [glossary](GLOSSARY.md), the
architecture in [ARCHITECTURE.md](ARCHITECTURE.md).

Conventions: a return of `0.05` is 5%. A basis point (bp) is 10⁻⁴. A window
`P_0, …, P_L` is ordered from oldest to most recent: it contains `L + 1`
prices, hence `L` returns. Histories are read only after the window has been
validated by `signals/windows.py` (see ARCHITECTURE §6). A formula that
returns `None` produces the status `INVALID_INPUT`, never a number.

## 1. Signals

For price signals, `PriceBasis.RAW` reads the quotations and
`PriceBasis.ADJUSTED` the closes adjusted for the corporate actions known at
the decision instant (see [CORPORATE_ACTIONS.md](CORPORATE_ACTIONS.md)).

| Signal | Window | Formula | Refused when |
|---|---|---|---|
| `ReturnSignal` (`price/returns.py`) | `L + 1` sessions | `R = P_L / P_0 − 1` | `P_0 ≤ 0` |
| `MomentumSignal` (`price/momentum.py`) | `L + 1` sessions, `L = lookback_sessions` | `M = P_{L−k} / P_0 − 1`, `k = skip_recent_sessions`, `0 ≤ k < L` | `P_0 ≤ 0` |
| `MeanReversionSignal` (`price/mean_reversion.py`) | `L + 1` sessions | `−(P_L / P_0 − 1)` | `P_0 ≤ 0` |
| `MovingAverageTrendSignal` (`price/trend.py`) | `n` sessions | `P_L / mean(P_{L−n+1..L}) − 1` | average ≤ 0 |
| `MovingAverageCrossSignal` (`price/trend.py`) | `max(a, b)` sessions | `MA_a / MA_b − 1`, each `MA` over the last prices of the same window | `MA_b ≤ 0`, `a = b`, `a < 2` or `b < 2` |
| `RealizedVolatilitySignal` (`risk/volatility.py`) | `n + 1` sessions, `n = window_returns` | `σ = sqrt(A) · sqrt( Σ (r_i − r̄)² / (n − d) )` | a price ≤ 0, `n ≤ d` |
| `CurrentDrawdownSignal` (`risk/drawdown.py`) | `n` sessions | `P_L / max(P_{L−n+1..L}) − 1 ≤ 0` | max ≤ 0 |
| `LevelChangeSignal` (`level/change.py`) | `L + 1` observations | `x_L − x_0`, in the series' unit | — |
| `LevelZScoreSignal` (`level/zscore.py`) | `n` observations | `(x_{n−1} − x̄) / s`, `s` with `ddof = 1` | `s = 0` |
| `CrossSectionalRank` (`cross_sectional/rank.py`) | the source signal | `(ρ_i − 1) / (m − 1)` | `m < minimum` → `INSUFFICIENT_CROSS_SECTION` |

Details:

- **Momentum with a skip.** The starting point stays `P_0`. Skipping the last
  `k` sessions **shortens** the measured period to `L − k` returns: the window
  does not shift into the past. For `k = 0`, momentum is the return.
- **Moving averages.** `MovingAverageCrossSignal(first_sessions=50, second_sessions=20)`
  gives a positive score when the 50 average is **above** the 20 average: it is
  a rule that buys the dip. The "golden cross" is written
  `first_sessions=20, second_sessions=50`.
- **Volatility.** By default returns are logarithmic
  (`r_i = log(P_i / P_{i−1})`), `d = ddof = 1` and `A = annualization`. `A` has
  **no default value**: it is declared like the other research parameters, 252
  for XNYS or 255 for XPAR. Multiplying by `sqrt(A)` assumes uncorrelated
  returns of comparable variance. It is a convention, not a property of the
  data.
- **Z-score.** The last observation is part of the mean and of the standard
  deviation. A constant window is refused.
- **Rank.** `ρ_i` is the average rank in case of a tie, and `m` the number of
  instruments whose score is usable. By default (`ascending=False`), the
  largest score receives 1 and the smallest 0. An instrument without a score
  keeps its status and never receives 0. A rank is not an economic gap: being
  first of two is not a 100% conviction.

Example by hand (`tests/signals/price/test_trend.py`): for 100, 101, …, 109,
`MA_2 = 108.5`, `MA_5 = 107`, and the cross is `108.5 / 107 − 1 = 1.40%`.

## 2. Portfolio

With `C` the cash, `q_i` the quantities and `P_i` the valuation prices
(`portfolio/state.py`):

```
V   = C + Σ q_i · P_i
w_i = q_i · P_i / V                    (V > 0 required)
```

A target is admissible if `0 ≤ w_i ≤ 1` and `Σ w_i ≤ 1 + 10⁻⁹`.
`PortfolioLimits` first caps each line, then multiplies every weight by
`gross_cap / Σ w_i` if their sum exceeds the gross cap. What is removed stays
in cash.

**Average cost** (`portfolio/holdings.py`). `K` is the price paid per unit,
costs included:

```
purchase of Δq at price K:   P̄' = (q · P̄ + Δq · K) / (q + Δq)
sale of Δq              :   P̄' = P̄
```

It is not a tax calculation by lot.

## 3. Execution

`P` is the reference price (the open), `q > 0` the quantity, `h` the
half-spread, `s` the slippage, `c` the commission rate and `m` its floor
(`execution/costs.py`):

```
price paid       P_f = P · (1 + h + s)      purchase
                 P_f = P · (1 − h − s)      sale
commission       F   = max(c · q · P_f, m)  (0 if q = 0)
cash             −(q · P_f + F)             purchase
                 +(q · P_f − F)             sale
spread cost      q · P · h
slippage cost    q · P · s
```

Spread and slippage are **already in `P_f`**. The report shows them
separately, but they must not be taken off a second time.

With `Sizing.AT_DECISION`, the target quantity of a line `i` of weight `w_i`
is set on the book as the decision valued it:

```
V_d = C + Σ q_j · P_j^d       P_j^d = the close of j known at the decision,
                              or its last known price if it is missing
q_i* = w_i · V_d / P_i^d      (order refused, NO_DECISION_PRICE, if i has no close)
```

A held line without a close at the decision is never valued at zero: that
reduced `V_d` by its weight and made the other lines sell as much.

Example: `P = 100`, `q = 10`, `h = 0.0002`, `s = 0.0001`, `c = 0.0005`,
`m = 1`. One pays `P_f = 100.03` and `F = max(0.50; 1) = 1`, a disbursement of
1,001.30. The costs are 0.20 of spread, 0.10 of slippage and 1 of commission.

**Lots** (`execution/rounding.py`). A change of position is **truncated
towards zero** to the instrument's step, with a tolerance of 10⁻⁹:
`floor(q / step + 10⁻⁹) · step`. A sale of 4.5 lots too many sells 4 lots, not
5.

**Budget** (`execution/model.py`):

- Sales go before purchases.
- The cash spendable before commission is
  `max(0, min(C − m, C / (1 + c)))`.
- If several purchases exceed that cash, a common factor `λ ∈ [0, 1]` reduces
  them. The cash needed grows in steps with `λ` (lots, commission floor), so
  `λ` is found by **60 bisections**. No purchase is favoured. The part cut off
  is an `INSUFFICIENT_CASH` reject.
- A `keep_and_buy` purchase is brought back to its share of the cash, at the
  price actually paid (`CASH_SHARE_BUDGET`). One lot at a time is removed while
  the debit exceeds that share.

## 4. Analysis

`V_0, …, V_T` are the values of the book at the sessions `d_0, …, d_T`, and
`r_t = V_t / V_{t−1} − 1`. `A = sessions_per_year` and `R_f = risk_free_rate`
come from the `AnalyticsConfig`. `Y = (d_T − d_0) / 365.25` is the duration in
calendar years (`analytics/curves.py`, `performance.py`).

| Measure | Formula | Defined if |
|---|---|---|
| Total return | `V_T / V_0 − 1` | always |
| Annualised return | `(V_T / V_0)^(1/Y) − 1` | at least `minimum_sessions` sessions (60) and `Y > 0` |
| Annualised volatility | `std(r, ddof = 1) · sqrt(A)` | at least 2 returns |
| Sharpe | `mean(r − r_f) / std(r − r_f, ddof = 1) · sqrt(A)`, with `r_f = (1 + R_f)^(1/A) − 1` | 60 sessions, non-zero standard deviation |
| Drawdown | `D_t = V_t / max_{u ≤ t} V_u − 1`; maximum = `min_t D_t` | always; the **first** minimal trough is kept |
| Turnover | `Σ |q_j · P_f,j| / mean(V)`, purchases and sales counted | `mean(V) > 0` |
| Annual turnover | `turnover / Y` | `Y > 0` |
| Cost in return | `R_gross − R_net` | always |
| Share of gross absorbed | `(R_gross − R_net) / R_gross` | `R_gross > 0` |

- `r_f` is compounded down, not divided by `A`. The book's cash earns
  **nothing**: `R_f` serves only the Sharpe.
- The **gross** book replays the same fills at the market price, without fees.
  It is not another strategy that would have bought more for lack of costs.
  With the same quantities, the cost in return equals the cumulative costs
  divided by the initial capital.
- Selling everything and buying everything back gives a turnover of about 2.
- **Contribution by instrument** (`analytics/contribution.py`): the change in
  the value held plus the cash flows of its transactions. The unexplained
  residual is shown, never allocated.
- An undefined metric is `None` and is displayed "-". It is never 0.

**Benchmark** (`backtest/runner.py`, `value_benchmark`): a unit held without
costs or lots. Wealth is chained over the benchmark's sessions:

```
growth of a session = (shares · C_t + cash received) / C_{t−1}
```

A split multiplies the number of shares. Under `TOTAL_RETURN`, a dividend is
paid on each share at the ex-date and reinvested at that close.

**Measures relative to the benchmark** (`analytics/relative.py`,
`RelativePerformanceStats`). Both curves are first aligned by
`aligned_equity_curves`. The ends may be trimmed, but an **inner** hole on one
side only is refused: otherwise a Monday–Wednesday return would be counted as
a single session. With `r_s,t`, `r_b,t` the simple returns of the strategy and
of the benchmark, `x_t = r_b,t − r_f`, `y_t = r_s,t − r_f` and `n` the number
of returns:

```
β̂          = Σ (x_t − x̄)(y_t − ȳ) / Σ (x_t − x̄)²        (OLS with a constant)
α̂_session  = ȳ − β̂ · x̄
α̂_year     = A · α̂_session                             (a scaling, not a compounded rate)
a_t         = r_s,t − r_b,t                             (active return; r_f cancels out)
active_year = A · ā
TE_year     = sqrt(A) · std(a, ddof = 1)
IR          = active_year / TE_year = sqrt(A) · ā / s_a
R²          = 1 − Σ ε̂_t² / Σ (y_t − ȳ)²
```

| Case | Result |
|---|---|
| fewer than `minimum_sessions` valuations, or fewer than 2 returns | all seven figures `None`, `insufficient_observations` |
| standard deviation of the benchmark's returns ≤ `RETURN_STD_TOLERANCE` (10⁻¹²) | α, β, R² `None`, `zero_benchmark_variance`; the active block is still computed |
| a strategy with a constant return | R² `None`, `zero_strategy_variance`; β ≈ 0 |
| a constant active return | TE = 0.0 exactly, IR `None`, `zero_tracking_error` |
| numerical overflow | `ValueError`, never a silent `NaN` or infinity |

Example by hand (`tests/analytics/test_relative.py`, M01): with
`x = (−2%, −1%, 0, 1%, 2%)` and `y = 0.05% + 1.5 x`, one finds `β = 1.5`,
`α_session = 0.05%` and `α_year = 252 × 0.0005 = 12.6%`. The active return is
also 12.6% because `x̄ = 0`, which is not true in general. One also gets
`TE = 12.55%`, `IR = 1.004` and `R² = 1`.

These three measures do not replace one another, and none replaces the
comparison's `excess return` (difference of total returns) or a difference of
Sharpe ratios. A β close to 1 with a high R² says that the strategy follows the
reference; a negative α says that it earned less than that exposure explains.
No confidence interval is computed yet for α, β or IR: do not speak of a
"significant alpha".

**Paired bootstrap** (`analytics/uncertainty.py`). The returns of the strategy
and of the control are aligned on the same sessions. Blocks of `b` consecutive
sessions are drawn with replacement, **with the same indices for both
series**. The statistic is one of the following two:

- `MEAN_RETURN`: `A · (r̄_a − r̄_b)`, a difference of annualised means, not of
  compounded rates;
- `SHARPE`: `Sharpe_a − Sharpe_b`, with the report's risk-free rate. It does
  not cancel out in general, because each series has its own standard
  deviation.

The interval is given by the empirical quantiles. The conditions are: at least
2 returns, `1 ≤ b ≤ T`, at least 100 draws, a level in `(0, 1)` and an
explicit seed. A statistic undefined in a draw raises `UndefinedStatistic`:
inconvenient draws are not thrown away. The interval does not protect against
choosing the best of many trials.

## 5. Data

**Gap between two sources** (`data/crosscheck.py`):

```
δ(a, b) = |a − b| / max(|a|, |b|)      δ(0, 0) = 0
```

Two missing values give 0, a single one gives `∞`. The field comparator first
ignores missing values: with fewer than two finite values, the field is **not
confirmed**, which is not an agreement. A field whose gap exceeds its
tolerance (`metadata/crosscheck.toml`) is `CONFLICT`, and the reader does not
serve that field.

**Corporate action adjustment** (`data/reader.py`, `adjusted_history`): each
price before the ex-date `e` is multiplied by

```
1 / r               split of ratio r, or spin-off of factor r
1 − D / C_{e−1}     dividend D (ordinary or special), C_{e−1} = the raw close before it
```

The factors of several events multiply. A factor ≤ 0 is refused.
