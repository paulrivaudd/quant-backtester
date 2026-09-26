# Changelog

## 0.2.0 — 2026-09-26

The fixes of two audits of 2026-09-26: the first (A01–A18, decisions D1–D10)
and the audit of those fixes (R01–R11, decisions D11–D16). The figures of the
README are unchanged to the printed precision; the run records they come from
are archived with the state of the store that produced them.

### Migrating from 0.1.0

| 0.1.0 | 0.2.0 | What to do |
|---|---|---|
| Any platform with Python 3.12 | POSIX only: Linux, macOS, WSL | Run under WSL on Windows. The store is locked with `flock`. |
| `PriceBasis.TOTAL_RETURN` | `PriceBasis.ADJUSTED` | Rename. The series is an adjusted price (`1 - D / C_prev`), not a reinvested wealth. |
| `reader.total_return_history(...)` | `reader.adjusted_history(...)` | Rename. |
| `BenchmarkSpec(..., price_basis=PriceBasis.RAW)` | `BenchmarkSpec(..., basis=BenchmarkBasis.PRICE_RETURN)` | Migrate. A price-return benchmark now neutralises splits. |
| `BenchmarkSpec(..., price_basis=PriceBasis.TOTAL_RETURN)` | `basis=BenchmarkBasis.TOTAL_RETURN` (the default) | Migrate. Dividends are reinvested at the ex-date close. |
| `instruments.toml` entries | `history_basis` and `history_note` required | Declare both for every instrument, custom registries included. |
| `metadata/` | `known_gaps.toml` required | Commit one, empty if nothing is known. |
| `MarketDataUpdater(...)` | `known_gaps=` required | Pass `KnownGaps.from_toml(...)`. |
| `schedule.decision_sessions(sessions)` | `decision_sessions(sessions, following=...)` | Pass the calendar's next session, or `None` at the end of its coverage. |
| `StrategyResult(...)` built by hand | `data_state` required | Build results through `StrategyRunner`. |
| `RunQuality(...)` built by hand | `max_realised_weight` required | Build it with `RunQuality.of`. |
| `HistoryCoverage.complete` (ends only) | `spans_declared_window` (ends only); `complete` counts every session | Use the one you mean. |
| `BenchmarkCurve.equity` was a stored series | A new series on every read | Nothing to do; mutating it no longer changes the result. |
| `ctx.keep_and_buy({name: weight})` | `ctx.keep_and_buy({name: share of cash})` | The values are now shares of the cash at the next open. |
| `clean/vintages/*.parquet` without `withdrawn` | Refused with `StoreFormatError` | Rebuild from `raw/` (`--rebuild --only <id>`). |
| A session only a check source serves | Not served; reported `SECONDARY_ONLY_SESSION` | Nothing to do; the checked series covers the primary's sessions. |
| The table's `trades` column | `rebal.` and `fills` | Read `rebal.` as sessions traded, `fills` as orders done. |

### Data and storage
- An infinite price, volume, level or action value is refused (A11).
- A merged bar is validated, and a broken merge refuses the whole promotion (A03).
- A check source confirms the primary's sessions and adds none (A06, D8).
- One writer holds the store (`flock`); a second gets `StoreBusy`; opening the store never deletes live work (A02).
- A run reads a complete generation, finishing an interrupted commit first (R03, D14).
- A rebuild is one transaction and decides what to replay under the lock (A16, R04).
- A promotion that finds an error is refused whole, journal of applied fetches included (R09).
- The stored action table is validated, not only the fetch; a split and a distribution on one ex-date are refused (D2, R08).
- A vintage that withdraws an observation is stored as a withdrawal (A09); vintage archives are found by every helper (A10).
- Coverage counts every session inside the span, contested sessions apart, and reviewed gaps apart (A12).
- Older formats are named: an older commit manifest is finished; an older clean file raises `StoreFormatError` (R11, D16).
- Every instrument declares its `history_basis` (D10); `known_gaps.toml` records reviewed gaps, which are never filled.

### Results
- The benchmark is a wealth chained from raw closes over its own sessions, with actions counted when known (A01, R02, D1, D13).
- A benchmark is not carried past its delisting (A15, D7).
- A run pins the digest of the store and of the registries it was handed; `run_id` identifies the whole experiment; a later comparison on a changed store raises `StoreChanged` (A05, R07, D15).
- The kept benchmark cannot be rewritten through a series it hands out (R06).
- The market view answers an absence instead of raising (A04).
- The recorded configuration holds the whole statistical convention (A13).

### Strategies and schedules
- Buy and hold completes its basket with the cash at the next open, then keeps it (A07, R05, D5, D12).
- A week or a month ends on the market's calendar, not at the run's end, and a run may end on the last covered session (A18, R10).
- The mutation guard is documented for what it checks: the declared definition (A14).

### Reports
- The report states its assumptions: fill model `OPEN_AUCTION_NOTIONAL`, what gross is, what cash earns, what limits cap, how long a decision lives, and the history basis of what was read. It also reports the largest weight held (section 5, D4, D6, D9).
- The table counts rebalancings and fills (A17). A comparison says its benchmark is a yardstick.
