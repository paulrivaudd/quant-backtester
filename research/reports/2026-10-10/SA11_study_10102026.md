# SA11 - GARCH vol control: retrospective study

Common period 2021-04-01 to 2026-10-09, 1416 sessions, 100,000 EUR, costs of the ETF comparison, quantities fixed at the decision, cash unpaid. A retrospective evaluation with chronological forecasts: the history was looked at before, so this is not an untouched sample.

## Ranking (QUALITY_V1, against ETF_WORLD bought and held)

| book | rank | score | market | signif. | risk | robust. | implem. | net | net/yr | vol | Sharpe | max DD | alpha/yr | beta | IR | costs EUR | turnover/yr | expo |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 50/50 rebalanced | 1 | 77.9% | 0.78 | 0.86 | 0.46 | 0.91 | 0.98 | +103.3% | +13.71% | 14.2% | +0.96 | -22.5% | +0.51% | 1.02 | +0.55 | 736 | 0.18 | 100% |
| EWMA 0.94 control | 2 | 53.6% | 0.27 | 0.85 | 0.79 | 0.48 | 0.93 | +73.4% | +10.48% | 11.2% | +0.93 | -15.4% | +0.39% | 0.78 | -0.58 | 1,519 | 2.15 | 88% |
| SA6 - vol control | 3 | 52.0% | 0.25 | 0.83 | 0.77 | 0.48 | 0.93 | +67.4% | +9.78% | 10.9% | +0.90 | -15.7% | +0.03% | 0.76 | -0.69 | 1,445 | 2.07 | 85% |
| SA10 - ensemble | 4 | 51.1% | 0.24 | 0.80 | 0.96 | 0.44 | 0.81 | +32.1% | +5.16% | 6.0% | +0.86 | -11.8% | -0.12% | 0.41 | -0.92 | 1,986 | 3.05 | 42% |
| SA3 - smooth MA | 5 | 49.0% | 0.27 | 0.76 | 0.50 | 0.49 | 0.96 | +57.9% | +8.62% | 11.0% | +0.79 | -21.6% | +0.39% | 0.65 | -0.51 | 680 | 0.98 | 71% |
| SA11 - GARCH vol control | 6 | 48.6% | 0.23 | 0.81 | 0.74 | 0.44 | 0.82 | +66.0% | +9.61% | 11.1% | +0.87 | -16.5% | -0.39% | 0.78 | -0.77 | 3,749 | 5.46 | 87% |
| SA2 - dual momentum | 7 | 44.1% | 0.21 | 0.75 | 0.45 | 0.52 | 0.79 | +69.2% | +9.99% | 13.1% | +0.78 | -22.8% | -1.03% | 0.88 | -0.48 | 4,629 | 6.78 | 86% |
| SA5 - relative tilt | 8 | 29.4% | 0.13 | 0.73 | 0.44 | 0.25 | 0.27 | +72.8% | +10.42% | 14.2% | +0.76 | -22.9% | -2.40% | 1.03 | -1.33 | 20,517 | 29.23 | 100% |
| SA1 - std MA20 | 9 | 0.0% | 0.17 | 0.43 | 0.62 | 0.00 | 0.00 | +20.5% | +3.43% | 8.9% | +0.42 | -18.9% | -1.61% | 0.41 | -0.86 | 15,730 | 25.53 | 66% |
| SA4 - pullback | 9 | 0.0% | 0.26 | 0.42 | 1.00 | 0.00 | 0.00 | +4.4% | +0.79% | 1.9% | +0.41 | -3.4% | +0.18% | 0.05 | -0.91 | 4,572 | 8.02 | 4% |
| SA9 - VIX relief | 9 | 0.0% | 0.21 | 0.10 | 1.00 | 0.00 | 0.00 | -0.7% | -0.13% | 2.3% | -0.04 | -8.0% | -0.71% | 0.05 | -0.97 | 2,041 | 3.78 | 4% |
| buy & hold World | n/a | n/a | n/a | n/a | n/a | n/a | n/a | +94.8% | +12.83% | 13.8% | +0.93 | -21.6% | n/a | n/a | n/a | 100 | 0.13 | 100% |

Deflated by 10 trials (dispersion of per-session Sharpe ratios 0.01959). The register holds the configurations run here and not the variants of earlier exercises: the ranking is exploratory. The score is a composite index, not a probability of making money. A book without a score has no rank.

## The same table with every cost paid x2 (second real run)

| book | rank | score | market | signif. | risk | robust. | implem. | net | net/yr | vol | Sharpe | max DD | alpha/yr | beta | IR | costs EUR | turnover/yr | expo |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 50/50 rebalanced | 1 | 75.3% | 0.77 | 0.77 | 0.46 | 0.91 | 0.97 | +102.7% | +13.65% | 14.2% | +0.96 | -22.5% | +0.47% | 1.03 | +0.54 | 1,069 | 0.17 | 100% |
| EWMA 0.94 control | 2 | 50.0% | 0.26 | 0.73 | 0.78 | 0.46 | 0.86 | +70.9% | +10.19% | 11.1% | +0.91 | -15.5% | +0.16% | 0.78 | -0.64 | 3,033 | 2.16 | 88% |
| SA6 - vol control | 3 | 48.5% | 0.24 | 0.71 | 0.77 | 0.46 | 0.86 | +65.5% | +9.55% | 10.9% | +0.88 | -15.8% | -0.17% | 0.76 | -0.73 | 2,810 | 2.02 | 85% |
| SA3 - smooth MA | 4 | 46.1% | 0.27 | 0.63 | 0.50 | 0.48 | 0.92 | +56.9% | +8.50% | 11.0% | +0.79 | -21.6% | +0.30% | 0.65 | -0.52 | 1,353 | 0.98 | 71% |
| SA10 - ensemble | 5 | 44.4% | 0.23 | 0.64 | 0.95 | 0.37 | 0.61 | +29.6% | +4.80% | 6.0% | +0.80 | -11.8% | -0.45% | 0.41 | -0.96 | 3,891 | 3.03 | 42% |
| SA11 - GARCH vol control | 6 | 42.3% | 0.21 | 0.66 | 0.73 | 0.38 | 0.65 | +61.3% | +9.04% | 11.1% | +0.82 | -16.6% | -0.88% | 0.78 | -0.89 | 7,306 | 5.42 | 87% |
| SA2 - dual momentum | 7 | 36.1% | 0.16 | 0.57 | 0.45 | 0.45 | 0.58 | +62.4% | +9.17% | 13.1% | +0.72 | -22.8% | -1.74% | 0.88 | -0.61 | 9,013 | 6.77 | 86% |
| SA1 - std MA20 | 8 | 0.0% | 0.04 | 0.11 | 0.53 | 0.00 | 0.00 | +4.4% | +0.78% | 8.9% | +0.13 | -20.9% | -4.16% | 0.42 | -1.10 | 29,241 | 25.47 | 66% |
| SA4 - pullback | 8 | 0.0% | 0.22 | 0.06 | 1.00 | 0.00 | 0.00 | -0.2% | -0.03% | 1.9% | -0.00 | -4.0% | -0.63% | 0.05 | -0.97 | 8,950 | 8.01 | 4% |
| SA5 - relative tilt | 8 | 0.0% | 0.00 | 0.41 | 0.42 | 0.00 | 0.00 | +46.4% | +7.14% | 14.2% | +0.55 | -23.3% | -5.34% | 1.03 | -3.14 | 37,617 | 29.36 | 100% |
| SA9 - VIX relief | 8 | 0.0% | 0.20 | 0.02 | 1.00 | 0.00 | 0.00 | -2.8% | -0.51% | 2.3% | -0.21 | -9.3% | -1.09% | 0.05 | -1.00 | 4,040 | 3.79 | 4% |
| buy & hold World | n/a | n/a | n/a | n/a | n/a | n/a | n/a | +94.3% | +12.79% | 13.8% | +0.93 | -21.6% | n/a | n/a | n/a | 199 | 0.13 | 100% |

## SA11 against its controls

| costs vs control | Sharpe SA11 | Sharpe control | difference | 95% low | 95% high | net return diff. | max DD SA11 | max DD control | bootstrap |
|---|---|---|---|---|---|---|---|---|---|
| x1 vs SA6 - vol control | +0.866 | +0.899 | -0.033 | -0.141 | +0.076 | -1.46% | -16.50% | -15.72% | ok |
| x1 vs EWMA 0.94 control | +0.866 | +0.934 | -0.069 | -0.147 | +0.009 | -7.39% | -16.50% | -15.45% | ok |
| x1 vs buy & hold World | +0.866 | +0.930 | -0.065 | -0.258 | +0.095 | -28.81% | -16.50% | -21.64% | ok |
| x2 vs SA6 - vol control | +0.820 | +0.880 | -0.060 | -0.169 | +0.053 | -4.20% | -16.59% | -15.78% | ok |
| x2 vs EWMA 0.94 control | +0.820 | +0.912 | -0.092 | -0.172 | -0.014 | -9.58% | -16.59% | -15.51% | ok |
| x2 vs buy & hold World | +0.820 | +0.929 | -0.109 | -0.306 | +0.054 | -33.04% | -16.59% | -21.61% | ok |

Paired block bootstrap: blocks of 20 sessions, 5000 draws, seed 20261010, 95% interval. It is conditional on the experiment examined and carries neither the uncertainty of the estimation nor that of having chosen the rule.

## Forecast of risk (ex post, close to close)

| scope / forecast | pairs | QLIKE | variance MSE | mean r2/q | std z | kurtosis z | |z|>2 | floored |
|---|---|---|---|---|---|---|---|---|
| own origins / GARCH accepted | 1415 | -8.6225 | 3.129e-08 | 0.970 | 0.984 | 5.70 | 5.6% | 0 |
| own origins / SA11 policy | 1415 | -8.6225 | 3.129e-08 | 0.970 | 0.984 | 5.70 | 5.6% | 0 |
| own origins / EWMA 0.94 | 1415 | -8.6033 | 3.135e-08 | 1.106 | 1.050 | 5.59 | 6.3% | 0 |
| own origins / SA6 estimator | 1415 | -8.5649 | 3.543e-08 | 0.949 | 0.973 | 5.96 | 5.1% | 0 |
| origins of accepted GARCH fits / GARCH accepted | 1415 | -8.6225 | 3.129e-08 | 0.970 | 0.984 | 5.70 | 5.6% | 0 |
| origins of accepted GARCH fits / SA11 policy | 1415 | -8.6225 | 3.129e-08 | 0.970 | 0.984 | 5.70 | 5.6% | 0 |
| origins of accepted GARCH fits / EWMA 0.94 | 1415 | -8.6033 | 3.135e-08 | 1.106 | 1.050 | 5.59 | 6.3% | 0 |
| origins of accepted GARCH fits / SA6 estimator | 1415 | -8.5649 | 3.543e-08 | 0.949 | 0.973 | 5.96 | 5.1% | 0 |

QLIKE = log(q) + r2/q, lower is better; q is floored at 1e-12 for the metric only. One squared daily return is a very noisy proxy of a variance. QLIKE measures the close-to-close forecast, not the profit of an allocation filled at the open. It is a loss, negative here because the variances are far below one; it is not a return.

| difference of mean QLIKE | pairs | mean difference | 95% low | 95% high | excludes zero |
|---|---|---|---|---|---|
| GARCH accepted - EWMA 0.94 | 1415 | -0.0192 | -0.0507 | +0.0092 | False |
| GARCH accepted - SA6 estimator | 1415 | -0.0576 | -0.1085 | -0.0170 | True |
| EWMA 0.94 - SA6 estimator | 1415 | -0.0385 | -0.0755 | -0.0063 | True |

Paired differences of QLIKE on shared origins, negative when the first forecast is the better one; moving-block bootstrap, blocks of 20 origins, 5000 draws, seed 20261010. A lowest mean QLIKE whose interval includes zero is the best one observed, not a demonstrated superiority. The standardised residuals keep fat tails under every forecast (kurtosis above 3).

## Fallback

1416 decisions had a valid window: 1416 used the GARCH fit, 0 the EWMA fallback, 0 had no usable fallback. Fallback share: 0.00%. Reasons: none. Episodes: none.
The share is at or below 5%: no reserve on attributing the results to GARCH.

## Net return by calendar year

| book | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|
| SA1 - std MA20 | +8.0% | -8.0% | +8.5% | +9.0% | +2.6% | -0.0% |
| buy & hold World | +18.4% | -13.7% | +19.6% | +27.1% | +6.6% | +17.7% |
| 50/50 rebalanced | +20.7% | -14.0% | +20.9% | +30.2% | +5.0% | +18.5% |
| SA2 - dual momentum | +21.2% | -17.6% | +9.1% | +30.7% | +0.6% | +18.0% |
| SA3 - smooth MA | +18.4% | -9.1% | +8.6% | +27.1% | -9.6% | +17.6% |
| SA4 - pullback | +1.1% | -0.8% | -0.7% | +5.5% | -2.4% | +1.7% |
| SA5 - relative tilt | +18.2% | -16.9% | +18.1% | +25.9% | +2.4% | +15.6% |
| SA6 - vol control | +14.9% | -11.3% | +16.3% | +20.3% | +1.6% | +15.6% |
| SA9 - VIX relief | -0.8% | -5.6% | +0.0% | +1.7% | +0.9% | +3.3% |
| SA10 - ensemble | +9.6% | -7.4% | +5.5% | +14.8% | -1.7% | +9.2% |
| SA11 - GARCH vol control | +14.2% | -13.2% | +15.6% | +22.5% | +2.5% | +15.3% |
| EWMA 0.94 control | +16.1% | -12.5% | +16.6% | +22.3% | +3.0% | +16.1% |

Sessions of each year inside the period: 2021: 195, 2022: 257, 2023: 255, 2024: 256, 2025: 255, 2026: 198. The first and the last year are partial.

## Decision on the registered hypothesis (`sa11_garch_vol_control`)

**REFUTED.**
- net Sharpe not above SA6 - vol control at costs x1
- maximum drawdown deeper than SA6 - vol control at costs x1
- net Sharpe not above EWMA 0.94 control at costs x1
- maximum drawdown deeper than EWMA 0.94 control at costs x1
- net Sharpe not above SA6 - vol control at costs x2
- maximum drawdown deeper than SA6 - vol control at costs x2
- net Sharpe not above EWMA 0.94 control at costs x2
- maximum drawdown deeper than EWMA 0.94 control at costs x2
- Sharpe difference against SA6 - vol control at costs x1: interval includes zero
- Sharpe difference against EWMA 0.94 control at costs x1: interval includes zero
- Sharpe difference against SA6 - vol control at costs x2: interval includes zero

`REFUTED` is an operational verdict: a criterion of refutation written before the run is met - a net Sharpe ratio not above a control's, or a deeper maximum drawdown. It is not a statistical proof that this configuration is inferior: where an interval of a Sharpe difference includes zero, the two books are not told apart at that level, and the lines above say where that is the case. Nor does it say anything of GARCH models in general. GARCH did not clearly beat the simple rules after costs, so the simple rules are kept; a better likelihood or a lower QLIKE alone does not justify the strategy.

## Limits

- The store is not a set of provider vintages: restated closes are what a decision read, as far as the store can say.
- The forecast covers close to close and orders are filled at the next open.
- A prospective check starts at the first XPAR session after 2026-10-10 with this configuration frozen; it does not exist yet.
- SA7 and SA8 were not run (instruments not registered). ML1 is reported apart.

## Timings

- every run at costs x1: 143.3 s
- every run at costs x2: 147.5 s
- GARCH calibration alone, one fit per decision: 20.0 s
