# SA17 — admission gates of the executable study

The five gates of [protocol.md](protocol.md) ("Future comparison and admission
gates"). No executable SA17 run happens until each gate is either passed or
replaced by a declared assumption, in an amendment written and approved before
the run. A run resting on a declared assumption is `PROVISIONAL_NOT_ADMITTED`,
and its formal verdict is `INSUFFICIENT_EVIDENCE`, as `research/hypotheses.toml`
states.

Status on 2026-11-07:

| Gate | Status | Evidence | What remains |
| --- | --- | --- | --- |
| 2a. Fund valuation calendar | **PASSED** | [fund_calendar_evidence.json](fund_calendar_evidence.json), [`SA17_check_fund_calendar.py`](../../scripts/SA17_check_fund_calendar.py) | Adopt the XNYS ∩ XLON grid in the amendment. Code: let a signal read a BAR instrument on a registered sub-calendar of its own |
| 2b. Fund actions and index changes | **PASSED** (data screen); notices not exhaustively read | [nav_jump_screen.json](nav_jump_screen.json), [`SA17_screen_nav_jumps.py`](../../scripts/SA17_screen_nav_jumps.py) | Disclose the 2018 GICS reshuffle of the sector indices |
| 2c. Historical NAV publication | **PARTIAL**: owner chose the declared prospectus rule (2026-11-07) | Prospectus rule (below); one dated notice ([lse_nav_validation.json](lse_nav_validation.json)) | Per-row historical timestamps not obtained |
| 2d. Synchronous EUR/USD | IN PROGRESS: owner chose Dukascopy (2026-11-07) | Adapter [`dukascopy.py`](../../src/quant_backtester/data/sources/dukascopy.py), [`SA17_acquire_fx.py`](../../scripts/SA17_acquire_fx.py); three probe days read 1.08991, 1.09471, 1.09363 at the US close | Acquisition throttled (HTTP 429) on 2026-11-07; resume with `fetch`, then `verify` and `build` |
| 2e. Execution prices | **PARTIAL**: no second source; the engine's refusals stand | `runs/sa17_store` re-downloaded 2026-11-07: two missing Xetra sessions per sector fund (2025-10-24, 2026-03-06) | Count refusals in the run; opening price plus declared costs stays an approximation |

## 2a. Fund valuation calendar: passed

The umbrella prospectus of SSGA SPDR ETFs Europe II plc (19 February 2026,
archived with its SHA-256) defines a **Business Day** as "a day on which markets
in the United Kingdom are open and/or such other day or days as the Directors
may determine". Each sector supplement values at **10.15 p.m. Irish time on each
Business Day**. Neither of the two supplements read redefines either term.

Checked against the XLON calendar of `exchange-calendars`:

- All 26 XNYS sessions without a NAV (18 for communications), in every fund,
  are UK market holidays. **No gap is unexplained**, and none is a provider
  failure.
- Since mid-2016 the funds also value on most UK bank holidays (May, spring,
  August) under the "such other day" clause. They do not value on Easter
  Monday or the Christmas and New Year holidays.

The proposed observation grid is **XNYS sessions that are also XLON
sessions**. It is known in advance from two published calendars, every fund
has a NAV on each of its dates, and it drops the NAVs struck on UK holidays
that no rule fixed in advance could anticipate. It becomes the grid only
through the executable-run amendment.

The definitions come from the 2026 edition. The check over the whole
2015–2026 history is what supports applying them to earlier years.

## 2b. Fund actions: passed on the data, with a disclosure

A split, consolidation or restatement left unrecorded would show as a daily
NAV change far from the market's. The screen flags every change above 15%, or
more than 8 points from the S&P 500 total return over the same dates. It finds
four, all in the energy fund, all on known market days: the oil price war of
9 March 2020, the Covid crash and rebound of 18 and 24 March 2020, and the
first vaccine announcement on 9 November 2020. No change looks like a split
(−50%, +100%).

The issuer's notices were not read exhaustively, for the same reason as in 2c.
The sector indices were reconstituted in September 2018, when the GICS
communication services sector took names from technology and consumer
discretionary. That changes what a sector means, not the data. The
communications fund starts in August 2018 and enters the ranking only with 36
months of history, so the study discloses this rather than adjusting for it.

## 2e. Execution prices: partial

Two Xetra sessions (2025-10-24 and 2026-03-06) have no bar for the sector
funds. No second price source was added for them. The protocol's fallback
stands: the engine refuses an order it cannot fill at a valid opening price,
and never fills at a NAV or a previous close. The executable run counts its
refusals. Zero reported volume before 2021 is not treated as unavailability,
and the opening price plus declared costs remains an approximation of what
was executable.

## 2c. Historical publication: partial

The prospectus (PDF page 55): "the Net Asset Value per Share shall be made
public after the Valuation Point on the business day following the relevant
Dealing Day". One LSE notice is consistent with it: published 2026-11-06 at
10:20:21 UTC, it carries the NAVs of 2026-11-05.

Per-row timestamps back to 2015 were not obtained. The London Stock Exchange
news pages are rendered by script and expose no public archive interface, and
search engines index none of SSGA's NAV notices. So a historical decision can
rest on the prospectus rule, declared as an assumption, but not on observed
publication times.

## 2d. Synchronous EUR/USD: decision needed

The NAVs are struck from US closing prices (16:00 New York, valued at
22:15 Dublin). The risk inputs need EUR/USD at that instant; ECB and WM 16:00
London fixings are refused by the protocol.

Dukascopy publishes free bars without an account. Its files of hourly bars,
one per month and side, give the rate at 16:00 New York: the close of the hour
ending then is the close of the minute ending then. Both are the last quote
before it, and they agreed on the probe day 2024-03-06 (bid 1.08990). That
means about 270 requests instead of about 5,700 daily minute files. A seeded
sample of 24 days is checked against the minute files.

The feed refuses Python's default client name with HTTP 429. The adapter sends
a plain one, `quant-backtester research client`, and does not imitate a
browser. After the probes on 2026-11-07 the feed throttled this address, and
the acquisition was stopped rather than retried against a refusal. The
fetcher waits five seconds between requests, waits five minutes once after a
refusal, and stops at the second one. A later run resumes the archive.

## Owner's decisions, 2026-11-07

- **2c**: the executable study uses the prospectus rule as a declared
  assumption: the NAV of day D is usable from the 23:00 Paris decision of the
  next UK business day. The gate stays `PARTIAL`, so the run is
  `PROVISIONAL_NOT_ADMITTED`.
- **2d**: EUR/USD at the US close is taken from Dukascopy minute bars. The owner
  takes responsibility for checking Dukascopy's terms for personal research
  use.
