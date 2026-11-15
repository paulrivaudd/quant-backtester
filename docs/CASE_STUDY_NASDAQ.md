# Case study: three frozen attempts to beat the Nasdaq, and what they showed

## The question

On 2018-08 to 2026-10, SA16's retained configuration (US technology and gold
under a 75/25 risk budget) is ahead of the Nasdaq fund bought and held, net
of costs: 22.3% a year against 19.1%, a Sharpe ratio of 1.32 against 0.94
([SA17 study, reference books](../results/SA17/study.md)). That window is
the one the rule was designed on, and three studies were read on it.

**Is there a rule that returns more than the Nasdaq on months it was not
designed on?**

## The protocol

- **Unseen months.** 1975-01 to 2018-07, 523 months, monthly, in US dollars:
  none of them was looked at for SA15, SA16 or SA17.
- **Frozen first.** Each test has a design, its parameters and a written
  prediction committed and pushed before any return is computed. The run
  refuses uncommitted code and input files whose hash is not the recorded one.
- **One criterion.** A rule beats a reference when its net CAGR and net
  Sharpe are both higher and its maximum drawdown is at most 2 points deeper.
  `SUPPORTED_RETROSPECTIVE` also needs a Holm-adjusted p-value below 0.05 on
  the Sharpe difference (paired stationary bootstrap, 10,000 draws) and the
  same result at doubled costs.
- **Two references.** The technology portfolio of Ken French's 12 industries,
  held (a total return), and the Nasdaq Composite, held (no dividends, so it
  is understated).
- **Costs.** 10 basis points of traded value, doubled in a second run.

These are research series, not funds. Gold is a monthly average price. The
result says whether a mechanism held over forty years; it says nothing about
an executable book.

## The figures

| Book, 1975-01 to 2018-07, net | CAGR | Volatility | Sharpe | Max drawdown | Reading |
| --- | ---: | ---: | ---: | ---: | --- |
| Technology portfolio, held (reference) | 12.0% | 22.8% | 0.42 | -79.6% | |
| Nasdaq Composite, held (reference) | 11.8% | 20.7% | 0.43 | -75.0% | |
| 1. Technology and gold at a risk budget | 10.8% | 15.3% | 0.45 | -44.5% | `NOT_SUPPORTED` |
| 2. The same, levered to the technology portfolio's volatility | 11.6% | 21.9% | 0.41 | -69.8% | `NOT_SUPPORTED` |
| 3. Technology above its ten-month average, bills otherwise | 9.4% | 16.9% | 0.35 | -46.1% | `NOT_SUPPORTED` |

Reports: [1](../results/SA16/long_history/study.md),
[2](../results/SA16/levered_long_history/study.md),
[3](../results/SA18/trend_long_history/study.md). Designs:
[1](../research/SA16/long_history.md),
[2](../research/SA16/levered_long_history.md),
[3](../research/SA18/trend_long_history.md).

## The predictions, against what happened

| Test | Written before the run | Outcome |
| --- | --- | --- |
| 1 | Sharpe above both references, shallower drawdown, CAGR below both: `NOT_SUPPORTED` | As predicted |
| 2 | CAGR 12 to 12.5%, drawdown -55% to -65%, Sharpe 0.42 to 0.45 | CAGR 11.6%, drawdown -69.8%, Sharpe 0.41: too favourable |
| 3 | CAGR 11 to 13.5%, Sharpe 0.50 to 0.60, 40 to 70 switches | CAGR 9.4%, Sharpe 0.35, 85 switches: too favourable |

Volatility, drawdown and time invested fell in their predicted ranges for
test 3. The returns did not, twice in a row and in the same direction.

## The interpretation

- **Mixing technology with gold changes how much risk is taken, not how much
  it pays.** The rule halves the worst loss for about one point less a year,
  at a Sharpe ratio that cannot be told apart from the references' (95%
  interval of the difference: [-0.148, 0.216] against the technology
  portfolio).
- **Leverage does not buy the return back.** Held at the technology
  portfolio's volatility, the rule earns 0.4 point less than it, and its
  drawdown goes from -44.5% to -69.8%. The loan costs about half a point a
  year: with a free loan the CAGR is 12.1%.
- **The trend filter pays for one decade.** It is ahead in 2000-2009 only
  (4.9% a year against -6.2%) and behind the technology portfolio in the
  four other periods, by 4 to 13 points a year. It left and re-entered 85
  times.
- **The 2018-2026 lead does not generalise.** On that window the rule was
  ahead of the Nasdaq; on the forty-three years before, it was not.

## The limits

- **The second and third tests are not blind.** The same 523 months had been
  read once, then twice. Each design says what that leaves the test able to
  show.
- **The trend filter is a published rule** (Faber 2007), chosen on data that
  overlaps the window.
- **One result points the other way, weakly.** On 1927-07 to 1974-12, months
  no test here had read, the trend filter is ahead of the technology
  portfolio: 9.9% against 9.2%, Sharpe 0.50 against 0.37. The difference is
  not significant (p = 0.38), and the design said beforehand that these
  months decide nothing.
- **Forty-three years is still a thin sample for this question.** Intervals of about ±0.2 on a
  Sharpe difference cannot see a real edge of 0.1.
- The later tests, their code and their reports were written with AI coding
  assistants under my direction; the checks above are what I rely on.

## What comes next

Nothing here out-returns the Nasdaq without taking more risk. What the
evidence supports is narrower: the technology and gold rule is a lower-risk
way to hold it. That claim is now tested the only way left: the retained
configuration runs forward on paper beside its two references from
2026-11-17, and is not read before 252 sessions, on 2027-11-09
([plans](../research/paper/README.md)).
