# Complementary diagnostics — results of 10 October 2026

This document measures what the analyses of this folder listed as "remaining to
be measured", at the request of the independent review of 10 October. It is
written by `scripts/run_review_diagnostics.py`, from the exports of the study and
a few additional runs of the same engine, over the same period
(2021-04-01 → 2026-10-09), with the same capital and the same costs.

**Everything that follows is descriptive.** A constant-target control, whose
target is the weight a rule held on average, is chosen after the fact: it
describes the past of that rule, it is not a parameter that could have been set
in advance, and its realised exposure is not the rule's. An ablation of `SA10`
or another EWMA coefficient is a variant looked at after a backtest. None is a
candidate: retaining one would be a new hypothesis, to be written before its
run, and each would count as a trial in the register that deflates the Sharpe
ratios. The estimates are point estimates unless an interval is mentioned.
Nothing here is an untouched sample.

Version 2 of 10 October 2026, after the independent check made on commit
`ad310bc`. What changed: the close-to-open price gap is measured at given
quantities, on the market price and not on the amount executed; the
"execution" column of the attribution is renamed residual, because it does not
isolate the execution; the closed stays and the stay still open are counted
apart; the correlations of `SA5` keep their first decision and compound their
returns over five sessions; the controls are called "constant-target"; `SA14`
is replayed with its frozen model at doubled costs; a run is compared with the
exports only if it read the same store. Written in English since 2026-10-31,
with the same figures.

Exports of the study: commit `91a2f3776759` (CLEAN), store `b5facce52a6f`. Runs of this document: commit `af1f35d1b241` (CLEAN).

## 1. Result by stay in the market (SA1, SA4, SA9)

| Strategy | Stays | Closed | Open | Closed winners | Closed losers | Winning share (closed) | Mean net | Median net | Worst | Best | Compounded | Avg. length (val.) | Costs EUR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| SA1 - std MA20 | 72 | 71 | 1 | 28 | 43 | 39.4% | +0.31% | -0.28% | -6.14% | +17.48% | +20.45% | 13.1 | 15,730 |
| SA4 - pullback | 71 | 71 | 0 | 47 | 24 | 66.2% | +0.06% | +0.04% | -2.92% | +1.85% | +4.43% | 2.8 | 4,572 |
| SA9 - VIX relief | 21 | 21 | 0 | 9 | 12 | 42.9% | -0.02% | -0.70% | -2.64% | +3.64% | -0.70% | 5.0 | 2,041 |

A stay is a run of valuations in which a position is held. The net result of a **closed** stay runs from the valuation before the entry to the first valuation back in cash: its two fills and their costs are in it. An **open** stay is still running at the last session: it is marked to market at that session, without a final sale or its cost. The winners and the losers are counted on the closed stays only. The mean net, the median, the worst, the best and "Compounded" cover all the stays, the open one included: "Compounded" is their product and gives back the net return of the strategy, since cash earns nothing.

- SA1 - std MA20: a stay still open, entered at the valuation of 2026-09-18, valued +2.96% at 2026-10-09, without a final sale.

### SA9: its 21 stays in 7 groups (convention: 20 valuations)

| First entry | Last exit | Stays | Net | Costs EUR |
|---|---:|---:|---:|---:|
| 2021-12-08 | 2022-02-14 | 5 | -2.07% | 493 |
| 2022-03-17 | 2022-04-12 | 3 | +0.30% | 297 |
| 2022-05-17 | 2022-07-13 | 5 | -2.50% | 484 |
| 2022-10-31 | 2022-11-17 | 2 | -2.22% | 190 |
| 2024-08-12 | 2024-09-03 | 2 | +1.75% | 190 |
| 2025-04-15 | 2025-05-21 | 2 | +0.90% | 190 |
| 2026-04-07 | 2026-04-29 | 2 | +3.30% | 197 |

Two stays separated by 20 valuations or fewer are attached to the same group. It is an automatic grouping by this convention, not the economic identification of as many independent panics; a winning group can count several entries, as a losing group can.

## 2. Signed close-to-open price gap, at given quantities

| Book | Orders | Favourable gaps EUR | Unfavourable gaps EUR | Net gap EUR | As % of the initial capital | Orders excluded (ex-date) |
|---|---:|---:|---:|---:|---:|---:|
| 50/50 rebalanced | 617 | +112 | -1,211 | -1,100 | -1.10% | 0 |
| EWMA 0.94 control | 220 | +3,571 | -6,647 | -3,076 | -3.08% | 0 |
| SA6 - vol control | 180 | +2,985 | -5,487 | -2,503 | -2.50% | 0 |
| SA10 - ensemble | 465 | +4,966 | -5,997 | -1,031 | -1.03% | 0 |
| SA7 - factor blend | 72 | +6,602 | -3,587 | +3,015 | +3.02% | 0 |
| SA3 - smooth MA | 78 | +2,107 | -2,752 | -645 | -0.65% | 0 |
| SA11 - GARCH vol control | 508 | +10,066 | -12,989 | -2,923 | -2.92% | 0 |
| SA2 - dual momentum | 317 | +9,460 | -11,297 | -1,838 | -1.84% | 0 |
| SA5 - relative tilt | 1904 | +44,451 | -47,022 | -2,571 | -2.57% | 0 |
| SA1 - std MA20 | 143 | +28,201 | -42,768 | -14,568 | -14.57% | 0 |
| SA4 - pullback | 237 | +14,660 | -12,358 | +2,303 | +2.30% | 0 |
| SA9 - VIX relief | 42 | +4,528 | -9,472 | -4,944 | -4.94% | 0 |
| SA8 - monetary carry | 9 | +95 | -47 | +47 | +0.05% | 0 |
| buy & hold World | 1 | +0 | -951 | -951 | -0.95% | 0 |

For each order: `-sign x quantity x (open - previous close)`, sign +1 for a purchase, on the market price of the open and not on the price executed: the spread, the slippage and the commission stay in the costs. Positive: the overnight move went the order's way. An order executed on an ex-date is excluded, the two prices not being on the same basis.

It is a **price gap at given quantities**, not the result of another backtest executed at the close: the signal reads that close, so the order could not be executed at it, and another execution price would have changed all the following quantities. It reads neither as a cost paid nor as an exact shortfall.

## 3. SA2 and SA5 against the 50/50 basket of the same two funds

| Strategy | Basket (closes) | Total exposure | Choice between funds | Residual of the approximation at the close weights | Costs | = Net of the strategy | Executed 50/50 basket, net |
|---|---:|---:|---:|---:|---:|---:|---:|
| SA2 - dual momentum | +0.7273 | -0.1397 | +0.0044 | -0.0392 | -0.0270 | +0.5258 | +0.7097 |
| SA5 - relative tilt | +0.7273 | -0.0111 | +0.0027 | -0.0596 | -0.1122 | +0.5471 | +0.7097 |

Log returns over the period, which add up row by row. "Total exposure": what holding the previous day's total weight in the basket adds to the basket. "Choice between funds": what holding the previous day's weights by fund adds to that. These first three columns are an **approximation**: they value the weights held at the previous close with the close-to-close return, which is not how the book traded.

The **residual** is the gap between this approximation and the gross accounting of the engine. It is not a measure of the execution: besides the gap between the close and the price executed, the band and the whole quantities, it contains the return of the day on what was bought or sold that very morning - part of the effect of the signal. A book in cash that buys at the open, at the price of the previous close, and gains 10% during the day sees all this gain in the residual, with an "exposure" negative by as much. The "exposure" and "choice" columns are therefore not the full contribution of a timing, and the residual is not an execution handicap. An exact attribution requires the quantities before and after each fill and the opening prices; it is not produced here.

### SA5: the tilt signal and what the funds did next

- 1416 decisions with a non-zero residual; the residual changes sign **293 times**, i.e. a sign held 4.8 valuations on average.
- Correlation of the residual (positive when the world fund has fallen behind, hence overweighted) with the relative return of world minus S&P 500:

| Horizon | Pearson | Spearman | Pairs |
|---|---:|---:|---:|
| session t + 1 (partly before the execution at its open) | +0.029 | +0.030 | 1415 |
| session t + 2, the first full one after the execution | +0.028 | +0.004 | 1414 |
| sessions t + 2 to t + 6, compounded returns | +0.064 | +0.005 | 1410 |

A signal that forecast the relative return it bets on would show a positive correlation. These coefficients are given without an interval, on close-to-close returns: they do not measure the open-to-open interval actually carried after the decision, which is not computed here, and a correlation close to zero does not rule out every non-linear relation.

## 4. Each rule with a variable exposure beside a constant-target control

| Book | Net | Net/yr | Vol. | Sharpe | Max. drawdown | Back at peak (d) | Avg. expo. | Orders | Costs EUR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| SA3 - smooth MA | +57.88% | +8.62% | 11.01% | +0.79 | -21.64% | 540 | 71.5% | 78 | 680 |
| ↳ constant-target control (ETF_WORLD 71.5%) | +63.15% | +9.27% | 9.88% | +0.93 | -15.86% | 226 | 72.2% | 7 | 94 |
| SA6 - vol control | +67.43% | +9.78% | 10.87% | +0.90 | -15.72% | 330 | 84.7% | 180 | 1,445 |
| ↳ constant-target control (ETF_WORLD 84.7%) | +77.98% | +11.00% | 11.83% | +0.93 | -18.53% | 229 | 86.1% | 4 | 97 |
| SA10 - ensemble | +32.06% | +5.16% | 6.00% | +0.86 | -11.76% | 442 | 42.4% | 465 | 1,986 |
| ↳ constant-target control (ETF_SP500_PEA 15.3%, ETF_WORLD 27.1%) | +37.08% | +5.88% | 6.23% | +0.93 | -9.99% | 231 | 44.8% | 8 | 61 |
| SA11 - GARCH vol control | +65.98% | +9.61% | 11.14% | +0.87 | -16.50% | 324 | 87.5% | 508 | 3,749 |
| ↳ constant-target control (ETF_WORLD 87.5%) | +81.19% | +11.36% | 12.27% | +0.92 | -19.46% | 229 | 89.0% | 3 | 96 |
| EWMA 0.94 control | +73.37% | +10.48% | 11.16% | +0.93 | -15.45% | 321 | 87.8% | 220 | 1,519 |
| ↳ constant-target control (ETF_WORLD 87.8%) | +81.59% | +11.41% | 12.31% | +0.92 | -19.51% | 229 | 89.3% | 3 | 97 |

Control at a **constant target** equal to the rule's historical average weights, with the same 3-point rebalancing band and the same costs: it trades only when the drift of prices moves it 3 points away from its target. Its **realised** exposure therefore differs from the rule's, as the "Avg. expo." column shows (control minus rule: from +0.7 to +2.4 points here). The comparison describes the result of two executable rules; it does not isolate, at exactly the same exposure, the value of the timing: the level of exposure, the composition, the costs and the path change too. These weights being known after the fact, it is descriptive.

## 5. SA10 without each of its rules, and without its risk control

| Version | Net | Net/yr | Vol. | Sharpe | Max. drawdown | Back at peak (d) | Avg. expo. | Orders | Costs EUR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| SA10 - ensemble | +32.06% | +5.16% | 6.00% | +0.86 | -11.76% | 442 | 42.4% | 465 | 1,986 |
| SA10 without momentum | +18.88% | +3.18% | 3.58% | +0.88 | -7.12% | 449 | 25.3% | 368 | 1,256 |
| SA10 without trend | +20.39% | +3.42% | 4.10% | +0.83 | -7.51% | 324 | 28.2% | 417 | 1,813 |
| SA10 without pullback | +31.52% | +5.09% | 5.92% | +0.85 | -11.57% | 441 | 42.0% | 376 | 1,640 |
| SA10 without relative | +23.85% | +3.95% | 4.80% | +0.82 | -9.56% | 448 | 32.8% | 302 | 1,397 |
| SA10 without relief | +32.55% | +5.23% | 5.96% | +0.87 | -11.71% | 448 | 42.1% | 428 | 1,816 |
| SA10 without risk control | +32.55% | +5.23% | 6.11% | +0.85 | -11.88% | 441 | 42.6% | 441 | 1,973 |

Each "without" row sets the budget of one rule to zero: this budget stays in cash, it is not redistributed. "Without risk control" sets the risk target at a level never reached, so the reduction factor is always 1. All these versions are, like SA10 here, without style or money-market funds.

The gap between SA10 and its version without risk control measures the **aggregate effect** of this control on this run. It does not say how many times the reduction factor was below 1, nor on which dates: this factor and the decisions forced by the risk of the portfolio held are not exported.

## 6. SA6 against the EWMA control, and the EWMA at other coefficients

Sharpe difference SA6 minus EWMA 0.94: **-0.036**, 95% bootstrap interval [-0.104; +0.027] (blocks of 20 sessions, 5000 draws, seed 20261010). The interval includes zero: the two controls are not told apart.

| Book | Net | Net/yr | Vol. | Sharpe | Max. drawdown | Back at peak (d) | Avg. expo. | Orders | Costs EUR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| EWMA 0.94 control | +73.37% | +10.48% | 11.16% | +0.93 | -15.45% | 321 | 87.8% | 220 | 1,519 |
| SA6 - vol control | +67.43% | +9.78% | 10.87% | +0.90 | -15.72% | 330 | 84.7% | 180 | 1,445 |
| EWMA 0.90 | +69.40% | +10.02% | 11.14% | +0.90 | -14.60% | 251 | 87.9% | 366 | 2,686 |
| EWMA 0.97 | +77.75% | +10.98% | 11.25% | +0.97 | -17.08% | 330 | 87.6% | 127 | 769 |

The coefficients 0.90 and 0.97 were set in the script before their run, on either side of 0.94; they are not the result of a search for the best coefficient, and must not become one on this same history. The order of these three EWMAs holds only for them: it does not define a "speed" of the GARCH re-estimated every evening and does not establish a general rule by which a slower estimator would be better.

## 7. SA14

Extended test period, 2025-01-02 → 2026-10-09, frozen model `d9bfd125bf69`.

### Against a constant allocation

| Book | Net | Net/yr | Vol. | Sharpe | Max. drawdown | Back at peak (d) | Avg. expo. | Orders | Costs EUR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| SA14 - neural allocation | +13.42% | +7.39% | 9.88% | +0.76 | -16.11% | 251 | 66.6% | 270 | 756 |
| ↳ constant-target control (ETF_SP500_PEA 36.3%, ETF_WORLD 30.3%) | +17.16% | +9.38% | 10.01% | +0.93 | -15.20% | 225 | 68.3% | 6 | 76 |
| buy & hold World | +24.54% | +13.23% | 14.31% | +0.93 | -21.51% | 229 | 99.1% | 1 | 99 |

Control at a constant target equal to the average weights of SA14 over these dates, with the same 3-point band and the same costs: it is the executable control that the product "65% times the fund's return" did not replace. Its realised exposure is not exactly SA14's ("Avg. expo." column): the comparison describes two executable rules and does not isolate the value of the timing at identical exposure. Chosen after the fact, it is descriptive.

Over these dates, apart from the first session, the total weight held by SA14 ranges from 47.4% to 87.3% (standard deviation 8.3%), and the share of the S&P 500 fund in what is invested ranges from 33.1% to 66.2% (average 54.8%).

### Sensitivities announced by the hypothesis (original test period, 2025-01-02 → 2026-09-30)

| Variant | Model | Epoch retained | Score | Net | Sharpe | Sharpe of the fund held | Max. drawdown | Avg. expo. | Costs EUR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| seed 42, costs x1 (the preregistered test) | `d9bfd125bf69` | 20 | 44.5% | +11.71% | +0.68 | +0.86 | -16.11% | 66.6% | 752 |
| seed 43, costs x1 | `84d056424fc7` | 5 | 45.9% | +11.78% | +0.70 | +0.86 | -15.33% | 61.8% | 683 |
| seed 44, costs x1 | `8c9eaf9f5e92` | 15 | 45.6% | +12.26% | +0.71 | +0.86 | -15.96% | 68.3% | 654 |
| seed 42, frozen model of the test, costs x2 (engine only) | `d9bfd125bf69` | 20 | 40.7% | +11.01% | +0.64 | +0.86 | -16.21% | 66.6% | 1,434 |
| seed 42, recalibrated under costs x2 | `a5afb76183eb` | 15 | 44.3% | +11.78% | +0.69 | +0.86 | -15.65% | 66.0% | 1,037 |

Seeds 43 and 44 and the doubled costs are reported beside seed 42 and do not replace it: a seed is never chosen on its test result. All the rows cover the same original period. Two rows at doubled costs answer two different questions. "Frozen model" replays the **same artifact** as the preregistered test - same normalisation, same weights, same epoch - doubling only the costs of the engine: what the initial model becomes if it costs twice as much to execute. "Recalibrated" redoes the calibration of `scripts/SA14_run_neural_strategy.py` under these costs: its validation may retain another epoch, and it is then another model - what the calibration procedure produces under another cost. In each variant the Sharpe stays below the fund held's and the score below 50%.

### Inputs of the network

The 319 features read by the network at each of the 453 decisions are exported to `sa14_inputs.csv` (folder of the diagnostics), with their status: 453 decisions have a complete vector. They are rebuilt by the model's `NeuralFeatureBuilder` on a reader frozen at the instant of each decision.

