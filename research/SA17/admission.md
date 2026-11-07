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
| 2b. Fund actions and index changes | NOT STARTED | — | Issuer notices; screen NAV jumps |
| 2c. Historical NAV publication | **PARTIAL** | Prospectus rule (below); one dated notice ([lse_nav_validation.json](lse_nav_validation.json)) | Per-row historical timestamps not obtained |
| 2d. Synchronous EUR/USD | OPEN, decision needed | — | Candidate source: Dukascopy minute data; its terms of use were not found |
| 2e. Execution prices | NOT STARTED | `runs/sa17_store` re-downloaded 2026-11-07: two missing Xetra sessions per sector fund | Second price source, or the engine's refusals, counted |

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

Dukascopy publishes free minute bars without an account, from which the rate
at 16:00 New York can be read. Its terms of use were not found, and bulk
download needs the owner's decision before an adapter is written.
