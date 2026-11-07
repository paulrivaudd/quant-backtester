# SA17 — data readiness audit

Audit date: 2026-11-01. Repository baseline: `63a8984`.

**Outcome: `INSUFFICIENT_EVIDENCE` for running the proposed study with the
audited inputs. This is a data-readiness outcome, not a rejection of the
strategy. No SA17 backtest, fit, parameter comparison or selection was run.**

The [original proposal](proposal.md) remains unchanged. The two proposed
studies — a long economic proxy study and an executable UCITS portfolio —
still have separate requirements. Neither has an approved common window.

## What was inspected

The local store `runs/sa16_store`, its instrument registry, calendars,
corporate-action table and clean date coverage were read under the repository's
shared lock. [local_inventory.json](local_inventory.json) records all 23
registered instruments, including three with no observations, and the SHA-256
of each pinned file. Its store digest is
`9a5346a834f4a8572655f059643e80633db47b307b83f7e423b6e909a5cefed6`.

The inventory reports missing sessions only **between the first and last
observed dates**. An empty list does not certify coverage before or after that
range, valid prices, timely publication, executable opens or true total returns.
An empty series reports unknown coverage, not zero missing sessions.

| Local input | Observations | Relevance to SA17 |
| --- | --- | --- |
| `SP500`, `NDX` | 2014-01-02–2026-10-30 | USD price indices; neither supplies the required S&P 500 total-return market factor. |
| `ETF_US_TECH` (`QDVE.DE`) | 2017-01-02–2026-10-30; 2,493 bars | One US sector, quoted in EUR; insufficient for a three-sector selection. Missing 2025-10-24 and 2026-03-06. |
| `ETF_WORLD_HEALTH`, `ETF_WORLD_UTILITIES` | Start 2017-01-02 | Global sector funds; not the proposed S&P 500 health-care and utilities exposures. |
| `ETF_MONETARY_EUR`, `ETF_NASDAQ` | 2014-01-02–2026-10-30; 3,255 bars each | Potential existing monetary and Nasdaq controls; not evidence for earlier periods. |
| `ETF_GOLD` | 2018-01-02–2026-10-30; 2,241 bars | Gold leg of the archived SA16 comparison; missing the same two recent sessions as technology. |
| `ECB_EURUSD` | 2014-01-02–2026-10-30 | No local 1996–2013 FX history. An ECB fixing also does not establish a synchronous US-close conversion. |

The registry's `first_session` is not proof of observed coverage. For example,
gold is declared from 2014 but this store's gold observations start in 2018.
The earliest local observations are in 2014, so this store cannot support the
1999–2018 study with its required warm-up from 1996.

The committed XPAR calendar begins in 2002 and XETR in 2014; XNYS begins in
1990. An XPAR decision schedule in 1999 cannot be run without independently
extending that calendar. The inventory also exposes the existing session gaps;
they must not be filled just to make a 63-session covariance available.

## Return definitions are an implementation prerequisite

[CORPORATE_ACTIONS.md](../../docs/CORPORATE_ACTIONS.md) explicitly distinguishes
`PriceBasis.ADJUSTED` from dividend-reinvested wealth. Its dividend adjustment
produces `C_ex / (C_prev - D) - 1`, whereas a one-period total return without a
split is `(C_ex + D) / C_prev - 1`. Those are different even when both prices
are available. The first is not an admissible substitute for the second in the
proposed monthly regression.

The existing Yahoo adapter also refuses an ETF with any reported split because
its returned OHLC is already split-adjusted. Declaring a distributing US ETF to
be an index, suppressing the split check or relabelling adjusted prices as total
returns would bypass the data contract. A genuine total-return index input or
a separately tested point-in-time total-return builder is needed. Gross versus
net dividend treatment must match across every sector and the market factor.

Accumulating funds may supply economic returns from their observed prices,
subject to their actions and price validation. A EUR exchange close converted
at an unrelated FX fixing does not become a synchronous USD sector-index close.
The signal input and the traded vehicle need separate identifiers and clocks.

## Sector and vehicle evidence

These are facts useful for further sourcing, not a frozen historical universe.

- S&P's [March 2016 real-estate note](https://www.spglobal.com/spdji/en/documents/additional-material/spdji-the-new-gics-real-estate-sector-and-sp-us-benchmarks.pdf)
  places the new sector's S&P US index implementation at the September 2016
  rebalance. A current real-estate series cannot simply be treated as a separate
  historical sector throughout the proposed long sample.
- The [2017 GICS announcement](https://press.spglobal.com/2017-11-15-S-P-Dow-Jones-Indices-And-MSCI-Announce-Revisions-To-The-Global-Industry-Classification-Standard-GICS-R-Structure-In-2018)
  describes the 2018 expansion of telecommunications into communication
  services, including transfers from technology and consumer discretionary.
  An identifier remaining similar does not establish unchanged exposure.
- S&P's [July 2018 technology-index notice](https://www.spglobal.com/spdji/en/documents/indexnews/announcements/20180709-737751/737751_spselectsectorcapped20percenttechnologyindexconsultationresults7.9.2018.pdf)
  explicitly describes the former combined technology/telecommunications scope
  of its Capped 20% Technology index. Different index families require their
  own mapping; a fund name containing “technology” is insufficient.
- State Street's [2019 shareholder notice](https://www.ssga.com/library-content/products/fund-docs/etfs/emea/related-items/spdr-ii-us-sector-benchmarks-shareholder-notice-en.pdf)
  identifies the sector funds below and their planned switch to daily capped
  25/20 indices from 15 March 2019, subject to the notice's effective-date
  condition. Current fund pages also describe later 35/20 benchmarks. Their
  current benchmark names must not be backdated over their entire histories.

The following **sourcing shortlist** covers the current eleven sector labels.
It is neither an assertion that all were investable together historically nor
a comparison of their performance. Rows marked “unverified” still need a dated
EUR listing and a usable provider history; no provider ticker is invented.

| Sector | Fund / ISIN | Verified EUR listing | Evidence |
| --- | --- | --- | --- |
| Energy | SPDR US Energy / `IE00BWBXM492` | Unverified | 2019 notice |
| Materials | SPDR US Materials / `IE00BWBXM831` | Unverified | 2019 notice |
| Industrials | SPDR US Industrials / `IE00BWBXM724` | Unverified | 2019 notice |
| Consumer discretionary | SPDR US Consumer Discretionary / `IE00BWBXM278` | Unverified | 2019 notice |
| Consumer staples | SPDR US Consumer Staples / `IE00BWBXM385` | Unverified | 2019 notice |
| Health care | SPDR US Health Care / `IE00BWBXM617` | Unverified | 2019 notice |
| Financials | SPDR US Financials / `IE00BWBXM500` | Unverified | 2019 notice |
| Information technology | SPDR US Technology / `IE00BWBXM948` | Deutsche Börse, `ZPDT`, 2015-07-08 | [Issuer listing table](https://www.ssga.com/uk/en_gb/institutional/etfs/state-street-spdr-sp-us-technology-select-sector-ucits-etf-acc-zpdt-gy) |
| Communication services | SPDR US Communication Services / `IE00BFWFPX50` | Deutsche Börse, `ZPDK`, 2018-08-16 | [Issuer listing table](https://www.ssga.com/uk/en_gb/institutional/etfs/state-street-spdr-sp-us-communication-services-select-sector-ucits-etf-acc-zpdk-gy) |
| Utilities | SPDR US Utilities / `IE00BWBXMB69` | Unverified | 2019 notice |
| Real estate | Invesco Real Estate S&P US Select Sector Acc / `IE00BYM8JD58` | Unverified | [September 2026 factsheet](https://www.invesco.com/content/dam/invesco/emea/en/product-documents/etf/share-class/factsheet/IE00BYM8JD58_factsheet_en.pdf) |

*Addendum 2026-11-07:* the EUR listings marked "Unverified" above were checked
against the issuer's listing tables; see [sourcing_20261102.md](sourcing_20261102.md).
The same day, the ten funds, an S&P 500 total-return series, XEON, the ECB
EUR/USD rate and the funds of the external references were acquired into
`runs/sa17_store`. The coverage is in the
[README](README.md#acquisition-2026-11-07). The audit's other findings are
unchanged: nothing acquired reaches before 2014, and the 1999–2018 study
still lacks its data.

The Invesco factsheet confirms a 2016-02-17 launch, accumulation, synthetic
replication and a capped real-estate benchmark. It does not establish an earlier
EUR listing. The SPDR real-estate ISIN `IE00BFY0GR99` also appears in the 2019
notice, but a [KID hosted under pending-launch](https://www.ssga.com/library-content/announcement/etfs/emea/pending-launch/priip-spdr-sp-us-real-estate-select-sector-ucits-etf-acc-acc-usd-ie00bfy0gr99-en.pdf)
does not prove a launched, liquid listing; it has not been admitted here.

The already stored QDVE remains another technology vehicle to audit, and remains
the unchanged vehicle of the SA16 reference. No SA17 choice between it and ZPDT
has been made. Historical closures, mergers, discontinued listings and a vehicle
choice rule remain unaudited. This shortlist of currently discoverable products
does not resolve survivorship bias.

Issuer pages and factsheets include retrospective performance tables. Some
were exposed while locating metadata; that consultation is recorded here.
Those tables were not used to rank vehicles or change the candidate. No period
is labelled untouched or out of sample.

## What must be resolved before the first run

| Requirement | Current evidence | Required next artifact |
| --- | --- | --- |
| Long sector and market total returns | No audited machine-readable 1996-onward dataset acquired | Archived series, gross/net basis, publication rules, source and revision disclosures, classification history |
| Historical economic universe | Major 2016/2018 changes identified; full dated mapping absent | Dated sector membership and index-definition records, including pre-change histories |
| Executable vehicles | Sourcing shortlist only | Registry with ISIN, exact index, currency, venue, listing/delisting dates, actions and dated mapping to each signal |
| Survival-independent vehicle choice | Not established | Historical opportunity set including closures; selection rule fixed before return comparisons |
| Daily EUR risk inputs | Full sector panel absent | 64 synchronized valid daily closes for each 63-return window, with missing-session diagnostics |
| Common comparison window | Not established | Coverage-driven dates and warm-up manifest for candidate and all controls |
| Monetary reference and costs | Existing XEON and SA16 assumptions are available | Freeze excess-return convention and vehicle-specific commission, spread and slippage assumptions |
| Long proxy controls and FX | Not established | Technology, gold, Nasdaq, EUR monetary/FX proxies with explicit non-executable status where applicable |

No paid dataset or account was accessed. Public product documentation establishes
some identities, not the existence of a complete downloadable historical panel.
The absence of an audited dataset here is not a claim that none can be obtained.

The first continuation is data sourcing and historical mapping, then an isolated
SA17 store and coverage checks. A shorter modern study may eventually have an
admissible window, but it must be declared separately and must not replace the
1999–2018 question silently. No real instrument registry, hypothesis freeze or
performance report is created until these requirements are met.

## Reproduce the local inventory

From the project root in its POSIX Python 3.12 environment:

```bash
uv run python scripts/SA17_audit_data.py --store runs/sa16_store > /tmp/sa17-audit.json
cmp research/SA17/local_inventory.json /tmp/sa17-audit.json
uv run pytest tests/scripts/test_SA17_audit_data.py
```

For a new dated audit, use `--output <new-file.json>`. That option refuses an
existing output. The script does not download, fill missing observations,
compute returns or run strategies. As with other repository readers, opening
an interrupted store can trigger the repository's normal transaction recovery;
the audited store here was complete.
