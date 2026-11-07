# SA17 — mechanism study on Ken French industries

Run from the design frozen in [protocol.md](../../../research/SA17/protocol.md)
("Mechanism study: frozen design") and
[mechanism.toml](../../../research/SA17/mechanism.toml), committed before any
score was computed on these files. Retrospective replication on heavily
studied research portfolios: not an executable ETF result, not a discovery.

- Commit: `98da1efcdedc7fed19ae23fd46cd97cabe17a55b` (CLEAN); configuration sha256 `e108adcebe90e56f…`
- Holding months: 1929-07 to 2026-09
- Costs: 10 bp one way (declared), x2 (stressed); hypothetical
- Inference: paired stationary bootstrap of monthly excess returns, mean block 12 months, 10,000 draws, seed 20261107, 95% percentile intervals; Holm within {vs C1, vs C2}

## Verdicts

| Comparison | Question | Verdict |
| --- | --- | --- |
| RESIDUAL vs C1_MOMENTUM_12_1 | Does the market adjustment beat plain 12-1 momentum? | **UNCERTAIN** |
| RESIDUAL vs C2_EQUAL_WEIGHT | Does the selection beat holding every industry? | **SUPPORTED_RETROSPECTIVE** |

Read on INDUSTRY_10 at declared costs. Everything below that is not this table is reported in full and changes no verdict.

## INDUSTRY_10 (primary, top 3 of 10)

1167 formations; eligible industries per month 10 to 10; fits refused 0.

| Book | Costs | Sharpe (excess) | Sharpe gross | CAGR | CAGR gross | Vol | Max DD | Turnover/yr | Cost/yr | Months at RF | Missing held |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| RESIDUAL | declared | 0.54 | 0.57 | 12.31% | 13.00% | 18.78% | -78.34% | 6.15 | 0.62% | 0 | 0 |
| C1_MOMENTUM_12_1 | declared | 0.54 | 0.57 | 12.07% | 12.65% | 18.26% | -74.24% | 5.14 | 0.51% | 0 | 0 |
| C2_EQUAL_WEIGHT | declared | 0.46 | 0.46 | 10.35% | 10.38% | 17.89% | -81.93% | 0.29 | 0.03% | 0 | 0 |
| RESIDUAL | stressed | 0.51 | 0.57 | 11.62% | 13.00% | 18.78% | -78.60% | 6.15 | 1.23% | 0 | 0 |
| C1_MOMENTUM_12_1 | stressed | 0.51 | 0.57 | 11.50% | 12.65% | 18.25% | -74.55% | 5.14 | 1.03% | 0 | 0 |
| C2_EQUAL_WEIGHT | stressed | 0.46 | 0.46 | 10.32% | 10.38% | 17.89% | -81.95% | 0.29 | 0.06% | 0 | 0 |
| MARKET | none | 0.42 | n/a | 9.79% | n/a | 18.43% | -83.65% | n/a | n/a | n/a | n/a |

### The candidate against its controls (declared costs)

| Control | Sharpe diff | 95% interval | p | Holm p | Sharpe diff x2 | Active mean | Tracking error | IR | Verdict |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| C1_MOMENTUM_12_1 | 0.001 | [-0.060, 0.068] | 0.9861 | 0.9861 | -0.004 | 0.30% | 6.29% | 0.05 | UNCERTAIN |
| C2_EQUAL_WEIGHT | 0.081 | [0.017, 0.147] | 0.0136 | 0.0272 | 0.050 | 1.95% | 6.45% | 0.30 | SUPPORTED_RETROSPECTIVE |
| MARKET (description) | | | | | | 2.36% | 6.90% | 0.34 | — |

### Sensitivities, never selected

| Control | Statistic | Mean block | Estimate | 95% interval | p |
| --- | --- | ---: | ---: | --- | ---: |
| C1_MOMENTUM_12_1 | SHARPE | 12 | 0.001 | [-0.060, 0.068] | 0.9861 |
| C1_MOMENTUM_12_1 | MEAN_RETURN | 12 | 0.295% | [-0.877%, 1.469%] | 0.6285 |
| C1_MOMENTUM_12_1 | SHARPE | 6 | 0.001 | [-0.064, 0.069] | 0.9844 |
| C1_MOMENTUM_12_1 | MEAN_RETURN | 6 | 0.295% | [-0.943%, 1.535%] | 0.6399 |
| C1_MOMENTUM_12_1 | SHARPE | 24 | 0.001 | [-0.057, 0.066] | 0.9836 |
| C1_MOMENTUM_12_1 | MEAN_RETURN | 24 | 0.295% | [-0.808%, 1.372%] | 0.5892 |
| C2_EQUAL_WEIGHT | SHARPE | 12 | 0.081 | [0.017, 0.147] | 0.0136 |
| C2_EQUAL_WEIGHT | MEAN_RETURN | 12 | 1.949% | [0.750%, 3.205%] | 0.0021 |
| C2_EQUAL_WEIGHT | SHARPE | 6 | 0.081 | [0.012, 0.150] | 0.0210 |
| C2_EQUAL_WEIGHT | MEAN_RETURN | 6 | 1.949% | [0.657%, 3.246%] | 0.0037 |
| C2_EQUAL_WEIGHT | SHARPE | 24 | 0.081 | [0.020, 0.140] | 0.0077 |
| C2_EQUAL_WEIGHT | MEAN_RETURN | 24 | 1.949% | [0.812%, 3.133%] | 0.0010 |

### Regimes (declared costs, descriptive)

| Regime | Book | Sharpe (excess) | CAGR | Max DD |
| --- | --- | ---: | ---: | ---: |
| 1929-1969 | RESIDUAL | 0.50 | 10.65% | -78.34% |
| 1929-1969 | C1_MOMENTUM_12_1 | 0.53 | 10.88% | -74.24% |
| 1929-1969 | C2_EQUAL_WEIGHT | 0.42 | 8.76% | -81.93% |
| 1929-1969 | MARKET | 0.38 | 7.95% | -83.65% |
| 1970-1999 | RESIDUAL | 0.55 | 15.18% | -46.83% |
| 1970-1999 | C1_MOMENTUM_12_1 | 0.55 | 15.32% | -42.29% |
| 1970-1999 | C2_EQUAL_WEIGHT | 0.49 | 13.63% | -45.59% |
| 1970-1999 | MARKET | 0.47 | 13.51% | -46.51% |
| 2000-2017 | RESIDUAL | 0.52 | 8.71% | -40.73% |
| 2000-2017 | C1_MOMENTUM_12_1 | 0.48 | 7.78% | -39.60% |
| 2000-2017 | C2_EQUAL_WEIGHT | 0.48 | 7.60% | -48.09% |
| 2000-2017 | MARKET | 0.35 | 5.84% | -50.31% |
| 2018-2026 | RESIDUAL | 0.84 | 17.95% | -19.65% |
| 2018-2026 | C1_MOMENTUM_12_1 | 0.69 | 15.73% | -21.87% |
| 2018-2026 | C2_EQUAL_WEIGHT | 0.63 | 12.39% | -22.93% |
| 2018-2026 | MARKET | 0.72 | 14.13% | -24.84% |

## INDUSTRY_49 (robustness, top 15 of 49)

1167 formations; eligible industries per month 40 to 49; fits refused 0.

| Book | Costs | Sharpe (excess) | Sharpe gross | CAGR | CAGR gross | Vol | Max DD | Turnover/yr | Cost/yr | Months at RF | Missing held |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| RESIDUAL | declared | 0.53 | 0.56 | 12.69% | 13.36% | 20.48% | -80.25% | 5.93 | 0.59% | 0 | 1 |
| C1_MOMENTUM_12_1 | declared | 0.59 | 0.61 | 13.75% | 14.28% | 19.81% | -77.59% | 4.58 | 0.46% | 0 | 1 |
| C2_EQUAL_WEIGHT | declared | 0.44 | 0.44 | 10.61% | 10.65% | 20.33% | -84.45% | 0.41 | 0.04% | 0 | 1 |
| RESIDUAL | stressed | 0.50 | 0.56 | 12.02% | 13.36% | 20.47% | -80.54% | 5.93 | 1.19% | 0 | 1 |
| C1_MOMENTUM_12_1 | stressed | 0.57 | 0.61 | 13.23% | 14.28% | 19.80% | -77.81% | 4.58 | 0.92% | 0 | 1 |
| C2_EQUAL_WEIGHT | stressed | 0.44 | 0.44 | 10.56% | 10.65% | 20.33% | -84.48% | 0.41 | 0.08% | 0 | 1 |
| MARKET | none | 0.42 | n/a | 9.79% | n/a | 18.43% | -83.65% | n/a | n/a | n/a | n/a |

### The candidate against its controls (declared costs)

| Control | Sharpe diff | 95% interval | p | Holm p | Sharpe diff x2 | Active mean | Tracking error | IR |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| C1_MOMENTUM_12_1 | -0.060 | [-0.104, -0.013] | 0.0085 | 0.0085 | -0.066 | -0.84% | 4.90% | -0.17 |
| C2_EQUAL_WEIGHT | 0.090 | [0.037, 0.150] | 0.0032 | 0.0064 | 0.063 | 1.92% | 5.33% | 0.36 |
| MARKET (description) | | | | | | 3.02% | 6.78% | 0.45 |

### Sensitivities, never selected

| Control | Statistic | Mean block | Estimate | 95% interval | p |
| --- | --- | ---: | ---: | --- | ---: |
| C1_MOMENTUM_12_1 | SHARPE | 12 | -0.060 | [-0.104, -0.013] | 0.0085 |
| C1_MOMENTUM_12_1 | MEAN_RETURN | 12 | -0.841% | [-1.790%, 0.135%] | 0.0843 |
| C1_MOMENTUM_12_1 | SHARPE | 6 | -0.060 | [-0.107, -0.014] | 0.0126 |
| C1_MOMENTUM_12_1 | MEAN_RETURN | 6 | -0.841% | [-1.856%, 0.188%] | 0.1026 |
| C1_MOMENTUM_12_1 | SHARPE | 24 | -0.060 | [-0.100, -0.015] | 0.0064 |
| C1_MOMENTUM_12_1 | MEAN_RETURN | 24 | -0.841% | [-1.718%, 0.048%] | 0.0644 |
| C2_EQUAL_WEIGHT | SHARPE | 12 | 0.090 | [0.037, 0.150] | 0.0032 |
| C2_EQUAL_WEIGHT | MEAN_RETURN | 12 | 1.921% | [0.818%, 3.055%] | 0.0008 |
| C2_EQUAL_WEIGHT | SHARPE | 6 | 0.090 | [0.036, 0.148] | 0.0015 |
| C2_EQUAL_WEIGHT | MEAN_RETURN | 6 | 1.921% | [0.793%, 3.060%] | 0.0012 |
| C2_EQUAL_WEIGHT | SHARPE | 24 | 0.090 | [0.034, 0.153] | 0.0027 |
| C2_EQUAL_WEIGHT | MEAN_RETURN | 24 | 1.921% | [0.780%, 3.081%] | 0.0010 |

### Regimes (declared costs, descriptive)

| Regime | Book | Sharpe (excess) | CAGR | Max DD |
| --- | --- | ---: | ---: | ---: |
| 1929-1969 | RESIDUAL | 0.52 | 11.89% | -80.25% |
| 1929-1969 | C1_MOMENTUM_12_1 | 0.60 | 13.38% | -77.59% |
| 1929-1969 | C2_EQUAL_WEIGHT | 0.44 | 9.81% | -84.45% |
| 1929-1969 | MARKET | 0.38 | 7.95% | -83.65% |
| 1970-1999 | RESIDUAL | 0.53 | 15.70% | -36.70% |
| 1970-1999 | C1_MOMENTUM_12_1 | 0.58 | 16.45% | -35.15% |
| 1970-1999 | C2_EQUAL_WEIGHT | 0.37 | 12.18% | -49.55% |
| 1970-1999 | MARKET | 0.47 | 13.51% | -46.51% |
| 2000-2017 | RESIDUAL | 0.50 | 8.73% | -54.50% |
| 2000-2017 | C1_MOMENTUM_12_1 | 0.58 | 10.00% | -49.54% |
| 2000-2017 | C2_EQUAL_WEIGHT | 0.55 | 9.41% | -52.66% |
| 2000-2017 | MARKET | 0.35 | 5.84% | -50.31% |
| 2018-2026 | RESIDUAL | 0.71 | 14.52% | -20.92% |
| 2018-2026 | C1_MOMENTUM_12_1 | 0.67 | 14.20% | -23.26% |
| 2018-2026 | C2_EQUAL_WEIGHT | 0.55 | 11.40% | -25.95% |
| 2018-2026 | MARKET | 0.72 | 14.13% | -24.84% |

## What this does not show

- These are SIC research portfolios of the broad CRSP market, restated, not
  point-in-time and not tradable. The costs are a declared hypothesis.
- Industry momentum and residual momentum are published; the 10 and 49
  industries are among the most used series in finance. This tests whether
  SA17's score behaves as the literature says on this data, not a new edge.
- It tests monthly selection only, not SA17's daily volatility sizing, and
  says nothing about the executable ETF book, which has its own gates.
