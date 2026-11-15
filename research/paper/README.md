# Paper plans

A plan fixes a strategy, the conditions it is run under and a start date,
before that date. From then on it is run on the data as it arrives, and what
it did is appended to its log, which is never rewritten. `research/PROTOCOL.md`
(sections 2 and 6) says why; `quant_backtester.research.paper` says how.

## The plans

| Plan | Book | Role |
| --- | --- | --- |
| `SA16_IT2` | `SA16RiskBudget` as `results/SA16/selected.json` froze it, weekly | Observed |
| `NASDAQ_BUY_HOLD` | `ETF_NASDAQ` bought and held | Reference |
| `SA15_R4_TRIAL71` | SA15's last archived selection, monthly | Reference |

All three start on **2026-11-17**, from 100 000 EUR in cash, under the
conventions of the SA16 study (`scripts/SA16_run_study.py`): Paris calendar,
whole units, commission 5 bp (minimum 1 EUR), half-spread 3 bp, slippage
2 bp, quantities fixed at the 23:00 Paris decision and filled at the next
open. No real money.

## Each day, or whenever: nothing is lost by running late

```bash
uv run python scripts/paper_update_store.py     # the only step on the network
uv run python scripts/paper_trade.py
git add research/paper/*.jsonl && git commit -m "paper: sessions to <date>" && git push
```

The push is what dates a log: a line committed and pushed cannot have been
written after the fact.

A session is logged once its 23:00 Paris decision has passed, every fund of
the plan has a close of that session, and the paper store
(`runs/paper_sa16_store`) holds every series up to what was published at
that instant. A series the pipeline refuses, or a provider that is down,
holds the log back; it does not put a hole in it.

## What stops the run, on purpose

- **Uncommitted code** (the logs themselves apart).
- **Another contract**: a changed rule, cost, capital, schedule or universe
  is a new plan, with a new name and a new start.
- **A logged session that comes out differently**: a bar a provider served
  late, or a revised value. The log keeps what was done at the time; someone
  reviews before the run goes on. Nothing is absorbed.

The paper store is local and not committed. It was seeded from the study's
store and is extended by fetches archived under its `raw/`. If it is lost, a
store rebuilt from today's provider histories may not replay the logged
sessions identically, and the run stops as above: keep a copy of it.

## Reading

Nothing is read before **252 sessions**: the 252nd is 2027-11-09. Then, net of
costs and on the same sessions, `SA16_IT2` is compared with each reference
on criteria 1 and 2 of `research/SA16/protocol.md`, section 3; exposure,
turnover and drawdown are reported beside the return, whatever they say.
One year cannot establish an edge: the SA16 study gives the size of
difference such a sample can and cannot show.
