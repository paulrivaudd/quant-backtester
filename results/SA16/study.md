# SA16 — technology and gold under a risk budget — study of 31 October 2026

**Verdict.** The configuration retained, **SA16_it2** (`SA16RiskBudget`), beats,
net of costs, the Nasdaq-100 held and the last archived selection of SA15, over
the whole window and under all the declared robustness controls: CAGR 22.40%
against 19.09% and 20.97%, Sharpe 1.321 against 0.942 and 1.064, maximum
drawdown −22.3% against −31.3% and −25.7%. Doubled costs, 7 neighbours out of 7
and 7 restarts from cash out of 7 keep the order. The **Sharpe** superiority is
established by the paired bootstrap (90% intervals above zero against the two
references). The **return** superiority is not: its intervals contain zero.
Status in the strict sense of the protocol: **UNCERTAIN**.

Three limits weigh on the reading:

- **The return advantage comes mostly from the choice of technology**,
  inherited from SA15, which made it after seeing 2019–2024. The same rule on
  the Nasdaq beats the two references in Sharpe, but not in CAGR.
- **Technology held alone does better in CAGR** (24.14%), at the price of a
  maximum drawdown of −31.4% and a Sharpe of 1.041.
- **The whole history had already been examined**: the study is retrospective.

Three candidates out of the ten allowed were used; the specification provides
for stopping when a strategy dominates its references with a documented
robustness.

![Net value (log scale) and fall below the peak](comparison.png)

![Weights held by SA16_it2](weights.png)

## 1. References, data, conventions

- **SA(N−1) = SA15, trial 71 of R4** (`results/SA15_GPT-6.1_R4/selected.json`,
  `SA15RiskAwareRotation`, monthly, fingerprint `ef95006960c2…`). R5 stopped at
  M34 without a selection or a report (the README of SA15 points to a
  `selected.json` and a `study.md` of R5 that do not exist): R4 is the last
  configuration explicitly retained and archived. Detail:
  [protocol](../../research/SA16/protocol.md), section 1.
- **Reproduction**: on the rebuilt store, trial 71 and the Nasdaq held fall
  back to the cent on the SA15 archive (499,693.44 EUR and 448,002.97 EUR at
  2026-10-09; maximum relative gap 0 over 1,886 sessions;
  `reproduction/reproduction.json`).
- **Store** `runs/sa16_store` (`scripts/SA16_download_data.py`), fingerprint
  `677397e6fb770978…` for all the runs of the study: the project's registry,
  the SA15 additions and the SA16 signal series
  (`research/SA16/instruments.toml`: `^NDX`, GLD, HYG, IEF, VIX3M). Restated
  Yahoo/FRED histories, a single source, no vintages. QDVE, 4GLD and three
  other Xetra funds have no bar on 2025-10-24 or on 2026-03-06; no price is
  rebuilt.
- **Conventions of SA15**: XPAR calendar, 100,000 EUR, whole units,
  commission 5 bp (min. 1 EUR), half spread 3 bp, slippage 2 bp, quantities
  set at the 23:00 Paris decision, execution at the next open of the fund on
  its venue, Sharpe over 252 sessions, zero risk-free rate; costs ×2 = a
  second actual run.
- **Window**: 2018-08-01 → 2026-10-30, 2,113 sessions: the first month in
  which all the inputs of the references can be read, up to the last full
  session before the study.

## 2. The strategy retained: SA16_it2

At the end of each week (last XPAR session), at 23:00 Paris:

1. annualised volatility `σ` of **US technology** (QDVE.DE, iShares S&P 500
   Information Technology, listed in euros, unhedged) and of **gold** (4GLD.DE,
   ETC Xetra-Gold) over their last 126 log returns in euros, **each return
   divided by the square root of the number of sessions it covers** (new
   signal `SpanScaledVolatilitySignal`, at most 3 sessions per return); floor
   5%;
2. target weights `w ∝ b / σ` with a **risk budget** `b = 0.75` for
   technology and `0.25` for gold, the sum making the whole book;
3. an order only if a weight moves more than **5 points** away from its
   target; execution at the next Xetra open;
4. an input that cannot be read keeps the book (none could not be).

No forecast of direction, no leverage, no short selling, always invested. When
prices move the weights apart, the band sells what rose against the other and
buys what fell.

| Parameter | Value | Parameter | Value |
| --- | --- | --- | --- |
| `growth_id` | `ETF_US_TECH` | `hedge_id` | `ETF_GOLD` |
| `growth_risk_budget` | 0.75 | `volatility_returns` | 126 |
| `max_span_sessions` | 3 | `volatility_floor` | 0.05 |
| `rebalance_band` | 0.05 | `max_age_sessions` | 1 |
| `relative_lookback` / `momentum_tilt` | 0 / 0 (inactive) | cadence | weekly |

File: [`research/SA16/candidates/it02.json`](../../research/SA16/candidates/it02.json);
freeze: [`selected.json`](selected.json), fingerprint `66b3493a8970…`. The rerun
with the final code (commit `cedf642`, clean tree) gives back the curve to the
cent over the 2,113 sessions, at costs ×1 and ×2. The default values of the
class are those of the configuration retained, except the identifier
(`SA16_growth_gold_budget` in the catalogue, `SA16_it2` in the results).

## 3. Results over the full window

| Book | Total net | Total gross | Net CAGR | Vol. | Sharpe | Max. drawdown | Costs EUR | Trading days/yr |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **SA16_it2** | **+429.5%** | +430.2% | **22.40%** | 16.03% | **1.321** | **−22.3%** | 698 | 2.5 |
| SA16_it2, costs ×2 | +427.6% | +429.0% | 22.35% | 16.03% | 1.319 | −22.3% | 1,390 | 2.5 |
| Nasdaq held (SXRV) | +322.3% | +322.4% | 19.09% | 20.49% | 0.942 | −31.3% | 100 | 0.1 |
| SA15 trial 71 | +380.6% | +387.9% | 20.97% | 19.39% | 1.064 | −25.7% | 7,265 | 3.8 |
| SA15 trial 71, costs ×2 | +369.8% | +384.2% | 20.64% | 19.40% | 1.049 | −25.8% | 14,322 | 3.8 |
| *Technology held (QDVE)* | +495.0% | +495.1% | 24.14% | 22.99% | 1.041 | −31.4% | 100 | 0.1 |
| *Constant target 2/3 tech – 1/3 gold (C1)* | +409.4% | +409.8% | 21.83% | 16.31% | 1.273 | −22.7% | 373 | 1.1 |
| *Same rule, Nasdaq instead of tech (C2)* | +304.0% | +304.4% | 18.45% | 14.63% | 1.212 | −21.1% | 433 | 1.8 |
| *Nasdaq + gold 50/50 drifting* | +277.0% | +277.1% | 17.46% | 13.39% | 1.249 | −17.5% | 100 | 0.1 |
| *Gold held (4GLD)* | +233.2% | +233.3% | 15.71% | 15.60% | 0.999 | −22.8% | 100 | 0.1 |

In italics: passive or ablation controls, never candidates. The gross keeps the
same transactions without fees (not a counterfactual portfolio).

**Paired bootstrap** (`paired_block_bootstrap`, blocks of 20 sessions,
2,000 draws, seed 1616, 90%), SA16_it2 minus:

| Against | ΔSharpe [90% CI] | Δannualised mean return [90% CI] |
| --- | --- | --- |
| Nasdaq held | **+0.380 [+0.209; +0.618]** | +1.9 pt [−2.2; +7.0] |
| SA15 trial 71 | **+0.258 [+0.028; +0.560]** | +0.6 pt [−4.1; +6.4] |
| C1, constant target 2/3 – 1/3 | +0.048 [+0.001; +0.103] | +0.4 pt [−0.4; +1.3] |
| C2, Nasdaq as growth | +0.109 [−0.020; +0.239] | **+3.4 pts [+1.5; +5.5]** |

Reading: the volatility weighting adds almost nothing to the constant mix (C1
also beats the two references); the return advantage over the Nasdaq comes from
the choice of technology (against C2); the robust gain of SA16 is a gain in
**risk** (Sharpe, maximum drawdown), not in return.

## 4. Years and episodes, unfavourable ones included

| Year | SA16_it2 | Nasdaq | SA15 | Technology | C1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2018 (from August) | −6.3% | −11.2% | −7.7% | −11.3% | −7.3% |
| 2019 | 39.5% | 42.8% | 46.6% | 53.9% | 41.5% |
| 2020 | 24.1% | 34.4% | 21.7% | 29.7% | 24.3% |
| 2021 | 32.5% | 39.3% | 48.8% | 46.8% | 32.3% |
| 2022 | −13.7% | −30.0% | −17.2% | −25.8% | −15.3% |
| 2023 | 35.3% | 51.1% | 41.9% | 54.1% | 38.1% |
| 2024 | 42.2% | 33.5% | 48.8% | 46.1% | 42.2% |
| 2025 | 23.4% | 7.0% | 13.6% | 10.0% | 22.6% |
| 2026 (to 30 Oct.) | 20.2% | 17.7% | −1.2% | 24.7% | 15.8% |

**Unfavourable years**: SA16 loses against the Nasdaq in 2019 (−3.3 points),
2020 (−10.3), 2021 (−6.8) and 2023 (−15.8), and against SA15 in 2019, 2021,
2023 and 2024. These are the great years of technology, in which the third in
gold holds it back. It wins in 2018, 2022, 2024, 2025 and 2026 against the
Nasdaq.

| Episode | SA16_it2 | Nasdaq | SA15 | Technology |
| --- | ---: | ---: | ---: | ---: |
| 2018Q4 (Oct.–Dec.) | −6.7% | −15.9% | −12.8% | −16.2% |
| 2020 crash (19 Feb. – 31 March) | −13.3% | −18.0% | −16.3% | −19.3% |
| 2020 rebound (April – August) | +27.3% | +39.1% | +21.0% | +36.2% |
| 2022 | −13.7% | −30.0% | −17.2% | −25.8% |
| 2025 crash (19 Feb. – 30 April) | −12.3% | −19.2% | −16.4% | −20.9% |
| 2025 rebound (May – Sept.) | +25.8% | +22.9% | +16.2% | +33.7% |

**Maximum drawdowns of SA16_it2**: −22.3% from 2020-02-20 to 2020-03-23 (gold
falls too during the liquidity crisis; peak back on 2020-06-23); −20.0% from
2025-02-20 to 2025-04-07 (back on 2025-07-17); −15.3% from August to December
2022, when gold and technology fall together (back on 2023-05-18). SA15 is, at
2026-10-30, in a drawdown of −22.6% open since 2026-01-29.

## 5. Robustness

| Control | Result |
| --- | --- |
| Doubled costs (actual run) | CAGR 22.35%, Sharpe 1.319: beats SA15 ×2 (20.64%; 1.049) and the Nasdaq |
| 7 declared neighbours (budget 0.70/0.80, volatility 63/189, band 0.03/0.08, monthly) | 7/7 beat the two references; CAGR 21.77 to 22.85%, Sharpe 1.273 to 1.361, max. drawdown −20.9 to −24.0% |
| 7 restarts from cash (2019 to 2025, up to 2026-10-30) | 7/7 beat the two references in CAGR and in Sharpe |
| Deflated Sharpe (Bailey and López de Prado) | 0.999 for 13 trials in the register |

Detail: [`robustness/SA16_it2/tables.md`](robustness/SA16_it2/tables.md).
Limits of these tests:

- The restarts share the same end (2025–2026, very favourable to gold) and are
  not independent.
- The neighbours vary only one parameter at a time.
- The deflated Sharpe measures an absolute Sharpe against chance, not the
  probability of beating the Nasdaq. It counts neither the 85 policies of SA15
  nor the earlier choices of universe of the project.

## 6. All the iterations

| Iteration | Family, mechanism | CAGR | Sharpe | Max. drawdown | Costs EUR | Status |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| [it1](../../research/SA16/it01.md) | Nasdaq held at the share of positive 1/3/6/12-month returns of `^NDX` (New York close), the remainder to gold according to its own trend, then money market | 15.54% | 0.996 | −24.5% | 15,024 | NOT_SUPPORTED |
| it1 C1 | same rule without gold | 12.48% | 0.862 | −24.8% | 10,275 | control |
| [**it2**](../../research/SA16/it02.md) | **technology + gold at a 75/25 risk budget, inverse of the span-normalised volatility** | **22.40%** | **1.321** | **−22.3%** | 698 | **retained, UNCERTAIN** |
| it2 C1 | constant target 2/3 – 1/3 | 21.83% | 1.273 | −22.7% | 373 | control |
| it2 C2 | same rule, Nasdaq as growth | 18.45% | 1.212 | −21.1% | 433 | control |
| [it3](../../research/SA16/it03.md) | it2 + budget tilted ±0.10 towards the asset with the best 6-month return | 20.48% | 1.207 | −23.9% | 4,028 | NOT_SUPPORTED |

- **it1**, directional timing in steps: it sells in the Vs and comes back late.
  In 2020, 0% of Nasdaq on 20 March and 3 April, then 75% on 9 April, after the
  rebound. Crash at −20.2% against −18.0% for the Nasdaq held, 2023 at +34.4%
  against +51.1%. Gold is useful in it only when **held**: against its control
  without gold, Δreturn +2.8 pts [+0.2; +5.9]. From 2018-08 to 2018-12, the
  book stayed in cash, for lack of 252 sessions of history for gold: its 2018
  is not an effect of the rule.
- **it2** changes family: structural diversification, contrarian rebalancing,
  no sale at the trough. In 2020, the target and the book drift together within
  the band and the rule places no order.
- **it3** tilts the budget according to the 6-month relative momentum: late at
  each turn (2019, 2020, early 2022). ΔSharpe against it2 −0.115
  [−0.234; −0.005]; costs multiplied by six.
- **Set aside without a backtest**, after a control of the data: a contrarian
  purchase during the VIX/VIX3M inversions, too early in 3 of the 6 long
  inversions. Set aside on the lessons of it1 and of the filters of SA15 R3/R5:
  a cap on the portfolio's volatility towards the money market (the same delay
  at the rebound).

## 7. Manual execution

SA16_it2: 42 orders on 21 trading days over 8.25 years (**2.5 days a year,
exactly 2 orders per trading day**, maximum 2; limit 20, target 1 to 10).
Turnover 0.35 times the book a year; average residual cash 0.16%. Eleven
rejects, all `INSUFFICIENT_CASH`: a purchase reduced for lack of cash after a
sale in whole units and fees, like the 19 of SA15. No decision had an input
that could not be read: the span-normalised volatility crosses the two sessions
that Yahoo does not serve, where SA15 loses technology six months in a row.

## 8. What is documented and what is specific to SA16

Documented building blocks:

- **Risk budget**, weights `b/σ` without correlation: Maillard, Roncalli,
  Teiletche (2010).
- **Gold hedges equities** on average and serves as a haven in extreme shocks;
  buying it after the crash underperforms: Baur, Lucey (2010).
- **Diversification return through rebalancing**: Willenbrock (2011), with the
  criticisms of Chambers (2014) and of Cuthbertson et al.
- **Volatility and momentum**: volatility management improves equities
  (Harvey et al., 2018) but often disappoints out of sample (Cederburg et al.,
  2020); the advantage of time-series momentum comes mostly from the
  volatility weighting (Kim, Tse, Wald, 2016).
- Time-series and cross-sectional **momentum**: Moskowitz, Ooi, Pedersen
  (2012); Hurst, Ooi, Pedersen (2017); Asness, Moskowitz, Pedersen (2013);
  Goulding, Harvey, Mazzoleni (2023).

Specific to SA16, and to be judged as such:

1. **`SpanScaledVolatilitySignal`**: a volatility estimator with the declared
   `AVAILABLE_OBSERVATIONS` contract, which divides each return by the square
   root of the sessions it covers and refuses a gap of more than three
   sessions. Tested by hand, against the consecutive estimator without a gap,
   and against the future.
2. **"An input that cannot be read keeps the book"** instead of excluding the
   fund, the cause of the forced exits of SA15 in 2025–2026.
3. **The choice to diversify rather than forecast**, and its honest measure:
   two directional signals (absolute, relative) refuted over this period before
   retaining a rule without direction.

## 9. Limits

- **Retrospective**: the whole window was seen by SA1–SA15.
- **Universe chosen after the fact**: technology comes from SA15 R4, and SA15
  had already published constant technology/gold mixes ("companions" 55 and
  79). SA16 did not search for weights on the history: its 0.75 budget was set
  before the run and its 0.70/0.80 neighbours hold. But its return advantage
  depends on this choice (C2).
- **Concentration**: two lines, a US sector (a few large caps) and a gold ETC
  (issuer and custodian risk, not a UCITS). Not eligible for the PEA.
- **Exchange rate**: both funds are listed in euros but exposed to the dollar;
  nothing is hedged.
- **Gold lived through an exceptional period** (+34.6% in 2024, +49.3% in 2025
  in euros) which weighs on the recent result.
- **Data**: a single source (Yahoo for the funds), restated histories, no
  point-in-time vintages; two Xetra sessions missing.
- **Statistics**: the return difference is not significant; only 8.25 years.
- **Provenance**: some iteration runs carry `dirty = True`. The cause is the
  presence of untracked exports under `results/SA16` at the time of the run,
  the code tree being that of the commit named. The final rerun of the
  configuration retained is on a clean tree.

A prospective check remains the only possible proof (`research/PROTOCOL.md`,
section 6): configuration and store frozen, start at the first XPAR session
after the code is made available, reading after 252 sessions.

## 10. Reproduce

Linux, macOS or WSL (`fcntl` lock), Python 3.12, `uv`:

```bash
uv sync --frozen --extra stats
uv run python scripts/SA16_download_data.py           # runs/sa16_store, up to 2026-10-30
uv run python scripts/SA16_run_study.py reproduce      # SA15 and the Nasdaq against the SA15 archive
uv run python scripts/SA16_run_study.py references
for n in 01 02 03; do
    uv run python scripts/SA16_run_study.py candidate research/SA16/candidates/it$n.json
done
uv run python scripts/SA16_run_study.py robustness research/SA16/candidates/it02.json
uv run python scripts/SA16_run_study.py finalise research/SA16/candidates/it02.json
uv run python scripts/SA16_report.py
```

Use a new folder (`--output`) so as not to mix a rerun with the committed
exports: the script refuses to overwrite a different run in an existing
folder. Downloading again does not guarantee the same store (fingerprint of the
study `677397e6fb770978…`): the histories are restated by the provider.

| File | Content |
| --- | --- |
| `selected.json` | frozen configuration, fingerprint, check of the rerun |
| `register.csv` | the 13 trials counted (candidates, controls, neighbours) |
| `itNN/tables.md`, `itNN/report.json` | generated tables of each iteration |
| `itNN/x1/<book>/`, `x2/` | curves, weights, orders, fills, rejects, decisions |
| `references/`, `reproduction/` | the references over the SA16 window; the reproduction of SA15 |
| `robustness/SA16_it2/` | neighbours and restarts |
| `final/` | rerun of the configuration retained with the final code |
| `comparison.png`, `weights.png` | figures (`scripts/SA16_report.py`) |

## Archived exports (2026-10-31)

Of the files in the table above, the repository keeps `study.md`,
`selected.json`, the `tables.md` files and the figures. The others
(`register.csv`, the `report.json` files, the books under `x1/` and `x2/`,
`references/`, `reproduction/`, `final/` and the rest of `robustness/`)
are no longer tracked; they are in the results archive `quant-backtester-results-7a2205d.tar.gz`
(SHA-256 `475440c48634efec917ea1e0a11397cc2ac2b917e631d09f672346a60e8a0583`),
attached to the Release [`results-archive-2026-10-31`](https://github.com/paulrivaudd/quant-backtester/releases/tag/results-archive-2026-10-31).
Restore it before running `scripts/SA16_report.py` or
`scripts/SA16_run_study.py reproduce`: [ARCHIVE.md](../ARCHIVE.md) says how.
