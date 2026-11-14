# SA16_it2's rule with leverage, on the long history: frozen design

Written 2026-11-14, **after** the unlevered test was read and before any
levered return was computed. Parameters:
[levered_long_history.toml](levered_long_history.toml), on top of
[long_history.toml](long_history.toml).

## Why

The unlevered rule (`sa16_it2_long_history_usd`, `NOT_SUPPORTED`) returned
10.8% a year over 1975-01 to 2018-07, against 12.0% for the growth portfolio
and 11.8% for the Nasdaq Composite, with the same Sharpe ratio (0.45 against
0.42 and 0.43) and about half the maximum drawdown. It takes less risk and
earns less.

**Held at the risk of the growth portfolio, does the rule return more than
the growth portfolio and the Nasdaq?**

## This test is not blind

The same 523 months have been read once. The unlevered Sharpe ratio is known,
and leverage does not change a Sharpe ratio except through the cost of the
loan. So:

- the Sharpe difference cannot become significant: the p-values will stay
  near those of the first test (0.69 and 0.81);
- by SA16's criterion the reading can be `UNCERTAIN` at best, never
  `SUPPORTED_RETROSPECTIVE`;
- what is new is the size of the return and of the drawdown at equal risk,
  and what the loan costs. That is arithmetic on a result already seen, made
  exact, not independent evidence.

This is the second hypothesis read on these months.

## The rule

The weights are the base design's, unchanged. Before each month:

1. on the same 12 monthly log changes, estimate the variance of the growth
   asset and of the weighted book (gold's variance scaled by 1.5 as in the
   weights, the covariance as measured);
2. the leverage is the ratio of the two volatilities, at most 2;
3. the exposures are the weights times the leverage. What they leave of the
   equity is cash; a loan when negative.

The leverage is recomputed each month from data before it. It is not a
constant fitted on the window: the ratio of the two realised volatilities
over the whole window (about 1.5) is known from the first test and is
deliberately not used.

Cash earns the one-month Treasury bill. A loan pays the bill plus 1.0% a
year. The book is brought back to its target exposures when one is more than
5 points of equity away, at 10 basis points of traded value, as before. The
stressed run doubles both the trading cost and the spread.

## What it does not model

- **Margin calls within a month.** The series are monthly. A levered book
  can be called between two month ends; here it only fails if a whole month
  leaves no equity, and the run stops if one does.
- **How the loan is obtained.** 1% over the bill is a declared figure, near
  what a low-cost broker charges a large account and below what most retail
  accounts pay. Leveraged funds embed their own costs and daily reset; they
  are a different product.
- **Taxes, and gold's own holding cost.**
- Everything the base design already says about the series: gold is a
  monthly average, the Nasdaq has no dividends.

## Books and reading

`SA16_IT2_LEVERED` against `GROWTH_BUY_HOLD` and `NASDAQ_COMPOSITE_PRICE`,
with the unlevered `SA16_IT2_MONTHLY` shown beside them. The criterion, the
bootstrap, the Holm family and the regimes are the base design's.

Also reported: the leverage's mean, range and the share of months at the
cap; the caps of 1.5 and 3 and spreads of 0 and 2% as sensitivities.

## Prediction, written before the run

- Volatility close to the growth portfolio's (about 21 to 23%).
- **Net CAGR within one point of both references**, more likely above than
  below: about 12 to 12.5%.
- Net Sharpe 0.42 to 0.45: the unlevered one less the loan's cost.
- Maximum drawdown between -55% and -65%, shallower than the references'.
- Reading: `UNCERTAIN` against a reference whose CAGR it exceeds,
  `NOT_SUPPORTED` against one it does not. Not `SUPPORTED_RETROSPECTIVE`.
