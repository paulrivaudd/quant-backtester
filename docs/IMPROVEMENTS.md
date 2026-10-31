# Improvements still needed

State on 2026-09-26, after the answer to the archive audit (9). This list
records what still limits what a result can claim, by priority. The first
version of this note (`35cb750`) contained errors that the audit pointed out;
they are corrected below, and each item says what is done, what remains to be
done, and why.

Key: **P1** limits the validity of a result, **P2** limits its scope or its
reproducibility, **P3** is a matter of comfort or tooling.

## Done since the first version

| Item | What was done |
|---|---|
| 1.3 Execution model | `Sizing.AT_DECISION`: quantities set at the decision close, executed at the open, cut down to the cash available. `scripts/sensitivity.py`: the rotation loses 0.01 point with orders set the day before, nearly 4 points at doubled costs. That script and the rotation were removed from the code on 2026-10-11. |
| 2.1 Contested sessions | `metadata/conflict_reviews.toml`: the 13 conflicts are reviewed and settled in favour of Euronext, the listing venue, for the exact values reviewed. **The bar of 24 October 2025 cost 0.47 point, not the "about 4 points" I had written without measuring them.** |
| 3.1 Run folder | `research.archive`: a run reread offline without recomputation, and recomputable from a verified copy of the store it read. Removed from the code on 2026-10-11. |
| 3.2 Environment | The Python version, the hash of `uv.lock` and the versions of numpy, pandas, pyarrow and scipy go into the `run_id`. |
| 4.1 Uncertainty | `analytics.uncertainty`: a paired block bootstrap between the strategy and its executable control. Over the README's period, the interval of the Sharpe ratios excludes zero: the rotation's Sharpe is the lowest. |
| 4.2 Hypotheses and verdicts | `research/hypotheses.toml`: the 19 existing runs are declared `EXPLORATORY`. Verdicts are events, with no rewriting of a run and no extra variant. |
| 4.4 Executable comparator | The README suite compares the rotation with a buy & hold of the world fund subject to the same costs, lots and cash. |
| 5.1 Continuous integration | GitHub Actions: ruff, format, pyright and offline tests on every push, network tests every night. |
| Paper trading | `contract_id`, a journal of the complete economic state, committed code required, a session taken into account only once it is ready (23:00 Paris), journals under a lock. Removed from the code on 2026-10-11. |

## Corrections to the first version (archive audit 9)

- **1.5**: cash was **not** "penalised twice". The Sharpe ratio subtracts the risk-free rate once only. Unremunerated cash costs `(1 − w) × r_ref` as an opportunity cost; it is not a second deduction.
- **2.2**: US10Y is read by **no** current baseline (the gauge of `MomentumVix`, since removed from the code, was the VIX). Moving it to vintages moves no published figure.
- **2.5 and 4.5**: dated universes already exist, and the annual turnover and the average cash are already computed and shown in the report.
- **5.2**: paper trading must run after 23:00 Paris, the decision time, not "after the European close".
- **1.1**: a dividend on a held position is booked as a receivable on the ex-date, settled on payment. Cash on payment alone would create a false loss and then a false recovery.

## What remains

| # | Priority | Problem | What it would take |
|---|---|---|---|
| 1.1 | P1, before widening the universe | A split or a dividend on a held line stops the run. | Entitlement accounting: a receivable on the ex-date, settlement on payment, a split applied to quantities and average cost, declared withholding tax. |
| 1.2 | P1, before widening the universe | A delisting of a held line stops the run. | A policy declared case by case: buyout, last tradable price, recovery value. |
| 1.4 | P2 | No cap on participation in volume, and a single spread for every instrument. | A cap computed on a **past** volume (the day's volume is not known at the open), and a spread per instrument. |
| 1.5 | P3 | Cash earns nothing. | A declared deposit convention if one is wanted: rate obtained, accrued days, availability. It stays distinct from the Sharpe's reference rate. |
| 1.6 | P3 | Gross is an attribution at constant fills. | A run without fees as a counterfactual, under its own name. |
| 1.7 | P3 | A single account currency. | Cash accounts per currency and a valuation at the exchange rate available, before any non-euro asset. |
| 2.2 | P2, before any strategy that reads US10Y | US10Y is declared `RESTATED`. | ALFRED as `AS_OF_DECISION`. For a daily series this takes one vintage per business day, hence a storage dimension still to design. Since N08, every run that reads it says so in its report. |
| 2.3 | P2 | The Yahoo histories are `ASSUMED_UNREVISED` without proof. | A report of the revisions observed between downloads. Future refetches will prove nothing about the period before the first archive. |
| 2.4 | P2 | No second source covers ESE before 2024. | An independent historical source, for the periods actually to be used. |
| 2.5 | P2, before widening the universe | No dead security in the universes. | The data of the members that left: prices, events, dates. The dated-universe mechanism already exists. |
| 3.3 | P3 | No immutable generations of the store. | Run folders with a copy of the store cover the retention need. Generations would only be useful for a shared store. |
| 4.3 | P2 | No parameter sweep engine. | A declared grid, with rolling start dates and costs ×1 and ×2, each point entered in the register, and a budget of trials fixed in advance. |
| 4.6 | P3 | Signals S4/S5, `StrategyState`. | Only after 4.3, otherwise variants multiply that cannot be judged. |
| 5.3 | P2 | The scripts have no smoke tests. | Tests on a synthetic store: arguments, outputs, exit codes, double launch. |
| 5.4 | P3 | French exercise notes remain in English docstrings. | Rewrite them when those files are taken up again. |
