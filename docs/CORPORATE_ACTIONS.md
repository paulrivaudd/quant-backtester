# Corporate actions

State on 2026-09-27. This document says what the project does with a corporate
action at each layer, and above all what it **does not do yet**. The
architecture is in [ARCHITECTURE.md](ARCHITECTURE.md), the formulas in
[FORMULAS.md](FORMULAS.md).

## 1. What a corporate action is, and why it is dangerous

A corporate action changes a holder's securities, entitlements or cash flows.
The price then moves mechanically, without anyone having gained or lost as
much. A 2:1 split halves the price, but the holder has twice as many shares. A
dividend lowers the price by its amount, but the holder receives that amount
in cash.

Read on a raw series, a corporate action looks like a market move: a −50%
crash for a 2:1 split, a 2% fall for a 2% dividend. A momentum, a drawdown or
a return computed across it is wrong.

There are four distinct dates: the **announcement** (the event becomes
public), the **ex-date** (the security trades without the entitlement), the
**record date** (who is a holder) and the **payment date** (the cash or the
securities arrive). The project knows only the ex-date: Yahoo provides nothing
else.

## 2. The stored types

`data/schemas.py`, `ActionType`. The `value` column means something different
depending on the type:

| Type | `value` | Adjustment of prices before the ex-date |
|---|---|---|
| `SPLIT` | ratio: 4.0 for a 4:1, 0.125 for a 1:8 reverse split | divided by the ratio |
| `DIVIDEND` | gross amount per share, in the instrument's currency | multiplied by `1 − D / C_prev` |
| `SPIN_OFF` | price adjustment factor | divided by the factor, like a split, but **no share was multiplied** |
| `SPECIAL_DIVIDEND` | gross amount of an exceptional distribution | like a dividend |

`C_prev` is the raw close of the session before the ex-date.

Yahoo does not tell these cases apart. It codes a spin-off as a fractional
split (GE 1.281 on 2023-01-04 for GE HealthCare) and an exceptional dividend as
an ordinary one (COST 15.00 on 2023-12-27). Only a **reviewed correction**
committed in `market_data/metadata/corporate_actions.toml` requalifies an event
(`data/corporate_actions.py`). A correction can only rename `SPLIT` to
`SPIN_OFF` or `DIVIDEND` to `SPECIAL_DIVIDEND`. Both types of a pair adjust the
price in the same way, so a correction never moves a stored series. It only
changes what the layers above are allowed to read in it.

A correction is not point in time: it applies to the whole history from the day
it is written. **The corrected type is therefore not usable as a predictive
variable.** The file is empty today: SP500 and VIX are indices, the ETFs are
accumulating and the rates distribute nothing.

## 3. What each layer does

### `data`: ingestion and checks

- Yahoo: splits and dividends are downloaded separately and stored in their own
  table. `YahooSource.download` **refuses a stock or an ETF for which Yahoo
  reports a split**, even outside the requested period. With
  `auto_adjust=False`, Yahoo still adjusts prices before a split. The raw series
  is therefore not raw, and cannot be used. This protection can block an asset
  that the provider does carry.
- The validator refuses (`ERROR`):
  - a duplicate action on the same day;
  - **a split and a distribution on the same ex-date** (`SPLIT_WITH_DISTRIBUTION`,
    decision D2): it is not known whether the amount is per share before or
    after the split;
  - a ratio ≤ 0 or equal to 1;
  - a dividend ≤ 0;
  - a distribution on a unit declared `ACCUMULATING` (`UNEXPECTED_DISTRIBUTION`).
- `distribution_policy` (`DISTRIBUTING` / `ACCUMULATING`) says whether an empty
  dividend feed is normal or a gap.

### `data`: reading

- An action is **available at the open of its ex-date**, at the same time as
  the first price it affects. The execution reader of the ex-date sees the open
  already adjusted *and* the action. The reader of the evening before sees
  neither. Neither of them shows a false jump.
- `PointInTimeReader.adjusted_history` adjusts going back in time, with only the
  actions known at the instant. The factors multiply. An action still in the
  future does not change the window. A factor ≤ 0 raises an error.

### `signals`

`PriceBasis.ADJUSTED` reads `adjusted_history`. It is an **adjusted price**, not
reinvested wealth: on the ex-day, the return read is `C_ex / (C_prev − D) − 1`,
not `(C_ex + D) / C_prev − 1`. With `C_prev = 100`, `D = 2` and `C_ex = 101`,
the signal reads 101/98 − 1 = 3.06%, while the holder gained 103/100 − 1 = 3%.
A signal needs the first number: the second waits for a close it has not seen
yet. `PriceBasis.RAW` reads the quotation as it is. A signal on `RAW` whose
window crosses a corporate action measures the corporate action.

### `backtest`: the book

**The engine books no corporate action on a held position.** Before each open,
`BacktestEngine._require_no_corporate_action` checks whether a held position
crosses an ex-date since the previous session. If it does, the run stops with
`UnsupportedCorporateAction`, **even if the strategy was about to sell at that
open**, because the sale would take place after the event. Without this stop, a
split would read as a price collapse, and a dividend would never reach the
cash.

It is an explicit stop, not a handling of the event. Today no tradable
instrument distributes: both ETFs are accumulating, and neither has a split.
The stop has therefore never happened on the README's runs.

### `backtest` and `analytics`: the benchmark

`value_benchmark` and `session_growth` value a unit held without costs, in
fractions of shares:

- **split**: the number of shares is multiplied by the ratio;
- **dividend**, ordinary or special, under `BenchmarkBasis.TOTAL_RETURN`: the
  amount is paid on each share held at the ex-date, then reinvested at the
  close of that session. Under `PRICE_RETURN`, it is ignored;
- an action known late is counted at the first step where it is known;
- **spin-off: refused**. The benchmark cannot value what was distributed, and
  does not treat a spin-off as a split (decision D3);
- **split and distribution on the same day: refused** (decision D2).

## 4. What is not handled

- The accounting of a corporate action on a held position: the run stops (see
  §3).
- The receivable between the ex-date and the payment, and the payment delay.
- Taxation: withholding tax, the PEA regime.
- The delivery of a spin-off's shares, the exchange of a merger, the exercise
  or sale of a preferential subscription right.
- Split fractions: fractions of a share to be settled in cash.
- The redemption at delisting. A delisted security stops the run
  (`UnvaluablePosition`) and the benchmark, without an invented liquidation
  price.
- A history of announcements: the catalogue does not know the announcement
  date, and it is not a tradable feed before the ex-date.
- Survivorship bias at the data level: Yahoo serves nothing for a delisted
  security (TWTR, SIVB, CELG). A universe must be declared date by date, and the
  raw series archived before the delisting.

## 5. To extend it (batch G, C05 of the archive audit 9)

The extension waits for three **user decisions**: the payment delay of a
dividend, the treatment of withholding tax in a PEA and the settlement of split
fractions. Once those decisions are taken, the method is as follows:

1. a typed and dated event per corporate action, with its units before and
   after;
2. the book updates the quantities and the average cost at the open of the
   ex-date;
3. a dividend becomes a **receivable** on the ex-date, then cash on payment.
   Both movements are recorded in the `BacktestRecord`;
4. a **wealth conservation** test with no market move: 10 shares at 100 before
   a 2:1 split become 20 shares at 50, that is 1,000 in both cases;
5. the same test for a dividend: the book's wealth on the ex-date, receivable
   included, does not change when the price falls by the amount.

## 6. Corporate actions as a source of signal

Out of scope today. For the record:

- **cleaning a signal**: that is the role of `ADJUSTED`. A base adjusted today
  may still contain corrections unknown at the decision date;
- **event signal**: it needs an **announcement** timestamp, which we do not
  have. An ex-date known after the fact is not one;
- **merger arbitrage**: a target at 48, an offer at 50, a return to 35 if it
  fails. The expected gain is `15p − 13`, so `p > 13/15` is needed before fees
  and carry. It is not free money, and the project has neither these
  probabilities nor the exchange mechanics.
