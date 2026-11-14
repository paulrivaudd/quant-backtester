# SA16_it2 on a long history: frozen design

Written 2026-11-14, before any return, volatility, weight or book was
computed on the series below. Only their identity and coverage had been read.
Every parameter is in [long_history.toml](long_history.toml); this file says
why. Changing either after the first run is a new hypothesis.

## The question

SA16_it2 holds US technology and gold at inverse-volatility weights scaled by
a risk budget of 75% for technology. On 2018-08 to 2026-10, net of costs, it
is ahead of the Nasdaq bought and held, and its registered status is
`UNCERTAIN`. That window is the one it was designed on, and SA15, SA16 and
SA17 were all read on it.

**Does the same rule beat holding the Nasdaq on months it never saw?**

The test window is 1975-01 to 2018-07: 523 months, none of which was looked
at for SA15, SA16 or SA17's executable study. It holds the 1980 gold peak and
the twenty years of falling gold after it, the 1987 crash, the 2000-2002
collapse of technology and 2008.

## What it is not

- **Not SA16_it2 itself.** it2 trades two UCITS funds in euros, weekly, on
  daily closes. This is its rule on monthly research series in US dollars. A
  result here says whether the mechanism held over forty years. It says
  nothing about the funds, the euro, or weekly execution.
- **Not tradable.** No fund tracked these series over the window. Costs are a
  declared rate, not a measurement.
- **Not a search.** One design, one run. The sensitivities are reported and
  the reading is the primary design's whatever they show.

## Series

All are `RESTATED`: retrieved on 2026-11-14, labelled by the month they
describe. [long_history_inputs.json](long_history_inputs.json) records each
file's hash and coverage; the run refuses any other bytes.

| Role | Series | Source | Known limit |
| --- | --- | --- | --- |
| Growth | "BusEq" of the 12 industry portfolios, value-weighted, total return | Ken French data library | SIC codes, not GICS: computers, software and electronic equipment. Not the S&P 500 technology sector QDVE tracks |
| Gold | Monthly average price, USD per troy ounce | World Bank Pink Sheet | **An average, not a month-end price** (below) |
| Nasdaq | Nasdaq Composite, last close of each month | FRED `NASDAQCOM` | **No dividends**: the reference is understated |
| Risk-free | One-month Treasury bill | Ken French factor file | |

Daily gold prices before 2000 are not available from a source this project
can cite: FRED withdrew the London fixings, and the LBMA and Stooq refuse an
automated client. That is why the study is monthly.

**Gold is a monthly average.** The change from one average to the next runs
from mid-month to mid-month. Three consequences, none of them repaired in the
returns:

- it is smoother than a month-end change: about two thirds of the variance
  (Working, 1960). The volatility estimate scales gold's variance back by 1.5
  so the weights are not tilted towards gold by an artefact. The book's own
  volatility and drawdown are still slightly understated;
- gold lags the equity series by about half a month, which understates their
  correlation within a month;
- the rule stays causal on its own series: a decision at the end of month *t*
  reads the averages of months up to *t* and nothing later.

**The Nasdaq has no dividends.** The Composite is a price index. Its yield
was small but not zero, so the Nasdaq reference is too low by that yield and
a comparison with it flatters the candidate. The second reference, the growth
portfolio bought and held, is a total return and has no such bias. A reading
of `SUPPORTED_RETROSPECTIVE` against the Nasdaq alone would not be enough.

## The rule, as a month can carry it

At the end of each month:

1. the volatility of each asset is the annualised sample deviation of its 12
   last monthly log changes, gold's variance scaled by 1.5, each floored at 5%;
2. the target is `w_growth ~ 0.75 / vol_growth`, `w_gold ~ 0.25 / vol_gold`,
   scaled to add up to one;
3. the book is brought back to the target, whole, when a weight is more than
   5 points from it; otherwise the weights drift.

Budget, floor and band are it2's. Two things differ, and both were fixed
before any run:

- **Volatility on 12 months, not 126 days.** Six monthly changes give an
  estimate with a standard error near 30%. Twelve is the shortest window that
  is not mostly noise; 6 and 24 are reported.
- **Monthly decisions, not weekly.** The series are monthly.

## Books

| Book | Role |
| --- | --- |
| `SA16_IT2_MONTHLY` | Candidate |
| `GROWTH_BUY_HOLD` | Reference: the growth portfolio alone |
| `NASDAQ_COMPOSITE_PRICE` | Reference: the Nasdaq Composite, without dividends |
| `C1_CONSTANT_TWO_THIRDS` | it2's control, two thirds growth and one third gold, same band. Descriptive |

Costs: 10 basis points one way on traded value, doubled in a second run. The
first purchase is free for every book.

## Measures and reading

Net of costs, on 1975-01 to 2018-07: CAGR, volatility, Sharpe ratio of
returns in excess of the Treasury bill, maximum drawdown. Gross beside net.
Turnover and the number of trades.

The candidate **beats** a reference when its net CAGR and net Sharpe are both
higher and its maximum drawdown is at most 2 points deeper: SA16's criterion.
Against each reference:

- `NOT_SUPPORTED` if that fails at declared costs;
- `SUPPORTED_RETROSPECTIVE` if it holds at declared and doubled costs and the
  Sharpe difference has a Holm-adjusted p-value below 0.05 (paired stationary
  bootstrap, 10,000 draws, mean block 12 months, seed 20261114, two
  references in the family);
- `UNCERTAIN` otherwise.

Blocks of 6 and 24 months, the two other volatility windows, the uncorrected
gold variance, five regimes and the 2018-08 to 2024-12 months are reported
and decide nothing.

## Prediction, written before the run

Gold returned much less than technology shares over these forty years, and
the rule holds a third or more of the book in it. So:

- net Sharpe above both references and a shallower maximum drawdown;
- **net CAGR below both references**, so the reading is `NOT_SUPPORTED`
  against each: the rule lowers risk, it does not raise return.

If the CAGR is above both, the 2018-2026 result was not an accident of the
window, and the prediction is wrong in the candidate's favour.
