# SA18: a trend filter on the growth portfolio, on the long history: frozen design

Written 2026-11-15, before any level, moving average, signal or return of
this rule was computed on the series below. Every parameter is in
[trend_long_history.toml](trend_long_history.toml); this file says why.
Changing either after the first run is a new hypothesis.

## The question

Two tests on 1975-01 to 2018-07 found that mixing technology with gold lowers
risk without raising return, with or without leverage
([long history](../SA16/long_history.md),
[levered](../SA16/levered_long_history.md)). The owner asked for one
different idea to be tested on the same months.

**Does holding the growth portfolio only while it is above its moving
average, and Treasury bills otherwise, beat holding it, and beat the Nasdaq,
net of costs?**

## This test is not blind, and the rule is not new

- **Third hypothesis read on these 523 months.** The buy-and-hold figures of
  both references are known: 12.0% a year with a drawdown of -79.6% for the
  growth portfolio, 11.8% and -75.0% for the Nasdaq Composite. The Holm
  correction below covers the two references of this test, not the three
  hypotheses.
- **The rule is one of the most published timing rules.** The ten-month
  average is Faber's (2007), chosen on data that ends in 2005 and overlaps
  this window; its best-known success, 2008, is also in the window. A good
  result here is replication of a published result on a neighbouring series.
  It is weaker evidence than its p-value says.
- **What is known in advance about the mechanism**: a trend filter is out of
  the market for part of every long decline, so a shallower drawdown than the
  references' is close to certain and proves little. The open question is
  what it costs in return: the months missed after each re-entry.

The ten-month value is taken as published. It was not compared with any
other on these series before this file was written.

## Series

The archive of SA16's long-history tests, unchanged
([long_history_inputs.json](../SA16/long_history_inputs.json)); the run
refuses any other bytes. All are `RESTATED`, labelled by the month they
describe. Gold is not read.

| Role | Series | Known limit |
| --- | --- | --- |
| Growth | "BusEq" of Ken French's 12 industry portfolios, value-weighted, total return | SIC codes: computers, software, electronic equipment. Not a fund |
| Nasdaq | Nasdaq Composite, last close of each month (FRED `NASDAQCOM`) | **No dividends**: the reference is understated |
| Bills | One-month Treasury bill of the French factor file | |

## The rule

The growth portfolio's total-return level is the compounded product of its
monthly returns. At the end of each month *t*:

1. take the level at the end of *t* and the simple average of the last ten
   month-end levels, *t* included;
2. if the level is strictly above the average, hold the growth portfolio over
   month *t+1*; otherwise hold the one-month Treasury bill over *t+1*.

The decision reads months up to *t* and nothing later. The whole book
switches: there is no partial position and no leverage.

**Costs**: 10 basis points of traded value, one way. A switch trades the
whole book once. The position of the first month is taken at no cost, as the
references are bought at no cost. A second run doubles the rate.

**Not modelled**: the decision and the trade happen at the same month-end
close, as in the two earlier tests; taxes on each exit; the spread of a
Treasury bill. No fund tracked the growth series over the window.

## Books

| Book | Role |
| --- | --- |
| `SA18_TREND_FILTER` | Candidate |
| `GROWTH_BUY_HOLD` | Reference: the growth portfolio held throughout |
| `NASDAQ_COMPOSITE_PRICE` | Reference: the Nasdaq Composite, without dividends |

## Measures and reading

Net of costs on 1975-01 to 2018-07: CAGR, volatility, Sharpe ratio of returns
in excess of the bill, maximum drawdown; gross beside net. Number of
switches, share of months in the growth portfolio.

The criterion and the reading are those of the two earlier tests. The
candidate **beats** a reference when its net CAGR and net Sharpe are both
higher and its maximum drawdown is at most 2 points deeper. Against each
reference:

- `NOT_SUPPORTED` if that fails at declared costs;
- `SUPPORTED_RETROSPECTIVE` if it holds at declared and doubled costs and the
  Sharpe difference has a Holm-adjusted p-value below 0.05 (paired stationary
  bootstrap, 10,000 draws, mean block 12 months, seed 20261115, two
  references in the family);
- `UNCERTAIN` otherwise.

As before, a reading of `SUPPORTED_RETROSPECTIVE` against the Nasdaq alone
would not be enough: that reference has no dividends.

## Reported, deciding nothing

- **Earlier months, 1927-07 to 1974-12** (570 months), against the growth
  portfolio alone: the Nasdaq Composite starts in 1971. These are the only
  months of this study that no hypothesis of this project has read on this
  portfolio, and they precede the rule's publication sample. Same measures,
  and the Sharpe difference with its bootstrap interval. If the test window
  and the earlier months disagree, the report says so; the registered reading
  stays the test window's.
- **Later months, 2018-08 to 2026-09**: the window SA15 to SA17 were
  developed on.
- Averages of 6, 8 and 12 months; the signal read on the Nasdaq Composite's
  closes instead of the growth portfolio's level; bootstrap blocks of 6 and
  24 months; the five regimes of the earlier tests.

## Prediction, written before the run

- In the growth portfolio about 65 to 75% of months; 40 to 70 switches.
- Volatility 15 to 18%, against 22.8%.
- **Maximum drawdown between -30% and -50%**, against -79.6% and -75.0%.
- Net Sharpe 0.50 to 0.60, against 0.42 and 0.43; the difference not
  significant (Holm p above 0.05).
- **Net CAGR between 11% and 13.5%**: within about a point of the references
  on either side. This is the part I cannot call. Slightly more likely above
  12.0% than below.
- Reading: `UNCERTAIN` against a reference whose CAGR it exceeds,
  `NOT_SUPPORTED` against one it does not; most likely `UNCERTAIN` against
  both. Not `SUPPORTED_RETROSPECTIVE`.
- Earlier months: the same shape with a smaller advantage; the 1929-1932
  decline is where the filter should help most.
