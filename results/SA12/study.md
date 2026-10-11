# SA12 - ARIMA GARCH: retrospective study

Common period 2021-04-01 to 2026-10-09, 1416 sessions, 100,000 EUR, costs of the ETF comparison, quantities fixed at the decision, cash unpaid. A retrospective evaluation with chronological forecasts; a sequential two-stage estimation, not a joint ARIMA-GARCH likelihood.

## Ranking (QUALITY_V1, against ETF_WORLD bought and held)

| book | rank | score | net | net/yr | vol | Sharpe | Sortino | max DD | alpha/yr | beta | IR | costs EUR | turnover/yr | expo |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 50/50 rebalanced | 1 | 74.0% | +103.3% | +13.71% | 14.2% | +0.96 | +1.35 | -22.5% | +0.51% | 1.02 | +0.55 | 736 | 0.18 | 100% |
| EWMA 0.94 control | 2 | 50.7% | +73.4% | +10.48% | 11.2% | +0.93 | +1.29 | -15.4% | +0.39% | 0.78 | -0.58 | 1,519 | 2.15 | 88% |
| SA6 - vol control | 3 | 49.0% | +67.4% | +9.78% | 10.9% | +0.90 | +1.24 | -15.7% | +0.03% | 0.76 | -0.69 | 1,445 | 2.07 | 85% |
| SA10 - ensemble | 4 | 47.8% | +32.1% | +5.16% | 6.0% | +0.86 | +1.18 | -11.8% | -0.12% | 0.41 | -0.92 | 1,986 | 3.05 | 42% |
| SA11 - GARCH vol control | 5 | 45.6% | +66.0% | +9.61% | 11.1% | +0.87 | +1.19 | -16.5% | -0.39% | 0.78 | -0.77 | 3,749 | 5.46 | 87% |
| SA3 - smooth MA | 6 | 45.4% | +57.9% | +8.62% | 11.0% | +0.79 | +1.09 | -21.6% | +0.39% | 0.65 | -0.51 | 680 | 0.98 | 71% |
| D0 - same risk no filter | 7 | 43.4% | +64.1% | +9.38% | 11.1% | +0.85 | +1.17 | -17.8% | -0.46% | 0.77 | -0.76 | 5,788 | 8.34 | 86% |
| SA2 - dual momentum | 8 | 40.7% | +69.2% | +9.99% | 13.1% | +0.78 | +1.07 | -22.8% | -1.03% | 0.88 | -0.48 | 4,629 | 6.78 | 86% |
| SA5 - relative tilt | 9 | 27.0% | +72.8% | +10.42% | 14.2% | +0.76 | +1.05 | -22.9% | -2.40% | 1.03 | -1.33 | 20,517 | 29.23 | 100% |
| D1 - ARIMA EWMA | 10 | 0.0% | -2.5% | -0.45% | 2.1% | -0.20 | -0.24 | -7.3% | -0.77% | 0.03 | -0.98 | 4,126 | 7.40 | 4% |
| D2 - constant mean GARCH | 10 | 0.0% | +0.0% | +0.00% | 0.0% | n/a | n/a | 0.0% | +0.00% | 0.00 | -0.93 | 0 | 0.00 | 0% |
| SA1 - std MA20 | 10 | 0.0% | +20.5% | +3.43% | 8.9% | +0.42 | +0.58 | -18.9% | -1.61% | 0.41 | -0.86 | 15,730 | 25.53 | 66% |
| SA12 - ARIMA GARCH | 10 | 0.0% | -1.7% | -0.31% | 2.1% | -0.14 | -0.17 | -7.0% | -0.63% | 0.03 | -0.97 | 4,022 | 7.20 | 4% |
| SA4 - pullback | 10 | 0.0% | +4.4% | +0.79% | 1.9% | +0.41 | +0.59 | -3.4% | +0.18% | 0.05 | -0.91 | 4,572 | 8.02 | 4% |
| SA9 - VIX relief | 10 | 0.0% | -0.7% | -0.13% | 2.3% | -0.04 | -0.06 | -8.0% | -0.71% | 0.05 | -0.97 | 2,041 | 3.78 | 4% |
| buy & hold World | n/a | n/a | +94.8% | +12.83% | 13.8% | +0.93 | +1.30 | -21.6% | n/a | n/a | n/a | 100 | 0.13 | 100% |

Deflated by 14 trials: every catalogued strategy run here, the EWMA control of SA11 and the three controls of SA12; the fund held and the even split are references. These books are strongly correlated and are not independent experiments, and the variants of earlier exercises are not in the register: the ranking is exploratory. D0, D1 and D2 are controls, not candidates.

## The same table with every cost paid x2 (second real run, same policy)

| book | rank | score | net | net/yr | vol | Sharpe | Sortino | max DD | alpha/yr | beta | IR | costs EUR | turnover/yr | expo |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 50/50 rebalanced | 1 | 68.4% | +102.7% | +13.65% | 14.2% | +0.96 | +1.34 | -22.5% | +0.47% | 1.03 | +0.54 | 1,069 | 0.17 | 100% |
| EWMA 0.94 control | 2 | 45.0% | +70.9% | +10.19% | 11.1% | +0.91 | +1.26 | -15.5% | +0.16% | 0.78 | -0.64 | 3,033 | 2.16 | 88% |
| SA6 - vol control | 3 | 43.3% | +65.5% | +9.55% | 10.9% | +0.88 | +1.21 | -15.8% | -0.17% | 0.76 | -0.73 | 2,810 | 2.02 | 85% |
| SA3 - smooth MA | 4 | 40.3% | +56.9% | +8.50% | 11.0% | +0.79 | +1.08 | -21.6% | +0.30% | 0.65 | -0.52 | 1,353 | 0.98 | 71% |
| SA10 - ensemble | 5 | 38.9% | +29.6% | +4.80% | 6.0% | +0.80 | +1.10 | -11.8% | -0.45% | 0.41 | -0.96 | 3,891 | 3.03 | 42% |
| SA11 - GARCH vol control | 6 | 37.2% | +61.3% | +9.04% | 11.1% | +0.82 | +1.13 | -16.6% | -0.88% | 0.78 | -0.89 | 7,306 | 5.42 | 87% |
| D0 - same risk no filter | 7 | 32.1% | +56.3% | +8.43% | 11.1% | +0.77 | +1.06 | -17.8% | -1.31% | 0.77 | -0.95 | 11,260 | 8.33 | 86% |
| SA2 - dual momentum | 8 | 31.0% | +62.4% | +9.17% | 13.1% | +0.72 | +0.99 | -22.8% | -1.74% | 0.88 | -0.61 | 9,013 | 6.77 | 86% |
| D1 - ARIMA EWMA | 9 | 0.0% | -6.5% | -1.21% | 2.2% | -0.53 | -0.63 | -9.9% | -1.53% | 0.03 | -1.03 | 8,079 | 7.28 | 4% |
| D2 - constant mean GARCH | 9 | 0.0% | +0.0% | +0.00% | 0.0% | n/a | n/a | 0.0% | +0.00% | 0.00 | -0.93 | 0 | 0.00 | 0% |
| SA1 - std MA20 | 9 | 0.0% | +4.4% | +0.78% | 8.9% | +0.13 | +0.18 | -20.9% | -4.16% | 0.42 | -1.10 | 29,241 | 25.47 | 66% |
| SA12 - ARIMA GARCH | 9 | 0.0% | -5.7% | -1.06% | 2.2% | -0.47 | -0.56 | -9.5% | -1.36% | 0.03 | -1.02 | 7,880 | 7.10 | 4% |
| SA4 - pullback | 9 | 0.0% | -0.2% | -0.03% | 1.9% | -0.00 | -0.01 | -4.0% | -0.63% | 0.05 | -0.97 | 8,950 | 8.01 | 4% |
| SA5 - relative tilt | 9 | 0.0% | +46.4% | +7.14% | 14.2% | +0.55 | +0.76 | -23.3% | -5.34% | 1.03 | -3.14 | 37,617 | 29.36 | 100% |
| SA9 - VIX relief | 9 | 0.0% | -2.8% | -0.51% | 2.3% | -0.21 | -0.29 | -9.3% | -1.09% | 0.05 | -1.00 | 4,040 | 3.79 | 4% |
| buy & hold World | n/a | n/a | +94.3% | +12.79% | 13.8% | +0.93 | +1.30 | -21.6% | n/a | n/a | n/a | 199 | 0.13 | 100% |

The entry threshold of SA12 stays at 20 bp in this run: changing it too would test another strategy.

## Operational quality of the joint forecast

- decisions: 1416; windows of opens served: 1416; usable joint forecasts: 1415 (99.93%);
- means accepted: 1415; variance fits attempted: 1415, GARCH accepted 1415, EWMA fallbacks 0 (0.00%);
- failures by stage and code: {'ARIMA:ARIMA_NOT_CONVERGED': 1};
- forecast pairs with a known target: 1413 of 1416 origins; left out: {'no_forecast': 1, 'target_pending': 2, 'target_missing': 0}.

## Forecast of the mean (open to open, two steps ahead)

| forecast | pairs | MSE | MAE | bias | corr. | sign | always up | balanced | forecasts > 0 |
|---|---|---|---|---|---|---|---|---|---|
| ARIMA mu_h2 | 1413 | 9.2497e-05 | 0.00648 | +0.00000 | +0.018 | 56.1% | 56.7% | 50.4% | 1309 |
| zero | 1413 | 9.2133e-05 | 0.00649 | -0.00047 | n/a | 43.3% | 56.7% | 50.0% | 0 |
| mean of the window | 1413 | 9.2002e-05 | 0.00644 | -0.00000 | -0.036 | 56.7% | 56.7% | 50.0% | 1413 |

The sign is scored on the realisations that are not exactly zero; a forecast of zero counts as 'not up'. A share of right signs is to be read against 'always up', which only measures the drift of the fund.

Entry signals: the forecast cleared 20 bp on 31 of 1413 origins (2.19%) and was positive on 1309 (92.6%). Mean realised return after an entry signal: +0.0456% (all origins: +0.0473%).

## Joint forecast of the mean and the variance

| book | pairs | loss | mean e2/v | std z | kurtosis z | autocorr. z | autocorr. z2 | floored |
|---|---|---|---|---|---|---|---|---|
| SA12 - ARIMA GARCH | 1413 | -8.4848 | 1.088 | 1.044 | 11.14 | -0.020 | +0.242 | 0 |
| D1 - ARIMA EWMA | 1413 | -8.4737 | 1.173 | 1.083 | 8.93 | -0.036 | +0.223 | 0 |
| D2 - constant mean GARCH | 1361 | -8.4994 | 1.078 | 1.038 | 11.19 | -0.026 | +0.250 | 0 |

Loss = log(v) + e2/v with e the error around the forecast mean; lower is better. SA12 and D1 share their mean, so their difference compares variances; D2 has another mean, so its loss is a joint one.

| comparison | pairs | mean difference | 95% low | 95% high | excludes zero |
|---|---|---|---|---|---|
| SA12 - D1 (variance, same mean) | 1413 | -1.111e-02 | -6.458e-02 | +4.517e-02 | False |
| SA12 - D2 (joint mean and variance) | 1360 | +8.573e-03 | -6.003e-04 | +1.738e-02 | False |
| ARIMA - zero (squared error of the mean) | 1413 | +3.648e-07 | -5.027e-07 | +1.202e-06 | False |
| ARIMA - mean of the window (squared error of the mean) | 1413 | +4.949e-07 | -3.690e-07 | +1.288e-06 | False |

Paired differences on shared origins, negative when the first is the better one; moving-block bootstrap, blocks of 20, 5000 draws, seed 20261010.

## SA12 against its controls and the references

| costs vs control | Sharpe SA12 | Sharpe control | difference | 95% low | 95% high | net SA12 | net control | max DD SA12 | max DD control |
|---|---|---|---|---|---|---|---|---|---|
| x1 vs D0 - same risk no filter | -0.136 | +0.852 | -0.987 | -2.101 | +0.252 | -1.72% | +64.07% | -6.99% | -17.77% |
| x1 vs D1 - ARIMA EWMA | -0.136 | -0.196 | +0.061 | -0.037 | +0.170 | -1.72% | -2.46% | -6.99% | -7.32% |
| x1 vs D2 - constant mean GARCH | -0.136 | n/a | n/a | n/a | n/a | -1.72% | +0.00% | -6.99% | 0.00% |
| x1 vs SA11 - GARCH vol control | -0.136 | +0.866 | -1.001 | -2.094 | +0.223 | -1.72% | +65.98% | -6.99% | -16.50% |
| x1 vs SA6 - vol control | -0.136 | +0.899 | -1.034 | -2.087 | +0.161 | -1.72% | +67.43% | -6.99% | -15.72% |
| x1 vs EWMA 0.94 control | -0.136 | +0.934 | -1.070 | -2.142 | +0.138 | -1.72% | +73.37% | -6.99% | -15.45% |
| x1 vs buy & hold World | -0.136 | +0.930 | -1.066 | -2.170 | +0.143 | -1.72% | +94.79% | -6.99% | -21.64% |
| x2 vs D0 - same risk no filter | -0.468 | +0.774 | -1.241 | -2.335 | -0.032 | -5.70% | +56.33% | -9.46% | -17.84% |
| x2 vs D1 - ARIMA EWMA | -0.468 | -0.531 | +0.063 | -0.038 | +0.180 | -5.70% | -6.52% | -9.46% | -9.94% |
| x2 vs D2 - constant mean GARCH | -0.468 | n/a | n/a | n/a | n/a | -5.70% | +0.00% | -9.46% | 0.00% |
| x2 vs SA11 - GARCH vol control | -0.468 | +0.820 | -1.288 | -2.359 | -0.093 | -5.70% | +61.30% | -9.46% | -16.59% |
| x2 vs SA6 - vol control | -0.468 | +0.880 | -1.347 | -2.376 | -0.176 | -5.70% | +65.50% | -9.46% | -15.78% |
| x2 vs EWMA 0.94 control | -0.468 | +0.912 | -1.380 | -2.423 | -0.193 | -5.70% | +70.88% | -9.46% | -15.51% |
| x2 vs buy & hold World | -0.468 | +0.929 | -1.397 | -2.483 | -0.211 | -5.70% | +94.34% | -9.46% | -21.61% |

Position episodes of SA12: 29 (29 completed), 10 with a net gain; mean net return per episode -0.05%.

## Status of the registered hypothesis (`sa12_arima_garch`): the filter against D0

**INSUFFICIENT_EVIDENCE.**
- 29 completed position episodes, under 30

The status answers one question - does the direction filter improve the same risk sizing without it - under the criteria written before the run. It says nothing wider: `NOT_SUPPORTED` is not 'ARIMA-GARCH never works', and `SUPPORTED_RETROSPECTIVE` would not be 'ready to trade'. Whether GARCH adds anything is read apart, on the rows against D1 above and on the difference of losses: a result against D0 does not justify GARCH if ARIMA-EWMA does as well.

## Limits

- The mean and the variance are estimated in two stages; the two-step variance is a plug-in that ignores the uncertainty of the parameters.
- The forecasts are of open-to-open log returns; the books are valued at the close.
- The store is not a set of provider vintages.
- A prospective observation starts at the first XPAR session after this code is available, with this configuration frozen; it does not exist yet.

## Timings

- every run at costs x1: 635 s
- every run at costs x2: 635 s
- signals of every book recomputed for the exports: 421 s
