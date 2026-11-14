# SA17 — admission gates of the executable study

The five gates of [protocol.md](protocol.md) ("Future comparison and admission
gates"). No executable SA17 run happens until each gate is either passed or
replaced by a declared assumption, in an amendment written and approved before
the run. A run resting on a declared assumption is `PROVISIONAL_NOT_ADMITTED`,
and its formal verdict is `INSUFFICIENT_EVIDENCE`, as `research/hypotheses.toml`
states.

Status on 2026-11-14:

| Gate | Status | Evidence | What remains |
| --- | --- | --- | --- |
| 2a. Fund valuation calendar | **PASSED** | [fund_calendar_evidence.json](fund_calendar_evidence.json), [`SA17_check_fund_calendar.py`](../../scripts/SA17_check_fund_calendar.py) | The grid is registered (`XNYS_XLON`, a checked subset of `XNYS`) and the strategy takes it as `observation_calendar_id`; the amendment adopts it |
| 2b. Fund actions and index changes | **PASSED** (data screen); notices not exhaustively read | [nav_jump_screen.json](nav_jump_screen.json), [`SA17_screen_nav_jumps.py`](../../scripts/SA17_screen_nav_jumps.py) | Disclose the 2018 GICS reshuffle of the sector indices |
| 2c. Historical NAV publication | **PARTIAL**: owner chose the declared prospectus rule (2026-11-07) | Prospectus rule (below); one dated notice ([lse_nav_validation.json](lse_nav_validation.json)) | Per-row historical timestamps not obtained |
| 2d. Synchronous EUR/USD | **PASSED** (2026-11-14): owner chose Dukascopy (2026-11-07) | Adapter [`dukascopy.py`](../../src/quant_backtester/data/sources/dukascopy.py), [`SA17_acquire_fx.py`](../../scripts/SA17_acquire_fx.py), [fx_verification.json](fx_verification.json); `runs/sa17_fx_20261107/derived/coverage.json`: 2,851 rates for 2,851 sessions, 24 of 24 sampled sessions agree | The series is a retrieval, not a historical vintage (`SNAPSHOT_UNVERIFIED`); the run discloses it |
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

The grid is registered as `research/SA17/calendars/XNYS_XLON.toml`, beside
the study rather than among the venues: every run loading
`market_data/metadata/calendars` hashes that whole folder, so a calendar added
there would change the identity of runs that never use it.
`scripts/generate_calendars.py` generates it from `exchange-calendars`, with
NYSE hours and early closes, and it declares `subset_of = "XNYS"`. Before the
file is written, the generator loads it with the committed XNYS file, and any
registry holding both refuses it if one of its sessions is not an XNYS
session at the same hours. The executable study's store will carry it beside
the venue calendars. The signals read the S&P 500 (bars on XNYS) and an FX series on it,
and still refuse an unrelated calendar. `SA17SectorResidualMomentum` takes
the grid as `observation_calendar_id` (default `XNYS`, unchanged).

A return on this grid that spans a UK holiday covers two NYSE sessions, and
the grid has about 248 sessions a year, not 252. The amendment must declare
the strategy's `annualization` from the grid's own count, or the basket
volatility is overstated and the exposure understated.

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

## 2d. Synchronous EUR/USD: passed

The NAVs are struck from US closing prices (16:00 New York, valued at
22:15 Dublin). The risk inputs need EUR/USD at that instant; ECB and WM 16:00
London fixings are refused by the protocol.

Dukascopy publishes free bars without an account. Its files of hourly bars,
one per month and side, give the rate at 16:00 New York: the close of the hour
ending then is the close of the minute ending then. Both are the last quote
before it, and they agreed on the probe day 2024-03-06 (bid 1.08990). That
means about 270 requests instead of about 5,700 daily minute files. A seeded
sample of 24 days is checked against the minute files.

The rate is read at each session's close as the XNYS calendar gives it:
16:00 New York, or 13:00 on the roughly 25 half days of the period. A bar
without a tick (zero volume) is skipped: the feed fills it with an earlier
close, which would pass for a quote at its end. `build` fails unless every
sampled session's hourly rate equals its minute rate.

The feed refuses Python's default client name with HTTP 429. The adapter sends
a plain one, `quant-backtester research client`, and does not imitate a
browser. After the probes on 2026-11-07 the feed throttled this address, and
the acquisition was stopped rather than retried against a refusal. The
fetcher waits five seconds between requests and five minutes after a first
refusal, and stops the run at the second. Each file is recorded in the
manifest before it is moved into place, so a later run resumes the archive
without leaving a file nobody recorded.

## Owner's decisions, 2026-11-07

- **2c**: the executable study uses the prospectus rule as a declared
  assumption: the NAV of day D is usable from the 23:00 Paris decision of the
  next UK business day. The gate stays `PARTIAL`, so the run is
  `PROVISIONAL_NOT_ADMITTED`.
- **2d**: EUR/USD at the US close is taken from Dukascopy bars (hourly files,
  checked against minute files on a sample). The owner takes responsibility
  for checking Dukascopy's terms for personal research use.

## Owner's decision, 2026-11-08

On 2026-11-08 the feed began dropping connections instead of refusing them.
The acquisition now runs under a watchdog: when no file arrives for 20 minutes,
it stops the fetch, waits an hour and starts again. It allows at most six
pauses per step (`fetch`, then `verify`). A pass that ends with a file skipped
also ends in a pause.

The running watchdog was copied verbatim in `2de9ed5` as
[`scripts/SA17_fx_watchdog.sh`](../../scripts/SA17_fx_watchdog.sh). Subsequent
corrections to this repository copy count only expected complete files and do
not rely on a manifest to detect progress. They do not replace the running
process. Do not launch a second copy while acquisition is active.

- **The six-pause limit stays.**
- **If the six pauses run out, or no new file has arrived after about 24
  hours**, Dukascopy is not used as it stands. Another source is evaluated
  against the same two requirements before gate 2d is reopened:
  - the rate at each XNYS session's close (16:00 New York, 13:00 on a half
    day), at most five minutes before it;
  - a verification on the same 24 seeded sessions (seed `20261107`), every one
    of which must pass.
- Until a source meets both, 2d stays open and nothing runs, as the protocol
  requires. ECB and WM fixings stay refused.
- An expected finishing date is a checkpoint, not a deadline. The acquisition
  may run out of retries with files still missing. On 2026-11-09 its state is
  reviewed and this rule is applied.

## Owner's decision, 2026-11-14

The acquisition did not run out of retries; the machine running it stopped.
From 2026-11-08 21:20 UTC the laptop hosting WSL went in and out of sleep,
slept from the evening of 2026-11-09 to 2026-11-13, and powered off at
2026-11-13 15:26 UTC (the journal of that boot). The watchdog and its `verify`
were frozen, then killed with the virtual machine, without logging a stop. So
the 2026-11-09 checkpoint was never reviewed. When the machine stopped:

- `fetch` was complete: 272 of 272 hourly files, after one pause;
- `verify` had 20 of its 48 minute files and had used none of its six pauses.
  The last file arrived at 2026-11-08 21:35:46 UTC;
- all 292 archived files matched their manifest hash and size, with no
  partial file left behind.

The 24-hour clause above is met only by wall-clock time. For most of those
days nothing asked the feed for a file. The owner read the clause as "the feed
stopped answering", which did not happen, and chose to resume Dukascopy rather
than evaluate another source.

The repository copy of the watchdog,
[`scripts/SA17_fx_watchdog.sh`](../../scripts/SA17_fx_watchdog.sh) at
`17d963e`, was started on 2026-11-14 at 11:14 UTC. It replaces the 2026-11-08
process, which no longer exists. `verify` keeps its six pauses, none of which
had been used. The gap is noted in `runs/sa17_fx_20261107.chain.log`. The rest
of the 2026-11-08 rule is unchanged.

That process did not survive either: the WSL virtual machine powered off at
2026-11-14 11:19:55 UTC (the journal of that boot), five minutes into the
watchdog's initial pause, before it had asked the feed for anything. The same
script was started again at 11:23 UTC on the same terms: 20 of 48 minute files,
six pauses unused. The log records both starts.

## 2d outcome, 2026-11-14

The watchdog ended at 2026-11-14 14:22:59 UTC with `build exit 0`. `verify`
used one of its six pauses: its first pass skipped two files, both of which
the next pass obtained. The archive holds 272 of 272 hourly files and 48 of 48
minute files.

`runs/sa17_fx_20261107/derived/coverage.json` records:

- 2,851 rates for 2,851 XNYS sessions from 2015-07-01 to 2026-10-30, 23 of
  them at a half day's 13:00 close; no missing month and no session without a
  rate;
- the 24 sessions of [fx_verification.json](fx_verification.json) (seed
  `20261107`): on each, the hourly rate equals the minute rate exactly
  (tolerance 1e-09), and the minute bar ends at the close (staleness 0 s,
  limit 300 s);
- the table's hash, `0c5d6ec762d0c28981e41996899e0728a08ab6c8c351f8871ffa73afb8831b56`.

Gate 2d passes. `scripts/SA17_build_study_store.py` checks the same record
again before it builds the store. Gates 2c and 2e stay partial, so the run is
`PROVISIONAL_NOT_ADMITTED` and its formal verdict is `INSUFFICIENT_EVIDENCE`.
