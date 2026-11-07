# SA17 — market-adjusted sector momentum

## Correction NAV/USD, 2026-11-07

The authoritative contract is now [protocol.md](protocol.md), written before
any SA17 performance run. The original acquisition below is preserved as
evidence; it is not an admitted strategy input set.

- All ten official USD NAV histories have been acquired, with ISIN and currency
  checks: [source evidence](nav_source_evidence.json). They replace exchange
  closes for ranking and risk inputs. Execution still needs exchange prices.
- Sector and market observations use the same XNYS dates, in USD. EUR/USD never
  enters the ranking. Risk has separate NAV inputs and explicit synchronized FX
  conversion to EUR; ECB and issuer WM16-London reference NAVs do not qualify.
- Publication is distinct from valuation: all supplements state 22:15 Dublin,
  later than the 23:00 Paris decision. The historical workbooks provide no
  release timestamps. Normalization initially permits use only after retrieval.
- Monthly sampling now defaults to the previous completed US month with an
  explicit common observation cutoff. It no longer pairs Xetra and New York
  month-end prints or implicitly takes a partial current month.
- [Ken French source evidence](ken_french_source_evidence.json) covers monthly
  10/49-industry portfolios and matching factors since July 1926. This is a
  separate restated research study, not executable ETF history.
- [Costs](costs.toml) distinguish per-fund assumptions from observed quotes.
  [Power](power.json) distinguishes the ~0.68 significance threshold from the
  ~0.98 true IR needed for 80% power over 8.25 years under IID assumptions.

No performance or selection is published. Historical publication coverage,
synchronous FX and executable-price gaps remain admission requirements.

Checkpoint, 2026-11-07: **the rule and its controls are implemented and tested
offline. The data is acquired in `runs/sa17_store`. No strategy has been run on
it.** No SA17 performance has been calculated; the only figures read from the
store are the data checks [below](#acquisition-2026-11-07). The proposal stays
`PROPOSED / NOT_TESTED`. The data audit's `INSUFFICIENT_EVIDENCE` is about the
inputs available on 2026-11-01, not a verdict on the mechanism.

## Where it stands

| Step | State | Where |
| --- | --- | --- |
| Proposal | Written 2026-11-01, unchanged | [proposal.md](proposal.md) |
| Data audit | `INSUFFICIENT_EVIDENCE` for the 1999–2018 study; local store inventoried | [data_audit.md](data_audit.md), [local_inventory.json](local_inventory.json), [`SA17_audit_data.py`](../../scripts/SA17_audit_data.py) |
| Acquisition registry | Ten Xetra EUR sector funds, declared 2026-11-02; every listing checked against the issuer on 2026-11-07; real estate missing. The market factor `SP500TR` was added 2026-11-07, before the download | [source_instruments.toml](source_instruments.toml), [sourcing_20261102.md](sourcing_20261102.md) |
| Acquisition | **Run 2026-11-07**: 16 series, every one validated with no error; `runs/sa17_store` | [`SA17_download_data.py`](../../scripts/SA17_download_data.py), [below](#acquisition-2026-11-07) |
| Signal | `MonthlyMomentumSignal`: residual or total-return momentum on month-end closes | [`signals/cross_asset/residual_momentum.py`](../../src/quant_backtester/signals/cross_asset/residual_momentum.py) |
| Strategy and its sector controls | `SA17SectorResidualMomentum`, catalogued `SA17 - sector residual momentum`; `controls()` builds the four sector controls | [`strategies/SA17_sector_residual_momentum.py`](../../src/quant_backtester/strategies/SA17_sector_residual_momentum.py) |
| Hypothesis, executable protocol, study script | Not written | — |

## Original rule before the NAV correction (superseded)

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

## Acquisition, 2026-11-07

`uv run python scripts/SA17_download_data.py` ran in the POSIX clone from this
checkpoint's files, with the cutoff at 2026-10-30.

- **The store.** `runs/sa17_store` (not committed; `runs/` is ignored) has
  store digest `e67335cd9a186b07d66513e99897f8513f3bde8ec9857f4cb67b82f282926b4b`.
  The evidence file is `reports/acquisition_20261107T154101219801Z.json`.
- **The registry.** The store's registry concatenates the project registry,
  the two SA15 registries and [source_instruments.toml](source_instruments.toml).
  It is pinned by `metadata_sha256.json`. Any later change to the registry or
  to `market_data/metadata` needs a new `runs/sa17_*` store; the script
  refuses to rewrite this one.

All 16 series validated with no error:

| Series | Role | Symbol | From | Sessions to 2026-10-30 | Venue sessions missing |
| --- | --- | --- | --- | --- | --- |
| Nine sector funds | sectors | `ZPDE.DE` … `ZPDU.DE` | 2015-07-08 | 2,872 each | 2025-10-24, 2026-03-06 |
| `SA17_ETF_COMMUNICATION` | sector | `ZPDK.DE` | 2018-08-16 | 2,083 | the same two |
| `SP500TR` | market factor | `^SP500TR` | 2014-01-02 | 3,227 | none |
| `ETF_MONETARY_EUR` | monetary fund | `XEON.DE` | 2014-01-02 | 3,255 | none |
| `ECB_EURUSD` | EUR/USD reference rate | ECB | 2014-01-02 | 3,284 fixings | not computed (no TARGET calendar here) |
| `ETF_US_TECH` | SA16_it2, C1 | `QDVE.DE` | 2017-01-02 | 2,493 | 2025-10-24, 2026-03-06 |
| `ETF_GOLD` | SA16_it2, C1 | `4GLD.DE` | 2018-01-02 | 2,241 | the same two |
| `ETF_NASDAQ` | Nasdaq held | `SXRV.DE` | 2014-01-02 | 3,255 | none |

`ETF_GOLD` starts on 2018-01-02, as in SA16: its 2014–2017 archive holds two
invalid bars. XEON, QDVE, Xetra-Gold and SXRV came back with bars identical to
`runs/sa16_store`, session for session. The checks of the market factor
(gross dividends) are in the
[sourcing note](sourcing_20261102.md#the-market-factor-and-the-reused-declarations-2026-11-07).

What the coverage shows, read from volumes, dates and the calendar only:

- **Yahoo reports frequent zero volumes before 2021.** This does not prove
  absence of exchange trades, executable quotes or market-maker liquidity.
  It also does not establish that the reported open was executable. The
  validator only warns on
  these bars (`FLAT_ZERO_VOLUME`) and refuses none. Share of sessions with zero
  volume, by year:

  | Year | Energy | Materials | Industrials | Discretionary | Staples | Health | Financials | Technology | Communication | Utilities |
  | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
  | 2015 | 28 % | 67 % | 89 % | 67 % | 71 % | 49 % | 60 % | 63 % | — | 43 % |
  | 2016 | 8 % | 49 % | 62 % | 56 % | 37 % | 40 % | 39 % | 37 % | — | 11 % |
  | 2017 | 6 % | 59 % | 35 % | 65 % | 52 % | 18 % | 1 % | 15 % | — | 41 % |
  | 2018 | 5 % | 56 % | 19 % | 36 % | 25 % | 12 % | 6 % | 2 % | 27 % | 16 % |
  | 2019 | 4 % | 43 % | 29 % | 16 % | 12 % | 0 % | 2 % | 1 % | 1 % | 5 % |
  | 2020 | 1 % | 23 % | 6 % | 3 % | 1 % | 0 % | 2 % | 0 % | 0 % | 2 % |
  | 2021 on | ≤ 1 % | ≤ 2 % | ≤ 1 % | ≤ 1 % | ≤ 1 % | ≤ 1 % | ≤ 1 % | ≤ 1 % | ≤ 2 % | ≤ 3 % |

  The signal reads month-end closes, and month ends without a trade are
  common in the early years. Over 2015–2019 they number 4, 9, 7, 9 and 7 a
  year for materials; industrials had 7 in 2019, and discretionary 10 in 2017.
  From 2021 on, there are four in all: utilities twice in 2021, materials
  and communication services once each in 2023. Zero-volume sessions remain,
  but rare: at most 3 % a year for any fund. Among them, 2023-12-04 to 06 are
  flat on every fund at once, the provider outage the project registry
  already records for its Xetra funds. The engine fills at the open whatever
  the volume; it has no participation limit.
- **Two Xetra sessions are missing.** 2025-10-24 and 2026-03-06 are absent from
  every fund served at those dates except XEON and SXRV. These are the
  Yahoo gaps `known_gaps.toml` documents for the SA7 funds. For the SA17 funds
  they are not reviewed and stay `SESSION_GAP` warnings. Neither is a month
  end, so the signal is unaffected. The covariance window is affected: it
  originally needed 64 consecutive Xetra closes. By calendar arithmetic, the month-end
  decisions of October, November and December 2025 and of March, April and
  May 2026 span one of the two dates. This was a defect of using exchange
  prints for risk: the corrected contract reads separate NAV/FX inputs and
  reconciles validated sources before treating an input as missing. Actual
  execution-price gaps are still separate and cannot be filled with NAVs.

## Remaining admission requirements

USD NAVs and the market have been acquired; no mixed-currency regression or
ECB conversion is an alternative. The two Yahoo gap dates are present in all
ten NAV histories. However, [calendar coverage](nav_calendar_coverage.json)
also identifies US sessions without a fund NAV: 26 dates for nine funds,
18 for communications, through 2026-10-30. These include European holidays.
Official fund dealing calendars must distinguish nonvaluation days from
provider failures. No forward fill or silent deletion of expected US dates.

Historical publication coverage, synchronous EUR/USD observations, fund actions,
and valid execution prices remain unresolved. The new retrieval-dated NAV store
is `runs/sa17_nav_store_20261107_v3`; its normalized inputs are deliberately
unavailable to historical decisions. The old exchange store is preserved.

## Next steps

1. Resolve the documented data admission requirements. The hypothesis and
   corrected protocol are written; no performance run is authorized by a
   successful acquisition alone.
2. Freeze the executable schedule and complete input provenance before running
   the candidate, its four controls and external references at ×1 and ×2 costs.
   Ken French remains a separate retrospective mechanism study.

## Reproduce and test

From the project root, in the POSIX Python 3.12 environment (the store needs
`fcntl`):

```bash
uv run pytest tests/signals/cross_asset/test_residual_momentum.py \
    tests/strategies/test_SA17_sector_residual_momentum.py \
    tests/scripts/test_SA17_audit_data.py tests/scripts/test_SA17_download_data.py
uv run python scripts/SA17_audit_data.py --store runs/sa16_store > /tmp/sa17-audit.json
cmp research/SA17/local_inventory.json /tmp/sa17-audit.json
# the coverage report of an existing store, without downloading
uv run python scripts/SA17_download_data.py --coverage-only
```

A fresh download fetches today's provider snapshot, not the one of
2026-11-07. Run it into a new store (`--store runs/sa17_<name>`), never over
this one.
