"""What the strategies package exports: every class of it runs as it stands."""

from __future__ import annotations


def test_every_strategy_this_package_exports_can_be_run_as_it_stands() -> None:
    """A strategy that needed its signals wired in from outside looks the same.

    It looks identical in an import list, and fails at the first decision with
    a ``KeyError`` on a signal nobody computed. So every exported strategy
    declares what it reads, and this is what says so.
    """
    import quant_backtester.strategies as package
    from quant_backtester.strategies import (
        SA15GPT61,
        ArimaGarch,
        BufferedDualMomentum,
        ETFEnsemble,
        EwmaVolControl,
        FactorETFBlend,
        GarchVolControl,
        MonetaryCarry,
        RealizedVolControl,
        RelativeResidualTilt,
        SmoothMovingAverage,
        TrendFilteredPullback,
        VixReliefEntry,
        WorldMA20Benchmark,
    )
    from quant_backtester.strategies.base import Strategy as Contract

    runnable = {
        WorldMA20Benchmark(instrument_id="ETF_EU"),
        BufferedDualMomentum(first_id="ETF_EU", second_id="ETF_OTHER"),
        SmoothMovingAverage(instrument_id="ETF_EU"),
        TrendFilteredPullback(instrument_id="ETF_EU"),
        RelativeResidualTilt(first_id="ETF_EU", second_id="ETF_OTHER"),
        RealizedVolControl(instrument_id="ETF_EU"),
        GarchVolControl(instrument_id="ETF_EU"),
        ArimaGarch(instrument_id="ETF_EU"),
        EwmaVolControl(instrument_id="ETF_EU"),
        FactorETFBlend(instrument_ids=("ETF_EU", "ETF_OTHER", "ETF_LATE")),
        MonetaryCarry(instrument_id="ETF_LATE"),
        VixReliefEntry(instrument_id="ETF_OTHER", vix_id="RATE_US"),
        SA15GPT61(
            risky_ids=("ETF_EU", "ETF_OTHER"),
            monetary_id="ETF_LATE",
            core_id="ETF_EU",
        ),
        ETFEnsemble(
            enable_factors=False,
            enable_monetary=False,
            world_id="ETF_EU",
            sp500_id="ETF_OTHER",
            vix_id="RATE_US",
        ),
    }
    exported = {
        name
        for name in package.__all__
        if isinstance(getattr(package, name), type)
        and issubclass(getattr(package, name), Contract)
        and getattr(package, name) is not Contract
        and name != "FunctionalStrategy"  # a form, not a strategy of its own
    }

    assert exported == {type(strategy).__name__ for strategy in runnable}
    for strategy in runnable:
        # Declared, not wired: every signal a decision reads comes from here.
        assert isinstance(strategy.required_signals(), tuple)
