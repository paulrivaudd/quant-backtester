# Results and analyses of 10 October 2026

`results/` has one folder per strategy, `SA1` to `SA14`, and this folder, which
compares them. Everything is written by `scripts/write_strategy_reports.py` from
the exports of `scripts/SA11_run_garch_study.py`, after the store was updated to
2026-10-09; only this file is written by hand.

| In the folder of a strategy | What it is |
|---|---|
| `analysis.md` | its report: indicators, written analysis, history |
| `metrics.csv` | its indicators, at the declared costs and at doubled costs |
| `yearly.csv` | its returns by year, beside the fund held |
| `history.csv` | session by session: prices, signals read, weights targeted and held, value |
| `fills.csv` | its filled orders, one per row, with their price and their costs |
| `equity.png` | its net and gross value, against the fund held |
| `drawdown.png` | its fall below its own peak |
| `weights.png` | what it held in each fund, the rest being cash |
| `orders.png` | its orders on the prices of the funds, its weights and its value |
| `study.md` | for `SA11`, `SA12` and `SA13`: the document of their own study |

| In this folder | What it is |
|---|---|
| `ranking.csv`, `ranking_costs_x2.csv` | the table of all the books, at the declared and doubled costs |
| `yearly.csv` | the returns by year of all the books |
| `overview.png` | all the curves on one scale |
| `equity_all.png`, `drawdowns_all.png` | one panel per book, against `SA1` and the fund held |
| `costs.png` | what each book paid to trade |
| `diagnostics.md` | the complementary measures the review asked for |
| `REF_WorldBuyHold/`, `REF_5050Rebalanced/`, `EWMA94control/` | the two references and the control of `SA11`, without a catalogue code |

![Net value of every book, base 100](overview.png)

Each `analysis.md` has three sections: (1) the global result indicators, beside
the fund held; (2) the analysis — measured stretches, falls below a peak with
their recovery date, years and months, then strengths, weaknesses, worst and
best stretch, the market situations most risky for the strategy and what
remains to be measured; (3) the session-by-session history of the underlying,
of the indicators the strategy read, of its weights and of its value.

**Version 2 of the analyses.** The commentaries were rewritten after an
independent review made on commit `4e04eae`
(`revue_analyses_strategies_resultats_10102026.md`). The global figures did not
change. What changed: the chronologies of positions (SA3, SA4, SA6, SA9, SA10,
SA11, SA14), the causal conclusions that were not demonstrated, the distinction
between measured fact and reading, and the addition of the recovery of the
falls, of the unchanged months, of the partial periods, of the 50/50 control,
of the two reference reports and of an interval on the QLIKE gaps.

**Version 3 of the analyses.** An independent check made on commit `ad310bc`
(`verification_resultats_corriges_10102026.md`) found the global figures and the
histories again, and asked for several readings to be bounded. The global
figures did not change. What changed: the residual of the attribution of `SA2`
and `SA5` is no longer called "execution"; the controls are called
"constant-target" and the comparison no longer claims to isolate the timing;
the close-to-open price gap is measured again at given quantities and is no
longer presented as a cost; the still-open stay of `SA1` is counted apart;
`SA14` is replayed at doubled costs with its frozen model; the contradictions
found in the texts of `SA2`, `SA3`, `SA4`, `SA9`, `SA10`, `SA11`, the EWMA and
`SA14` are corrected.

**SA7 and SA8, on 2026-10-11.** They were catalogued with the other ETF rules
but had never run, for lack of chosen funds. Their funds, listed on Xetra, were
registered that day and the common study was run again: the store changes
(`b5facce52a6f`), but the figures of the other books are identical, to the
cent, to those of the previous run. `SA7` enters the ranking; `SA8` is reported
apart (see below).

**In English since 2026-10-31.** The analyses, this file and the diagnostics
were translated from French; the reports were regenerated from the same
exports, and no figure changes.

## How to read

- A decision is taken on the evening of session t (signal and target weight of
  row t) and executed at the open of t + 1; it appears in the weight held only
  at row t + 1.
- In the commentaries, **Fact** means what is read again in the exports,
  **Reading** a plausible interpretation that is not demonstrated, **Observed**
  and **Plausible** a risk seen in these histories or only expected.
- Cash earns nothing and the risk-free rate is zero.
- 2021 starts on 1 April and 2026 stops on 9 October: they are partial years,
  and October 2026 an incomplete month.

## Common ranking (exploratory)

Period 2021-04-01 → 2026-10-09 (1,416 valuations), 100,000 EUR, commission
5 bp (minimum 1 EUR), half spread 3 bp, slippage 2 bp, quantities set at the
decision. `QUALITY_V1` score against `ETF_WORLD` held, deflated by 11 trials.

| Rank | Book | Score | Net | Sharpe | Max. drawdown | Back at peak | Costs (EUR) | Report |
|---:|---|---:|---:|---:|---:|---:|---:|---|
| 1 | 50/50 rebalanced (reference, outside the catalogue) | 77.9% | +103.3% | 0.96 | -22.5% | 232 d | 736 | [report](REF_5050Rebalanced/analysis.md) |
| 2 | EWMA 0.94 (control of SA11, no code) | 53.6% | +73.4% | 0.93 | -15.4% | 321 d | 1,519 | [report](EWMA94control/analysis.md) |
| 3 | SA6 - vol control | 52.0% | +67.4% | 0.90 | -15.7% | 330 d | 1,445 | [report](../SA6/analysis.md) |
| 4 | SA10 - ensemble, **without factors or money market** | 51.1% | +32.1% | 0.86 | -11.8% | 442 d | 1,986 | [report](../SA10/analysis.md) |
| 5 | SA7 - factor blend, **Xetra funds** | 49.8% | +60.2% | 0.83 | -16.4% | 242 d | 1,983 | [report](../SA7/analysis.md) |
| 6 | SA3 - smooth MA | 49.1% | +57.9% | 0.79 | -21.6% | 540 d | 680 | [report](../SA3/analysis.md) |
| 7 | **SA11 - GARCH vol control** | 48.7% | +66.0% | 0.87 | -16.5% | 324 d | 3,749 | [report](../SA11/analysis.md) |
| 8 | SA2 - dual momentum | 44.2% | +69.2% | 0.78 | -22.8% | 422 d | 4,629 | [report](../SA2/analysis.md) |
| 9 | SA5 - relative tilt | 29.5% | +72.8% | 0.76 | -22.9% | 252 d | 20,517 | [report](../SA5/analysis.md) |
| 10 | SA1 - std MA20 | 0.0% | +20.5% | 0.42 | -18.9% | 794 d | 15,730 | [report](../SA1/analysis.md) |
| 10 | SA4 - pullback | 0.0% | +4.4% | 0.41 | -3.4% | not recovered | 4,572 | [report](../SA4/analysis.md) |
| 10 | SA9 - VIX relief | 0.0% | -0.7% | -0.04 | -8.0% | not recovered | 2,041 | [report](../SA9/analysis.md) |
| — | SA8 - monetary carry (money-market investment, outside the ranking) | — | +10.5% | 7.10 | -0.4% | 75 d | 963 | [report](../SA8/analysis.md) |
| — | ETF_WORLD held (yardstick, not scored) | — | +94.8% | 0.93 | -21.6% | 229 d | 100 | [report](REF_WorldBuyHold/analysis.md) |

"Back at peak": calendar days between the peak that precedes the maximum
drawdown and the first valuation back at that level.

This ranking is **exploratory**. The score is a weighted geometric mean of five
blocks: a single block at zero gives a zero score, which explains the three
zeros of rank 10 and means neither an economic tie nor a zero probability of
gain. It is deflated by the eleven trials of this study, not by the variants of
earlier exercises. A gap of a few points (53.6 / 52.0 / 49.8 / 48.7) is not a
test of superiority. No strategy of the catalogue beats the passive 50/50
basket of the same two funds.

`SA8` runs over the same period and at the same costs, but is neither scored
nor counted among the trials, like the fund held. It holds only a money-market
fund: with a zero risk-free rate, its Sharpe of 7.10 is that of a price that
hardly moves, not a measure of timing. Counted among the trials, it multiplied
by six the dispersion of the Sharpe ratios that deflates the scores and brought
all the others down to about 1%.

## SA11: the preregistered criteria are not met

The `REFUTED` status of the hypothesis `sa11_garch_vol_control` is
**operational**: the criteria written before the run are met, since the net
Sharpe of `SA11` (0.87) is above neither that of `SA6` (0.90) nor that of the
EWMA control (0.93) and its maximum drawdown is deeper. It is not a statistical
proof of inferiority: at the base costs, the 95% intervals of the Sharpe
difference include zero ([-0.141; +0.076] against `SA6`, [-0.147; +0.009]
against the EWMA); in the second run at doubled costs, the one against the EWMA
is negative ([-0.172; -0.014]).

`SA11` has the **lowest mean QLIKE observed** (-8.6225, against -8.6033 for the
EWMA and -8.5649 for the estimator of `SA6`). The lead is established against
`SA6` (paired difference -0.058, interval [-0.108; -0.017]) and not against the
EWMA (-0.019, interval [-0.051; +0.009]). No fit was rejected over 1,416
decisions. Forecasting the close-to-close variance better did not translate
into a better allocation after execution at the open, band and costs (2.5 times
those of `SA6`). The simple controls are kept; `SA11` stays in the catalogue as
a fixed reference. This says nothing about GARCH models in general. Detail:
[SA11/study.md](../SA11/study.md).

## SA12: a study apart, over the same period

[SA12/analysis.md](../SA12/analysis.md) comes from its own study
(`scripts/SA12_run_arima_garch_study.py`, commit `10f6d90`, same store, same
period 2021-04-01 → 2026-10-09), which also runs three controls without a
catalogue code: D0 (same ARIMA and same variance, direction gate always open),
D1 (EWMA variance), D2 (constant mean). Its register counts 14 trials: its
scores are not read in the table above, deflated by 10. Detail:
[SA12/study.md](../SA12/study.md).

| Book | Net | Net, costs ×2 | Sharpe | Max. drawdown | Exposure | Costs (EUR) |
|---|---:|---:|---:|---:|---:|---:|
| **SA12 - ARIMA GARCH** | -1.72% | -5.70% | -0.14 | -6.99% | 4% | 4,022 |
| D0, same risk without the gate | +64.07% | +56.33% | 0.85 | -17.77% | 86% | 5,788 |
| D1, ARIMA and EWMA variance | -2.46% | -6.52% | -0.20 | -7.32% | 4% | 4,126 |
| D2, constant mean and GARCH | 0.00% | 0.00% | n/a | 0.00% | 0% | 0 |
| SA6 - vol control | +67.43% | +65.50% | 0.90 | -15.72% | 85% | 1,445 |
| ETF_WORLD held | +94.79% | +94.34% | 0.93 | -21.64% | 100% | 100 |

- **Status of the hypothesis `sa12_arima_garch`: `INSUFFICIENT_EVIDENCE`.** The
  criteria written before the run asked for 30 finished position episodes;
  there are 29. The threshold was not changed after reading. The Sharpe gap
  measured against D0 is -0.987 (95% interval [-2.101; +0.252]) at the base
  costs and -1.241 ([-2.335; -0.032]) at doubled costs.
- **The forecast crosses the 20 bp threshold on only 31 evenings out of
  1,413**, all from 2025-04-10: the book stays in cash for four years, then
  takes 29 positions, of which 22 last only one valuation. The costs
  (4,022 EUR) exceed the gross gain (+2.30%).
- **The forecast mean does not beat two naive forecasts** (squared error
  9.2497e-05 against 9.2133e-05 for zero and 9.2002e-05 for the mean of the
  window; right sign 56.1% against 56.7% for "always up").
- **GARCH and EWMA are not told apart** (Sharpe gap against D1 +0.061, interval
  [-0.037; +0.170]); D2 never took a position.

This says nothing about ARIMA-GARCH models in general, and no control is a
candidate: adopting one would be a new hypothesis.

## SA13: a study apart, over a shorter test period

[SA13/analysis.md](../SA13/analysis.md) comes from its own study
(`scripts/SA13_run_signature_study.py`, commit `2b7d147`, same store). One
model a month is calibrated on what was known on the evening of the last
session of the previous month; the first month that can be calibrated is
January 2023, so the **test period is 2023-01-02 → 2026-10-09** (964 sessions),
with a continuous portfolio. All the comparable strategies are replayed over
it, with eight controls without a catalogue code (C0 to C7): 19 trials. **These
figures are not comparable with those of the table at the top**, measured since
2021. Detail: [SA13/study.md](../SA13/study.md).

| Book | Net | Net, costs ×2 | Sharpe | Max. drawdown | Exposure | Costs (EUR) |
|---|---:|---:|---:|---:|---:|---:|
| **SA13 - Signatures Neurons** | -3.53% | -5.11% | -0.10 | -18.56% | 23% | 1,579 |
| C0, same risk without the gate (identical to SA6 here) | +62.09% | +61.08% | 1.25 | -15.70% | 89% | 924 |
| C1, Ridge on the same 13 coefficients | +11.25% | +10.40% | 0.57 | -10.72% | 16% | 914 |
| C2, additive network at order 2 | -3.75% | -3.92% | -0.29 | -9.02% | 3% | 172 |
| C3, additive network without volume | -3.47% | -5.07% | -0.09 | -15.68% | 31% | 1,534 |
| C4, additive network on classic indicators | +14.05% | +12.66% | 0.48 | -22.98% | 44% | 1,291 |
| C5, Ridge on the raw path | -1.19% | -25.72% | -0.02 | -10.56% | 31% | 29,410 |
| C6, additive network, World + S&P 500 | -2.49% | -4.90% | -0.09 | -15.06% | 24% | 2,449 |
| C7, Ridge, World + S&P 500 | +17.87% | +16.56% | 0.78 | -13.95% | 19% | 1,337 |
| SA11 - GARCH vol control | +65.53% | +63.31% | 1.27 | -16.52% | 92% | 1,896 |
| SA12 - ARIMA GARCH | -1.72% | -5.70% | -0.16 | -6.99% | 6% | 4,022 |
| ETF_WORLD held | +86.73% | +86.63% | 1.35 | -21.57% | 99% | 99 |

- **Status of the hypothesis `sa13_signatures_neurons`:
  `INSUFFICIENT_EVIDENCE`.** The criteria written before the first fit asked
  for 30 finished position episodes; there are 8. The threshold was not changed
  after reading. The Sharpe gap measured against C0 is -1.353, 95% interval
  [-1.999; -0.627] (blocks of 60 sessions; negative also with blocks of 20 and
  of 120), and -1.401 ([-2.052; -0.678]) at doubled costs.
- **Full coverage**: 46 months out of 46 have a model, 964 decisions out of 964
  a usable forecast. The failure is not operational.
- **The forecasts are worse than the training mean** (squared error 8.7648e-05
  against 8.5353e-05, a gap whose interval excludes zero) **and than the Ridge
  on the same coefficients**. Right sign 52.4% against 57.1% for "always up".
- **The book is invested during the two falls** (August 2024, February to April
  2025), in which the forecast rises with the fall, and in cash during long
  rises: the fund gains +3.0 bp per session when the book is invested and
  +8.3 bp when it is in cash.
- **Neither order 3, nor the volume, nor a second process lowers the error** of
  the forecast; against the classic indicators and the raw path, the error of
  SA13 is lower without the gap being told from zero.
- 22 models out of 46 stop at the ceiling of 300 epochs, frozen before the first
  fit.

This says nothing about path signatures in general. The Ridge controls do
better than `SA13` here, but no control is a candidate: adopting one would be a
new hypothesis.

## Outside the ranking

- **SA14**, called `ML1` until 2026-10-11 ([report](../SA14/analysis.md)): its
  information stops at 2024-12-31. It is measured over 2025-01-02 → 2026-10-09
  (+13.4% against +24.5% for the fund, Sharpe 0.76 against 0.93). Its score,
  deflated for a single trial, is not comparable with those of the table. The
  original test (up to 2026-09-30) was already read on 2026-10-04; seeds 43 and
  44 and the two runs at doubled costs (frozen model, recalibrated model) are
  in the diagnostics.

## SA7 and SA8: run on Xetra funds, with two reservations

| Strategy | Funds | Net | Sharpe | Rank |
|---|---|---:|---:|---|
| [SA7 - factor blend](../SA7/analysis.md) | iShares Edge MSCI World Value, Quality, Minimum Volatility (`IS3S.DE`, `IS3Q.DE`, `IQQ0.DE`) | +60.2% | 0.83 | 5 |
| [SA8 - monetary carry](../SA8/analysis.md) | Xtrackers II EUR Overnight Rate Swap (`XEON.DE`) | +10.5% | 7.10 | outside the ranking |

The first funds chosen were listed in Paris (three BNP Paribas Easy style
funds, and `OBLI.PA`); the data control refused them, one bar in five of the
style funds having since 2023 a close outside its own range. The funds retained
are listed on Xetra, in euros, are not eligible for the PEA, and have only one
price source.

The two reservations weigh on the figures and are measured in each analysis:

- **The calendar.** The run is made on the Paris one. A session that Paris
  holds and Xetra does not (Whit Monday 2021, 24 and 31 December) leaves the
  funds without a close; the two rules then target cash, sell and buy back the
  next day. That makes 30 of the 72 orders of `SA7` (1,215 EUR) and 8 of the 9
  orders of `SA8` (863 EUR of its 963 EUR of costs).
- **Two sessions the provider does not serve**, 2025-10-24 and 2026-03-06,
  break the window of 61 consecutive closes of `SA7`, which stays in cash for 62
  then 60 valuations while the Value fund gains +9.3% then +29.4%. No second
  source allows them to be filled, and a price is never rebuilt.

`SA10` is still run without style funds or a money-market fund, as in all its
previous runs: its full version is another run, still to be decided.

## SA16: a study apart, over another window

[SA16/study.md](../SA16/study.md) comes from its own study
(`scripts/SA16_run_study.py`, store `runs/sa16_store`, window
2018-08-01 → 2026-10-30, conventions of SA15: Sharpe over 252 sessions at a
zero rate). Its figures are not read in the ranking above. The configuration
retained (technology and gold at a 75/25 risk budget) makes 22.40% a year,
Sharpe 1.321, maximum drawdown −22.3%, against 19.09% / 0.942 / −31.3% for the
Nasdaq held and 20.97% / 1.064 / −25.7% for SA15 trial 71; a Sharpe advantage
established by bootstrap, a return advantage not established and dependent on
the choice of technology.

## Complementary diagnostics

[diagnostics.md](diagnostics.md) measures what the analyses listed as remaining
to be measured; it is its version 2, recomputed after the check. Everything in
it is **descriptive**: the controls are built on weights observed after the
fact, and no variant is a candidate. What it shows:

- **No rule with a variable exposure clearly beats its constant-target
  control.** This control aims at the rule's average weights, with the same
  3-point band; its realised exposure is 0.7 to 2.4 points higher. The
  comparison therefore describes two executable rules and does not isolate the
  value of the timing at identical exposure. `SA3` (Sharpe 0.79) and `SA10`
  (0.86) do worse than theirs (0.93 each), including in maximum drawdown. `SA6`
  (0.90) and `SA11` (0.87) have a maximum drawdown about three points smaller
  than theirs, for a lower Sharpe; only the EWMA equals its own (0.93 against
  0.92) with four points less maximum drawdown.
- **`SA2` and `SA5` against the 50/50**: an approximate attribution, which
  values the weights of the previous close at the close-to-close return. For
  `SA2` the contribution of the exposure is negative (-0.140 in log return) and
  that of the choice between funds almost zero (+0.004). For `SA5` the choice
  between funds weighs +0.003, the costs -0.112 and the residual -0.060. This
  residual is not a measure of the execution: it also contains the return of
  the day on what was traded that very morning, hence part of the effect of the
  signal. The contribution of the tilt of `SA5` is not isolated; the
  correlations of its signal with the relative return that follows are close to
  zero (+0.03 to +0.06, without an interval).
- **The signed close → open price gap, at given quantities**, is -14,568 EUR
  for `SA1`, of the same order as its explicit costs, and -4,944 EUR for `SA9`,
  more than twice its own; `SA4` is the only book in which it is positive
  (+2,303 EUR). It is neither a cost paid nor the result of a backtest executed
  at the close: the signal reads that close.
- **By stay in the market**: `SA1` has 71 closed stays, 39% of them winners,
  and one stay still open; `SA4` has 66% winning stays (average net gain of
  0.06%); `SA9` has 9 out of 21, i.e. 4 groups of winning stays out of 7, groups
  formed by a convention of 20 valuations and not seven independent panics.
- **`SA10`**: the aggregate effect of its risk control is small on this run,
  without its frequency being exported, and none of its rules carries its
  Sharpe.
- **`SA6` against the EWMA**: Sharpe difference of -0.036, interval
  [-0.104; +0.027]; the two controls are not told apart.
- **`SA14`** does worse than its constant-target control (Sharpe 0.76 against
  0.93); seeds 43 and 44 fail like seed 42 (Sharpe 0.68 to 0.71 against 0.86
  for the fund, score below 50%), and at doubled costs the frozen model (0.64)
  as the recalibrated model (0.69) stay below the fund.

## What these files do not contain

Each folder covers all the sessions of its strategy but is not the archive of a
run. The rejects, the costs per session, the forecasts and the curves of all
the books are in the raw exports of each study (`runs/garch_study/`,
`runs/arima_garch_study/`, `runs/signature_study/`, `runs/sa14/`), and the
detail of the diagnostics in `runs/review_diagnostics/` (stays one by one,
inputs of `SA14`, tables of the controls). `runs/` is not committed: it is
reproduced. Still not produced: an exact attribution of `SA2` and `SA5` at the
quantities and opening prices; a control with an exposure or a risk truly
matched; the breakdown of the targets of `SA10` rule by rule at each decision,
and the reduction factor of its risk control; an analysis of the inputs of
`SA14`.

## Reproduce

```bash
uv sync --extra ml --extra stats
uv run python scripts/update_market_data.py
uv run python scripts/SA11_run_garch_study.py --output runs/garch_study
# the diagnostics first load the model of SA14: it must exist
uv run python scripts/SA14_run_neural_strategy.py --seed 42 --calibrate-only
uv run python scripts/run_review_diagnostics.py
uv run python scripts/write_strategy_reports.py --study runs/garch_study

# SA12, its study and its report (about an hour, a single thread)
OMP_NUM_THREADS=1 uv run python scripts/SA12_run_arima_garch_study.py \
    --output runs/arima_garch_study
uv run python scripts/write_strategy_reports.py --study runs/arima_garch_study --only SA12

# SA13, its monthly calibrations, its study and its report (about twenty minutes)
uv sync --extra ml --extra stats --extra signatures
OMP_NUM_THREADS=1 uv run python scripts/SA13_run_signature_study.py \
    --output runs/signature_study
uv run python scripts/write_strategy_reports.py --study runs/signature_study --only SA13
```

This recipe redoes the procedure, not necessarily the same numbers: running
`update_market_data.py` again does not guarantee finding the store of the
common study (`b5facce52a6f`) nor that of the studies of `SA12` and `SA13`
(`750c23dfffc3`), and a calibration redone on revised data is not the published
model (`d9bfd125bf69`). The diagnostics refuse to put a run beside the exports
of a study made on another store, another capital or other costs.

The written commentary is in
[research/commentary.toml](../../research/commentary.toml); the tables and the
measured facts are recomputed at each run. Everything is a retrospective
evaluation: the history of `ETF_WORLD` has already been looked at, and the
prospective check of `SA11` starts at the first XPAR session after 2026-10-10.
