# Research protocol

Written on 2026-09-26, before any experiment it governs. Changing it is a
reviewed commit, and a change never applies to an experiment already run.

## 1. What is already spent

Every session of 2018-04-18 to 2026-09-17 on `ROTATION_2` has been looked
at: the baselines table and the reference rotation of the README cover all of
it, and those results shaped choices (the 60-session lookback, the VIX gate,
the monthly equal weight). **No stretch of that history is out of sample
any more.** A "holdout" carved from it now would be one in name only. The
figures of the README are development baselines, not evidence that a rule
works.

## 2. The one test left: the future

Two paper plans are committed before their start, `2026-10-01`, in
`research/paper/`:

| Plan | Strategy | Why |
|---|---|---|
| `ROTATION_2_MOMENTUM_60` | `MomentumRotation(lookback_sessions=60, top_n=1)`, every session | The README's reference rule |
| `ROTATION_2_BUY_AND_HOLD` | `BuyAndHold(ETF_WORLD)` | The control it has to beat after costs |

Each is fixed by a `contract_id`: the strategy's fingerprint and every
condition it is run under - costs, starting cash, schedule, timetable,
universe, limits, lot sizes, benchmark. `scripts/paper_trade.py` runs both
from their start to the last ready session - its 23:00 Paris decision instant
passed, and a close of that session for every instrument traded - and appends
every new session to the plan's log, with the commit that produced it. The log
holds what was done, not a summary: the decision, the orders, the fills with
their prices and costs, the rejects, the book and the cash. It refuses
uncommitted code and a run under another contract, and stops if a session
already logged comes out differently in any of those: a revised price the
plan already acted on is reviewed, never absorbed. Running it twice changes
nothing. A rule or a condition changed after the start is a new plan, with a
new start.

**Reading the result.** No verdict before 12 months of sessions (about 255):
below that, the difference between two funds' returns is mostly one fund's
luck. At 12 months the comparison is net of costs, on the same sessions,
alongside exposure, turnover and drawdown, and it is reported whatever it
says.

## 3. Every experiment is registered

Any backtest run to answer a research question is appended to
`research/registry.jsonl` (`quant_backtester.research.registry`): one line per
run, never edited, the rejected ones included, only from committed code. Each
line names its hypothesis, so a result can always be read with the number of
variants it took to find it. Running variants and showing the best without
that count is not allowed.

A hypothesis is written down before its first variant is run: what it
predicts, over which universe, and what result would refute it.

## 4. How a variant is judged

- **Neighbourhoods, not points.** A lookback of 60 means little unless 40 and
  80 say the same thing. A result that exists at one parameter value and not
  next to it is noise.
- **Start dates.** Every conclusion is checked on rolling start dates; a rule
  that only works from one start was timing, not a rule.
- **Costs.** Every variant is run at the declared cost model and at twice it.
  An edge that disappears at twice the costs is not one to trade.
- **Same yardstick.** Return, drawdown, exposure, average cash and turnover are
  compared with an executable baseline over the same sessions, not with an
  index. A lower drawdown bought with more cash is exposure, not skill.
- **No significance claim from two funds.** `ROTATION_2` is the thinnest
  cross-section a ranking can have; nothing on it generalises to momentum.

## 5. Before widening the universe

Adding distributing ETFs or equities needs, first, a model of corporate
actions on held positions (today a split or a dividend on a held line stops
the run), and a universe whose history is point-in-time, dead names included.
A larger universe does not compensate for events booked wrongly.
