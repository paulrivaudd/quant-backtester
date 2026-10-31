# Case study: why none of my strategies beats a rebalanced 50/50

## The question

Do the ten timing and allocation rules of the common ranking (SA1 to SA11,
SA8 aside) do better, net of costs, than a passive basket held half in a World
fund (CW8) and half in an S&P 500 fund (ESE), rebalanced? SA12 to SA14 have
studies of their own, outside this ranking.

## The protocol

- **The same ground for all**: 2021-04-01 → 2026-10-09 (1,416 valuations),
  EUR 100,000, a 5 bp commission (minimum EUR 1), a 3 bp half-spread, 2 bp of
  slippage, quantities set at the 23:00 Paris decision and executed at the
  next open ([summary](../results/summary/README.md)).
- **Point in time**: a decision reads only what was published at its instant;
  a window with a hole is refused, never filled ([architecture](ARCHITECTURE.md)).
- **Doubled costs**: every book is replayed a second time with every cost
  multiplied by two ([`ranking_costs_x2.csv`](../results/summary/ranking_costs_x2.csv)).
- **Deflated Sharpe**: the `QUALITY_V1` score is deflated by the eleven trials
  of the study ([protocol](../research/PROTOCOL.md)).

## The figures

Taken from [`ranking.csv`](../results/summary/ranking.csv) and
[`ranking_costs_x2.csv`](../results/summary/ranking_costs_x2.csv):

| Book | Annualised return | Sharpe | Max drawdown | Annualised return, costs ×2 | Sharpe, costs ×2 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 50/50 rebalanced (reference) | 13.71% | 0.96 | −22.47% | 13.65% | 0.96 |
| SA6 - vol control | 9.78% | 0.90 | −15.72% | 9.55% | 0.88 |
| SA10 - ensemble | 5.16% | 0.86 | −11.76% | 4.80% | 0.80 |
| SA7 - factor blend | 8.90% | 0.83 | −16.36% | 8.59% | 0.80 |
| SA3 - smooth MA | 8.62% | 0.79 | −21.64% | 8.50% | 0.79 |
| World held (yardstick) | 12.83% | 0.93 | −21.64% | 12.79% | 0.93 |

The 50/50 ranks first (score 77.9%), ahead of the best control (53.6%) and
of the best strategy, SA6 (52.0%).

## The interpretation

- **The rules invest less.** Average exposure: 84.7% for SA6, 71.5% for SA3,
  42.4% for SA10, against 99.8% for the 50/50 (`average_exposure`,
  ranking.csv). A lower maximum drawdown bought with cash is not skill; the
  protocol puts it this way: "A lower drawdown bought with more cash is
  exposure, not skill".
- **Timing does not beat a constant target.** Against a control that aims at
  their average weights with the same band, SA3 (0.79) and SA10 (0.86) do
  worse than theirs (0.93 each), and SA6 and SA11 gain about three points of
  maximum drawdown for a lower Sharpe
  ([diagnostics](../results/summary/diagnostics.md)).
- **A better risk model is not enough.** SA11's GARCH forecasts variance
  better than SA6's estimator, but its Sharpe is not higher: 95% intervals of
  the difference of [−0.141; +0.076] against SA6 and [−0.147; +0.009] against
  the EWMA, and its costs are 2.5 times SA6's
  ([SA11/study.md](../results/SA11/study.md)).
- **Doubled costs reverse nothing**: the 50/50 keeps its Sharpe of 0.96 and
  its first place; the active rules, which trade more, lose more.

## The limits

The whole period had already been examined: these figures are retrospective,
not out of sample. Two funds make a very thin cross-section, over a single
period of five and a half years. The SA15 and SA16 studies are measured
against other references (Nasdaq-100 held, SA15) over other windows; they are
not read in this table ([SA16](../results/SA16/study.md)).

## What comes next

The only evidence left is the future: a strategy kept under observation is
frozen (configuration and store), starts at the first session after it is made
available, with no real money, and is not read before 252 sessions
([protocol](../research/PROTOCOL.md), section 6).
