# SA17 — market-adjusted sector momentum

Checkpoint, 2026-11-07: **the rule and its controls are implemented and tested
offline. Data is not acquired yet, and nothing has been run on market data.**
No SA17 performance has been calculated. The proposal stays
`PROPOSED / NOT_TESTED`. The data audit's `INSUFFICIENT_EVIDENCE` is about the
inputs available on 2026-11-01, not a verdict on the mechanism.

## Where it stands

| Step | State | Where |
| --- | --- | --- |
| Proposal | Written 2026-11-01, unchanged | [proposal.md](proposal.md) |
| Data audit | `INSUFFICIENT_EVIDENCE` for the 1999–2018 study; local store inventoried | [data_audit.md](data_audit.md), [local_inventory.json](local_inventory.json), [`SA17_audit_data.py`](../../scripts/SA17_audit_data.py) |
| Acquisition registry | Ten Xetra EUR sector funds, declared 2026-11-02; every listing checked against the issuer on 2026-11-07; real estate missing | [source_instruments.toml](source_instruments.toml), [sourcing_20261102.md](sourcing_20261102.md) |
| Acquisition script | Written and tested offline; **not run**, so there is no `runs/sa17_store` | [`SA17_download_data.py`](../../scripts/SA17_download_data.py) |
| Signal | `MonthlyMomentumSignal`: residual or total-return momentum on month-end closes | [`signals/cross_asset/residual_momentum.py`](../../src/quant_backtester/signals/cross_asset/residual_momentum.py) |
| Strategy and its sector controls | `SA17SectorResidualMomentum`, catalogued `SA17 - sector residual momentum`; `controls()` builds the four sector controls | [`strategies/SA17_sector_residual_momentum.py`](../../src/quant_backtester/strategies/SA17_sector_residual_momentum.py) |
| Hypothesis, executable protocol, study script | Not written | — |

## The rule as implemented

The proposal's table maps to the code as follows. Where the proposal left a
detail open, the choice the code makes is stated here; each one can be read
in the strategy's `definition()`.

- **Months.** A decision reads the month it is taken in, to date, and the 36
  calendar months before it. On each fund's own venue, a month ends at the
  last session on or before its last calendar day. That session's close must
  be in the history. A month end the provider did not serve is
  `MISSING_INPUT`; it is never replaced by the session before it. A hole
  inside a month is not read. The definition names this window
  `EXPECTED_MONTH_END_SESSIONS`, not consecutive sessions.
- **Score.** Simple monthly returns of adjusted closes, which equal the quoted
  closes for these accumulating funds; they are not total-return indices. The
  OLS fit with a constant uses all 36 months. The score is the mean of the
  residuals of months *t−11 … t−1*, divided by their sample standard deviation
  (`ddof=1`). A residual with no dispersion is `INVALID_INPUT`.
- **Selection.** The three best scores, ties to the smaller fund identifier,
  in equal thirds of the equity sleeve, even when every score is negative.
- **Risk.** `g = min(1, 0.15 / σ)`, with `σ = sqrt(252 · w′Cw)`. `C` is the
  sample covariance of the last 63 daily simple returns of the three selected
  funds. Each fund needs 64 consecutive closes on its venue, on the same
  sessions as the others. `σ = 0` gives `g = 1`. The rest, `1 − g`, goes to
  the monetary fund, or stays in cash when none is declared or it cannot be
  held yet. The book is restated monthly, with no band.
- **Eligibility and failures.** A sector that is not listed, not in the
  session's universe, or short of the 37 month ends is not eligible yet. That
  is decided before the freshness of its latest close, so a young fund's late
  bar does not cancel anything.
  Fewer than three eligible sectors put the book in the monetary fund. Any
  other unreadable input, including a covariance window, keeps the book with
  no order; only a line that has left the universe is sold. A reduced universe
  is never ranked silently.
- **Freshness.** Closes may be one Paris session old. Xetra is shut on
  31 December while Paris trades, and a stricter limit would cancel every
  December decision.
- **Controls** (`SA17SectorResidualMomentum.controls()`), each run as a book
  of its own:
  - ranking on the 12−1 total return over the same months;
  - the candidate without its volatility target;
  - every eligible sector in equal parts;
  - every eligible sector in equal parts under the same target.

  All four share the candidate's eligibility: the same history requirement,
  the market read as a gate (a market that cannot be read stops every book,
  not only the candidate), and at least three eligible sectors before they
  invest. Only a residual with no dispersion, which the candidate alone
  computes, can stop the candidate and not its controls.

The tests check:

- hand-computed values, and the fit against `numpy.linalg.lstsq`;
- the covariance against `numpy.cov`;
- every status, and the look-ahead guard (future prices change nothing);
- full engine runs at month ends for the candidate and its controls, on a
  synthetic market.

## Decisions still open

These are parameters of the code, not choices it makes. They have to be fixed
in a protocol committed **before** any run on the store:

- **The market factor** (`market_id`, required, no default). The proposal
  wants S&P 500 total returns in USD. The local `SP500` is a price index, so
  it does not qualify. Either a total-return series is acquired, or a proxy
  (an EUR-listed S&P 500 fund, say) is declared as one, with the FX
  consequence stated: the market correction then mixes in `(1 − β)` times the
  EUR/USD move.
- **The monetary fund** (`monetary_id`). XEON (`ETF_MONETARY_EUR`) is in
  `runs/sa16_store` but not in the SA17 acquisition registry. The same holds
  for any market factor, and for the instruments of the external references.
- **Signal inputs** (`signal_input_ids`). Each fund is scored on its own closes
  unless USD sector series are acquired for the signal.
- **The window.** The earliest full 36-month window is the end of July 2018
  for nine sectors and the end of August 2021 for communication services
  (arithmetic on listing dates; see the sourcing note). The common window
  with every control has not been fixed.
- **The external references.** SA16_it2, the fixed 2/3 technology and 1/3 gold
  book (C1), and Nasdaq held. They are existing classes (`SA16RiskBudget`,
  `FixedWeights`, `BuyAndHold`); their wiring belongs to the study script.

## Next steps

1. Run the acquisition in the POSIX environment and read its coverage report:
   `uv run python scripts/SA17_download_data.py`. It writes only to
   `runs/sa17_*`.
2. Settle the open decisions above. Then write the hypothesis in
   `research/hypotheses.toml` and the executable protocol, and commit both
   before the first run.
3. Write the study script. It runs the candidate, its four controls and the
   external references, at ×1 and ×2 costs.

## Reproduce and test

From the project root, in the POSIX Python 3.12 environment (the store needs
`fcntl`):

```bash
uv run pytest tests/signals/cross_asset/test_residual_momentum.py \
    tests/strategies/test_SA17_sector_residual_momentum.py \
    tests/scripts/test_SA17_audit_data.py tests/scripts/test_SA17_download_data.py
uv run python scripts/SA17_audit_data.py --store runs/sa16_store > /tmp/sa17-audit.json
cmp research/SA17/local_inventory.json /tmp/sa17-audit.json
```
