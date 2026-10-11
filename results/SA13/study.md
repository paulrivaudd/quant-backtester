# SA13 - Signatures Neurons: retrospective study

Test period 2023-01-02 to 2026-10-09, 964 sessions, one continuous book of 100,000 EUR, costs of the ETF comparison, quantities fixed at the decision, cash unpaid. One model per variant and per month, calibrated on what was known at the evening of the last session of the month before and frozen for the month. A retrospective evaluation with a sequential re-estimation: the history had been looked at before.

## Ranking on the test period (QUALITY_V1, against ETF_WORLD bought and held)

| book | rank | score | net | net/yr | vol | Sharpe | Sortino | max DD | alpha/yr | beta | IR | costs EUR | turnover/yr | expo |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 50/50 rebalanced | 1 | 74.1% | +92.0% | +18.91% | 13.2% | +1.36 | +1.97 | -22.5% | +0.26% | 1.03 | +0.55 | 475 | 0.24 | 100% |
| SA10 - ensemble | 2 | 47.5% | +29.8% | +7.16% | 5.8% | +1.21 | +1.69 | -11.7% | -0.45% | 0.43 | -1.37 | 1,235 | 2.76 | 44% |
| C0 - same risk no filter | 3 | 47.4% | +62.1% | +13.68% | 10.6% | +1.25 | +1.77 | -15.7% | -0.49% | 0.80 | -0.99 | 924 | 1.88 | 89% |
| SA6 - vol control | 3 | 47.4% | +62.1% | +13.68% | 10.6% | +1.25 | +1.77 | -15.7% | -0.49% | 0.80 | -0.99 | 924 | 1.88 | 89% |
| SA11 - GARCH vol control | 4 | 47.1% | +65.5% | +14.31% | 10.9% | +1.27 | +1.80 | -16.5% | -0.40% | 0.83 | -0.94 | 1,896 | 3.83 | 92% |
| SA2 - dual momentum | 5 | 44.9% | +69.4% | +15.01% | 12.2% | +1.19 | +1.68 | -22.8% | -0.75% | 0.89 | -0.53 | 3,080 | 6.30 | 88% |
| SA9 - VIX relief | 6 | 39.9% | +6.0% | +1.57% | 2.0% | +0.77 | +1.50 | -3.2% | +0.91% | 0.04 | -1.26 | 616 | 1.58 | 2% |
| C7 - Ridge context SP500 | 7 | 37.6% | +17.9% | +4.46% | 5.8% | +0.78 | +1.07 | -13.9% | -0.63% | 0.30 | -1.28 | 1,337 | 3.14 | 19% |
| SA3 - smooth MA | 8 | 33.7% | +46.6% | +10.69% | 11.1% | +0.95 | +1.32 | -21.6% | -2.75% | 0.78 | -1.12 | 366 | 0.79 | 79% |
| C1 - Ridge logsig3 | 9 | 31.9% | +11.2% | +2.87% | 5.1% | +0.57 | +0.79 | -10.7% | -1.29% | 0.25 | -1.37 | 914 | 2.17 | 16% |
| SA5 - relative tilt | 10 | 29.8% | +72.6% | +15.59% | 13.2% | +1.15 | +1.65 | -22.9% | -2.54% | 1.03 | -1.34 | 14,635 | 28.76 | 100% |
| C4 - NAM classical | 11 | 18.9% | +14.1% | +3.55% | 7.8% | +0.48 | +0.65 | -23.0% | -3.74% | 0.44 | -1.49 | 1,291 | 3.01 | 44% |
| C2 - NAM logsig2 | 12 | 0.0% | -3.8% | -1.01% | 3.3% | -0.29 | -0.34 | -9.0% | -3.24% | 0.13 | -1.59 | 172 | 0.46 | 3% |
| C3 - NAM no volume | 12 | 0.0% | -3.5% | -0.93% | 7.4% | -0.09 | -0.11 | -15.7% | -7.84% | 0.42 | -1.98 | 1,534 | 4.12 | 31% |
| C5 - Ridge raw trajectory | 12 | 0.0% | -1.2% | -0.32% | 6.4% | -0.02 | -0.02 | -10.6% | -5.08% | 0.29 | -1.65 | 29,410 | 75.12 | 31% |
| C6 - NAM context SP500 | 12 | 0.0% | -2.5% | -0.67% | 5.7% | -0.09 | -0.12 | -15.1% | -4.93% | 0.26 | -1.68 | 2,449 | 6.48 | 24% |
| SA1 - std MA20 | 12 | 0.0% | +21.1% | +5.22% | 8.6% | +0.62 | +0.90 | -10.1% | -2.42% | 0.46 | -1.25 | 11,112 | 25.41 | 71% |
| SA12 - ARIMA GARCH | 12 | 0.0% | -1.7% | -0.46% | 2.6% | -0.16 | -0.20 | -7.0% | -1.21% | 0.05 | -1.42 | 4,022 | 10.61 | 6% |
| SA13 - Signatures Neurons | 12 | 0.0% | -3.5% | -0.95% | 6.8% | -0.10 | -0.13 | -18.6% | -6.89% | 0.36 | -1.87 | 1,579 | 4.24 | 23% |
| SA4 - pullback | 12 | 0.0% | +4.0% | +1.06% | 2.0% | +0.54 | +0.80 | -3.4% | +0.12% | 0.05 | -1.33 | 3,376 | 8.71 | 4% |
| buy & hold World | n/a | n/a | +86.7% | +18.03% | 12.7% | +1.35 | +1.94 | -21.6% | n/a | n/a | n/a | 99 | 0.19 | 99% |

Deflated by 19 trials: every catalogued strategy re-run on this period, SA13 and its eight controls; the fund held and the even split are references. These books are strongly correlated and are not independent experiments, and the variants of earlier exercises are not in the register: the ranking is exploratory and a rank is not a probability of success. C0 to C7 are controls, not candidates. The scores of earlier studies were measured from an older date and are not comparable with these.

## The same table with every cost paid x2 (second real run, same models)

| book | rank | score | net | net/yr | vol | Sharpe | Sortino | max DD | alpha/yr | beta | IR | costs EUR | turnover/yr | expo |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 50/50 rebalanced | 1 | 68.3% | +91.5% | +18.83% | 13.2% | +1.36 | +1.96 | -22.5% | +0.22% | 1.03 | +0.51 | 785 | 0.23 | 100% |
| C0 - same risk no filter | 2 | 42.0% | +61.1% | +13.49% | 10.6% | +1.23 | +1.74 | -15.8% | -0.63% | 0.80 | -1.03 | 1,833 | 1.87 | 89% |
| SA6 - vol control | 2 | 42.0% | +61.1% | +13.49% | 10.6% | +1.23 | +1.74 | -15.8% | -0.63% | 0.80 | -1.03 | 1,833 | 1.87 | 89% |
| SA11 - GARCH vol control | 3 | 40.6% | +63.3% | +13.91% | 10.9% | +1.24 | +1.75 | -16.6% | -0.72% | 0.83 | -1.04 | 3,737 | 3.80 | 92% |
| SA10 - ensemble | 4 | 39.8% | +28.4% | +6.87% | 5.8% | +1.16 | +1.62 | -11.8% | -0.70% | 0.43 | -1.40 | 2,558 | 2.88 | 44% |
| SA2 - dual momentum | 5 | 36.3% | +64.9% | +14.20% | 12.2% | +1.13 | +1.60 | -22.8% | -1.41% | 0.89 | -0.67 | 6,107 | 6.36 | 88% |
| SA3 - smooth MA | 6 | 30.4% | +46.3% | +10.62% | 11.2% | +0.95 | +1.31 | -21.6% | -2.81% | 0.78 | -1.13 | 732 | 0.80 | 79% |
| C7 - Ridge context SP500 | 7 | 27.6% | +16.6% | +4.15% | 5.8% | +0.72 | +1.00 | -14.0% | -0.92% | 0.30 | -1.31 | 2,658 | 3.14 | 19% |
| SA9 - VIX relief | 8 | 26.0% | +5.4% | +1.41% | 2.0% | +0.69 | +1.30 | -3.3% | +0.75% | 0.04 | -1.27 | 1,229 | 1.58 | 2% |
| C1 - Ridge logsig3 | 9 | 22.5% | +10.4% | +2.66% | 5.1% | +0.53 | +0.73 | -10.9% | -1.48% | 0.25 | -1.38 | 1,802 | 2.15 | 16% |
| C4 - NAM classical | 10 | 11.8% | +12.7% | +3.21% | 7.8% | +0.44 | +0.59 | -23.5% | -4.06% | 0.44 | -1.52 | 2,569 | 3.01 | 44% |
| C2 - NAM logsig2 | 11 | 0.0% | -3.9% | -1.06% | 3.3% | -0.30 | -0.35 | -9.1% | -3.28% | 0.13 | -1.60 | 343 | 0.46 | 3% |
| C3 - NAM no volume | 11 | 0.0% | -5.1% | -1.37% | 7.4% | -0.15 | -0.19 | -15.8% | -8.27% | 0.42 | -2.03 | 3,050 | 4.13 | 31% |
| C5 - Ridge raw trajectory | 11 | 0.0% | -25.7% | -7.59% | 6.5% | -1.16 | -1.57 | -26.7% | -12.55% | 0.29 | -2.36 | 51,100 | 74.31 | 31% |
| C6 - NAM context SP500 | 11 | 0.0% | -4.9% | -1.32% | 5.7% | -0.20 | -0.26 | -15.6% | -5.58% | 0.26 | -1.74 | 4,831 | 6.46 | 24% |
| SA1 - std MA20 | 11 | 0.0% | +10.0% | +2.55% | 8.7% | +0.33 | +0.47 | -12.7% | -4.95% | 0.46 | -1.51 | 21,155 | 25.27 | 71% |
| SA12 - ARIMA GARCH | 11 | 0.0% | -5.7% | -1.55% | 2.6% | -0.57 | -0.68 | -9.5% | -2.29% | 0.05 | -1.51 | 7,880 | 10.48 | 6% |
| SA13 - Signatures Neurons | 11 | 0.0% | -5.1% | -1.38% | 6.8% | -0.17 | -0.21 | -19.0% | -7.31% | 0.36 | -1.91 | 3,139 | 4.24 | 23% |
| SA4 - pullback | 11 | 0.0% | +0.6% | +0.17% | 2.0% | +0.09 | +0.13 | -3.7% | -0.76% | 0.05 | -1.40 | 6,654 | 8.71 | 4% |
| SA5 - relative tilt | 11 | 0.0% | +54.5% | +12.24% | 13.2% | +0.93 | +1.32 | -23.3% | -5.41% | 1.03 | -3.22 | 27,561 | 28.77 | 100% |
| buy & hold World | n/a | n/a | +86.6% | +18.01% | 12.7% | +1.35 | +1.94 | -21.6% | n/a | n/a | n/a | 199 | 0.19 | 100% |

## Coverage: months with a model, decisions with a usable forecast

| book | months | with a model | decisions | usable | share | unusable, by reason |
|---|---|---|---|---|---|---|
| SA13 - Signatures Neurons | 46 | 46 | 964 | 964 | 100.00% | {} |
| C1 - Ridge logsig3 | 46 | 46 | 964 | 964 | 100.00% | {} |
| C2 - NAM logsig2 | 46 | 46 | 964 | 964 | 100.00% | {} |
| C3 - NAM no volume | 46 | 46 | 964 | 964 | 100.00% | {} |
| C4 - NAM classical | 46 | 46 | 964 | 964 | 100.00% | {} |
| C5 - Ridge raw trajectory | 46 | 46 | 964 | 964 | 100.00% | {} |
| C6 - NAM context SP500 | 46 | 46 | 964 | 964 | 100.00% | {} |
| C7 - Ridge context SP500 | 46 | 46 | 964 | 964 | 100.00% | {} |

A month without a model and a day without a signal are days in cash that stay in the results of the book.

## The monthly calibrations

| variant_id | model | features | models | training examples | validation examples | mean selected epoch | selected at the cap |
|---|---|---|---|---|---|---|---|
| sa13_nam_logsig3 | NEURAL_ADDITIVE | 13 | 46 | 1004 | 124 | 206 | 22 |
| research_sa13_ridge_logsig3 | RIDGE | 13 | 46 | 1004 | 124 | n/a | n/a |
| research_sa13_nam_logsig2 | NEURAL_ADDITIVE | 5 | 46 | 1004 | 124 | 64 | 1 |
| research_sa13_nam_no_volume | NEURAL_ADDITIVE | 13 | 46 | 1004 | 124 | 138 | 11 |
| research_sa13_nam_classical | NEURAL_ADDITIVE | 9 | 46 | 1004 | 124 | 97 | 6 |
| research_sa13_ridge_raw_trajectory | RIDGE | 120 | 46 | 1004 | 124 | n/a | n/a |
| research_sa13_nam_context_sp500 | NEURAL_ADDITIVE | 26 | 46 | 1004 | 124 | 182 | 18 |
| research_sa13_ridge_context_sp500 | RIDGE | 26 | 46 | 1004 | 124 | n/a | n/a |

`selected at the cap` counts the additive models whose selected epoch is the last one allowed: their validation loss was still improving when the fit stopped. The cap was frozen before the first fit; raising it after reading this would be another variant.

## Forecasts out of training (next open to the open after)

| book | pairs | MSE | MSE zero | MSE train mean | R2 OOS | MAE | bias | corr. | sign | always up | balanced | forecasts > 0 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SA13 - Signatures Neurons | 962 | 8.7648e-05 | 8.5767e-05 | 8.5353e-05 | -0.0269 | 0.00595 | -0.00008 | -0.035 | 52.4% | 57.1% | 49.1% | 705 |
| C1 - Ridge logsig3 | 962 | 8.6163e-05 | 8.5767e-05 | 8.5353e-05 | -0.0095 | 0.00588 | -0.00026 | -0.015 | 52.4% | 57.1% | 48.9% | 719 |
| C2 - NAM logsig2 | 962 | 8.5915e-05 | 8.5767e-05 | 8.5353e-05 | -0.0066 | 0.00590 | -0.00048 | +0.027 | 52.9% | 57.1% | 51.1% | 608 |
| C3 - NAM no volume | 962 | 8.6962e-05 | 8.5767e-05 | 8.5353e-05 | -0.0188 | 0.00591 | +0.00005 | -0.023 | 54.2% | 57.1% | 49.7% | 782 |
| C4 - NAM classical | 962 | 8.8062e-05 | 8.5767e-05 | 8.5353e-05 | -0.0317 | 0.00596 | +0.00002 | -0.064 | 52.9% | 57.1% | 48.9% | 754 |
| C5 - Ridge raw trajectory | 962 | 8.8918e-05 | 8.5767e-05 | 8.5353e-05 | -0.0418 | 0.00616 | -0.00018 | +0.056 | 51.1% | 57.1% | 50.2% | 547 |
| C6 - NAM context SP500 | 962 | 9.1452e-05 | 8.5767e-05 | 8.5353e-05 | -0.0715 | 0.00622 | -0.00022 | -0.080 | 50.3% | 57.1% | 48.0% | 637 |
| C7 - Ridge context SP500 | 962 | 8.6129e-05 | 8.5767e-05 | 8.5353e-05 | -0.0091 | 0.00589 | -0.00009 | +0.020 | 52.0% | 57.1% | 49.0% | 679 |

On the forecasts followed by a position actually carried:

| book | pairs | MSE | MSE zero | MSE train mean | R2 OOS | MAE | bias | corr. | sign | always up | balanced | forecasts > 0 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SA13 - Signatures Neurons | 269 | 1.9108e-04 | 1.8442e-04 | 1.8441e-04 | -0.0362 | 0.00787 | +0.00153 | -0.053 | 55.4% | 55.4% | 50.0% | 269 |
| C1 - Ridge logsig3 | 203 | 2.0940e-04 | 2.0840e-04 | 2.0776e-04 | -0.0079 | 0.00798 | +0.00019 | -0.056 | 57.1% | 57.1% | 50.0% | 203 |
| C2 - NAM logsig2 | 59 | 5.8159e-04 | 5.8007e-04 | 5.8010e-04 | -0.0026 | 0.01420 | +0.00227 | +0.079 | 55.9% | 55.9% | 50.0% | 59 |
| C3 - NAM no volume | 346 | 1.6992e-04 | 1.6632e-04 | 1.6641e-04 | -0.0211 | 0.00768 | +0.00127 | -0.011 | 54.9% | 54.9% | 50.0% | 346 |
| C4 - NAM classical | 440 | 1.2241e-04 | 1.1903e-04 | 1.1904e-04 | -0.0283 | 0.00633 | +0.00116 | -0.086 | 54.8% | 54.8% | 50.0% | 440 |
| C5 - Ridge raw trajectory | 343 | 1.1579e-04 | 1.1507e-04 | 1.1398e-04 | -0.0159 | 0.00673 | +0.00166 | +0.095 | 60.3% | 60.3% | 50.0% | 343 |
| C6 - NAM context SP500 | 279 | 1.6151e-04 | 1.4999e-04 | 1.5004e-04 | -0.0764 | 0.00724 | +0.00213 | -0.151 | 51.3% | 51.3% | 50.0% | 279 |
| C7 - Ridge context SP500 | 254 | 1.8063e-04 | 1.8003e-04 | 1.7921e-04 | -0.0079 | 0.00770 | +0.00073 | -0.013 | 59.1% | 59.1% | 50.0% | 254 |

`MSE zero` and `MSE train mean` are the errors, on the same pairs, of a forecast of zero and of the mean label of the training block frozen with each model. `R2 OOS` is one less the ratio of the model's squared error to that of the training mean. The sign is scored on the realisations that are not exactly zero and is to be read against 'always up', which only measures the drift of the fund.

| comparison | pairs | mean difference of squared error | 95% low | 95% high | excludes zero |
|---|---|---|---|---|---|
| SA13 - zero forecast | 962 | +1.881e-06 | -4.360e-07 | +5.886e-06 | False |
| SA13 - training mean | 962 | +2.294e-06 | +1.800e-07 | +5.913e-06 | True |
| SA13 - C1 (the neurons, against Ridge on the same log-signature) | 962 | +1.485e-06 | +1.272e-07 | +3.536e-06 | True |
| SA13 - C2 (order 3, against order 2) | 962 | +1.733e-06 | -2.477e-07 | +4.587e-06 | False |
| SA13 - C3 (the volume, against none) | 962 | +6.859e-07 | -2.890e-07 | +2.265e-06 | False |
| SA13 - C4 (the signature, against classical indicators) | 962 | -4.139e-07 | -2.572e-06 | +1.373e-06 | False |
| SA13 - C5 (the compression, against the raw trajectory) | 962 | -1.271e-06 | -6.224e-06 | +7.281e-06 | False |
| C6 - SA13 (a second process, against the fund alone) | 962 | +3.805e-06 | +1.334e-06 | +6.012e-06 | True |
| C6 - C7 (the neurons on two processes, against Ridge) | 962 | +5.323e-06 | +2.863e-06 | +7.651e-06 | True |

Paired differences on shared origins, negative when the first is the better one; moving-block bootstrap, blocks of 60, 5000 draws, seed 20261010. The windows overlap heavily: a thousand rows are not a thousand independent experiments.

## What a forecast of SA13 is made of (mean contributions, basis points)

| decisions_of | decisions | forecast | reference | displacements | price-volume | price-time | volume-time | order 3 |
|---|---|---|---|---|---|---|---|---|
| every usable decision | 964 | +6.09 | -4.77 | +3.64 | -0.18 | +2.18 | -0.91 | +6.12 |
| decisions that opened a position | 8 | +23.28 | -3.60 | +0.33 | +0.91 | +0.49 | -0.68 | +25.83 |
| decisions that closed a position | 8 | -2.73 | -4.51 | +3.38 | +0.14 | +2.70 | -0.44 | -4.00 |

A forecast is its reference plus its contributions, exactly. `z = 0` is a statistical reference of the features, not a path a market could follow, and a contribution to a forecast is not a contribution to a profit: the economic weight of a group is tested by the variant refitted without it.

## SA13 against its controls and the references

| costs vs control | Sharpe SA13 | Sharpe control | difference | 95% low | 95% high | net SA13 | net control | max DD SA13 | max DD control |
|---|---|---|---|---|---|---|---|---|---|
| x1 vs C0 - same risk no filter | -0.104 | +1.249 | -1.353 | -1.999 | -0.627 | -3.53% | +62.09% | -18.56% | -15.70% |
| x1 vs C1 - Ridge logsig3 | -0.104 | +0.568 | n/a | n/a | n/a | -3.53% | +11.25% | -18.56% | -10.72% |
| x1 vs C2 - NAM logsig2 | -0.104 | -0.285 | n/a | n/a | n/a | -3.53% | -3.75% | -18.56% | -9.02% |
| x1 vs C3 - NAM no volume | -0.104 | -0.088 | -0.016 | -0.525 | +0.464 | -3.53% | -3.47% | -18.56% | -15.68% |
| x1 vs C4 - NAM classical | -0.104 | +0.480 | -0.584 | -1.532 | +0.480 | -3.53% | +14.05% | -18.56% | -22.98% |
| x1 vs C5 - Ridge raw trajectory | -0.104 | -0.017 | -0.088 | -1.331 | +1.155 | -3.53% | -1.19% | -18.56% | -10.56% |
| x1 vs C6 - NAM context SP500 | -0.104 | -0.088 | -0.017 | -0.524 | +0.611 | -3.53% | -2.49% | -18.56% | -15.06% |
| x1 vs C7 - Ridge context SP500 | -0.104 | +0.776 | -0.881 | -2.338 | +0.208 | -3.53% | +17.87% | -18.56% | -13.95% |
| x1 vs SA6 - vol control | -0.104 | +1.249 | -1.353 | -1.999 | -0.627 | -3.53% | +62.09% | -18.56% | -15.70% |
| x1 vs SA11 - GARCH vol control | -0.104 | +1.269 | -1.374 | -2.042 | -0.645 | -3.53% | +65.53% | -18.56% | -16.52% |
| x1 vs SA12 - ARIMA GARCH | -0.104 | -0.164 | n/a | n/a | n/a | -3.53% | -1.72% | -18.56% | -6.99% |
| x1 vs buy & hold World | -0.104 | +1.352 | -1.456 | -2.118 | -0.788 | -3.53% | +86.73% | -18.56% | -21.57% |
| x1 vs 50/50 rebalanced | -0.104 | +1.365 | -1.469 | -2.173 | -0.769 | -3.53% | +92.04% | -18.56% | -22.46% |
| x2 vs C0 - same risk no filter | -0.168 | +1.233 | -1.401 | -2.052 | -0.678 | -5.11% | +61.08% | -18.98% | -15.77% |
| x2 vs C1 - Ridge logsig3 | -0.168 | +0.528 | n/a | n/a | n/a | -5.11% | +10.40% | -18.98% | -10.88% |
| x2 vs C2 - NAM logsig2 | -0.168 | -0.298 | n/a | n/a | n/a | -5.11% | -3.92% | -18.98% | -9.06% |
| x2 vs C3 - NAM no volume | -0.168 | -0.147 | -0.021 | -0.517 | +0.456 | -5.11% | -5.07% | -18.98% | -15.78% |
| x2 vs C4 - NAM classical | -0.168 | +0.438 | -0.606 | -1.556 | +0.463 | -5.11% | +12.66% | -18.98% | -23.49% |
| x2 vs C5 - Ridge raw trajectory | -0.168 | -1.163 | +0.996 | -0.376 | +2.349 | -5.11% | -25.72% | -18.98% | -26.74% |
| x2 vs C6 - NAM context SP500 | -0.168 | -0.202 | +0.034 | -0.469 | +0.665 | -5.11% | -4.90% | -18.98% | -15.64% |
| x2 vs C7 - Ridge context SP500 | -0.168 | +0.725 | -0.892 | -2.313 | +0.183 | -5.11% | +16.56% | -18.98% | -13.99% |
| x2 vs SA6 - vol control | -0.168 | +1.233 | -1.401 | -2.052 | -0.678 | -5.11% | +61.08% | -18.98% | -15.77% |
| x2 vs SA11 - GARCH vol control | -0.168 | +1.237 | -1.405 | -2.082 | -0.672 | -5.11% | +63.31% | -18.98% | -16.59% |
| x2 vs SA12 - ARIMA GARCH | -0.168 | -0.567 | n/a | n/a | n/a | -5.11% | -5.70% | -18.98% | -9.46% |
| x2 vs buy & hold World | -0.168 | +1.350 | -1.518 | -2.185 | -0.849 | -5.11% | +86.63% | -18.98% | -21.58% |
| x2 vs 50/50 rebalanced | -0.168 | +1.359 | -1.527 | -2.238 | -0.825 | -5.11% | +91.52% | -18.98% | -22.47% |

The main difference, SA13 less C0, at the three announced block lengths:

| costs, block | difference | 95% low | 95% high | bootstrap |
|---|---|---|---|---|
| x1, blocks of 20 | -1.353 | -2.028 | -0.543 | ok |
| x1, blocks of 60 | -1.353 | -1.999 | -0.627 | ok |
| x1, blocks of 120 | -1.353 | -1.987 | -0.673 | ok |
| x2, blocks of 20 | -1.401 | -2.074 | -0.602 | ok |
| x2, blocks of 60 | -1.401 | -2.052 | -0.678 | ok |
| x2, blocks of 120 | -1.401 | -2.034 | -0.714 | ok |

Position episodes of SA13: 8 (8 completed), 5 with a net gain; mean net return per episode -0.35%.

## Status of the registered hypothesis (`sa13_signatures_neurons`): SA13 against C0

**INSUFFICIENT_EVIDENCE.**
- 8 completed position episodes, under 30

The status answers one question - does the direction filter learnt from the log-signature improve the same risk sizing without it - under the criteria written before the first fit. The intervals are conditional on the path already produced: they carry neither the uncertainty of the re-estimations nor the selection of ideas.

Concluded apart, on the paired differences of squared error above:

- neurons: NOT_LOWER
- order_3: NOT_LOWER
- volume: NOT_LOWER
- signature_vs_classical: LOWER_MSE_NOT_TOLD_FROM_ZERO
- compression_vs_raw: LOWER_MSE_NOT_TOLD_FROM_ZERO
- second_process: NOT_LOWER

A favourable economic result would not show that the signatures or the neurons were needed; an unfavourable one does not show that a log-signature carries no information.

## Limits

- The 12 hours between a model's cutoff and its availability are an assumption of the historical run.
- The realised volatilities of the sizing are a proxy on closes, not a forecast of the variance of the label.
- The models of the comparison differ in capacity: 157 parameters for SA13, 61 at order 2, 109 on the classical indicators, 313 on two processes. A comparison does not isolate one cause.
- The store is not a set of provider vintages.
- A prospective observation starts at the first XPAR session at which the artifacts really exist, with this configuration frozen; it does not exist yet.

## Timings

- features of every origin, six representations: 58 s
- monthly calibrations of the eight variants: 163 s
- every run at costs x1: 318 s
- every run at costs x2: 314 s
- signals of every book recomputed for the exports: 207 s
