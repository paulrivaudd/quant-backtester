# Glossary

The finance and backtesting terms in the sense the project uses them. The
second column gives the name used in the code where there is one. The formulas
are in [FORMULAS.md](FORMULAS.md).

| Term | In the code | Meaning in this project |
|---|---|---|
| Instrument | instrument | a series described in `instruments.toml`: not necessarily tradable (an index, a rate) |
| Stock, share | stock, share | a unit of ownership of a company |
| Exchange-traded fund | ETF | a fund unit traded on an exchange; an index, by contrast, is only a calculation and cannot be bought |
| Accumulating / distributing fund | accumulating / distributing | reinvests its income / pays it out to holders (`distribution_policy`) |
| Universe | universe | the instruments a strategy may hold at a date; dated members in `universes.toml` |
| Session | session | a trading day of a venue, according to its calendar |
| Bar, OHLCV | bar | open, high, low, close and volume of a session: a summary, not the path travelled |
| Level | level | a published value (rate, exchange rate, VIX), with no exchange session |
| Fixing | fixing | a level set by a procedure at a given time (ECB); not an execution price |
| Availability | availability | the instant from which a value could be known (`available_at_utc`) |
| Vintage | vintage | the published state of a series at a given date |
| Restated series | restated | the series as published today, corrections included (`RESTATED`) |
| Cross-check | cross-check | a field-by-field comparison of two sources |
| Known gap | known gap | a missing session, explained, never filled |
| Corporate action | corporate action | a split, a dividend or a spin-off, which changes the securities or the cash flows; see [CORPORATE_ACTIONS.md](CORPORATE_ACTIONS.md) |
| Ex-date | ex-date | the first day the security trades without the entitlement |
| Raw / adjusted price | raw / adjusted | the quotation / the price recomputed backwards to neutralise the known corporate actions (`PriceBasis`) |
| Total return | total return | a performance that includes distributions under a reinvestment rule (`BenchmarkBasis.TOTAL_RETURN`) |
| Signal, indicator | signal | a number and a status per instrument, computed on a past window; never an order |
| Window | window | the observations a signal reads, under a contract (`WindowSpec`) |
| Momentum | momentum | the past return, read as a trend; does not prove that the trend continues |
| Mean reversion | mean reversion | here, the opposite of the return; no equilibrium mean is estimated |
| Moving average | moving average | an average recomputed over a window that moves forward |
| Volatility | volatility | the standard deviation of returns, annualised; does not tell a rise from a fall |
| Z-score | z-score | the distance from the window's mean, in standard deviations |
| Strategy | strategy | the rule that turns signals into a target allocation |
| Target weight | target weight | the fraction of capital wanted in an instrument, before costs and lots |
| Target allocation | `TargetAllocation` | what the strategy asks for |
| Constrained target | `ConstrainedTarget` | what the limits allow |
| Position | holding, position | a quantity actually held (`PortfolioState`) |
| Cash | cash | the money not invested; it earns nothing in the engine |
| Equity, book value | equity | cash plus the value of the positions |
| Average cost | average cost | the cost price per unit, fees included; not a tax calculation |
| Rebalancing | rebalancing | bringing positions back to a target, which costs transactions |
| Buy and hold | buy and hold | keeping the quantities; the weights drift |
| Rotation | rotation | switching instrument according to a ranking |
| Order | order | a request to the market |
| Fill | fill | the part of an order actually executed, at the price paid |
| Reject | reject | an order not executed, with its reason (`ExecutionRejectReason`) |
| Opening auction | opening auction | the common price set at the open; it is the engine's execution price |
| Bid / ask | bid / ask | the prices at which one can sell / buy immediately |
| Spread, half spread | spread, half spread | the difference between ask and bid; a purchase pays half of it above the mid |
| Slippage | slippage | the additional adverse gap to the theoretical price |
| Commission | commission | the broker's fees, with a floor |
| Lot | lot, quantity step | the tradable quantity step; 1 = whole units |
| Gross / net | gross / net | the same transactions without / with the fees |
| Turnover | turnover | the amount traded relative to the average capital |
| Drawdown | drawdown | the relative distance to the highest value already reached |
| Sharpe ratio | Sharpe ratio | the excess return over the risk-free rate, relative to its dispersion |
| Benchmark | benchmark | what the run is compared with: a unit held without costs |
| Executable control | executable control | a simple strategy (buy and hold) played under the same costs |
| Block bootstrap | block bootstrap | a resampling of blocks of consecutive sessions, for an interval |
| Look-ahead bias | look-ahead bias | using information that did not exist yet |
| Survivorship bias | survivorship bias | keeping only the instruments still listed today |
| Overfitting | overfitting | choosing a rule that explains the noise of the past |
| Preregistered hypothesis | preregistered hypothesis | a rule and a prediction written before the trials (`PREREGISTERED`) |
| Out of sample | out of sample | data that served for no choice |
| Paper trading | paper trading | following a frozen rule over time, with no real money |
| Fingerprint | fingerprint | the hash of a definition; it identifies, it does not prove the absence of a bug |
| Provenance | provenance | what identifies the code, the data and the parameters of a result (`run_id`) |
