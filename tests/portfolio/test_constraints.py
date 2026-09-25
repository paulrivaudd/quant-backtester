"""Admissibility: what a book may hold at all, refused loudly rather than clipped quietly."""

from __future__ import annotations

from datetime import date

import pytest

from quant_backtester.data.instruments import InstrumentRegistry
from quant_backtester.portfolio.constraints import (
    CurrencyMismatch,
    CurrencyMismatchInTradingUniverse,
    InadmissibleTarget,
    InvalidTradingUniverse,
    NonTradableInstrument,
    NonTradableInstrumentInTradingUniverse,
    OutsideTradingUniverse,
    UnknownInstrument,
    UnknownInstrumentInTradingUniverse,
    check_admissible,
    check_trading_universe,
)

UNIVERSE = ("ETF_EU", "ETF_OTHER")


def admissible(names: list[str], instruments: InstrumentRegistry) -> None:
    """Check a target naming ``names`` for a euro book over the usual universe."""
    check_admissible(names, instruments=instruments, universe=UNIVERSE, base_currency="EUR")


def test_a_euro_book_accepts_a_euro_fund_of_its_universe(instruments: InstrumentRegistry) -> None:
    """The ordinary case passes without a word."""
    admissible(["ETF_EU", "ETF_OTHER"], instruments)


def test_an_instrument_nobody_can_buy_cannot_enter_a_target(
    instruments: InstrumentRegistry,
) -> None:
    """An index can be read, never held - and asking to hold one is an error, not a clip."""
    with pytest.raises(NonTradableInstrument, match="IDX_US is declared tradable = false"):
        check_admissible(
            ["IDX_US"],
            instruments=instruments,
            universe=(*UNIVERSE, "IDX_US"),
            base_currency="EUR",
        )


def test_a_euro_book_refuses_a_fund_quoted_in_dollars(instruments: InstrumentRegistry) -> None:
    """Nothing converts a currency, so adding dollars to euros is refused."""
    with pytest.raises(CurrencyMismatch, match="ETF_US is quoted in USD"):
        check_admissible(
            ["ETF_US"], instruments=instruments, universe=("ETF_US",), base_currency="EUR"
        )


def test_a_name_outside_the_day_s_universe_cannot_be_held(instruments: InstrumentRegistry) -> None:
    """A strategy may read anything the registry declares, and may only target these."""
    with pytest.raises(OutsideTradingUniverse, match="ETF_LATE is not in this session"):
        admissible(["ETF_LATE"], instruments)


def test_a_name_the_registry_does_not_know_is_refused(instruments: InstrumentRegistry) -> None:
    """Two spellings of one fund are two positions unless the registry settles it."""
    with pytest.raises(UnknownInstrument, match="'ETF_EU '"):
        admissible(["ETF_EU "], instruments)


def test_a_zero_weight_on_a_forbidden_instrument_is_still_refused(
    instruments: InstrumentRegistry,
) -> None:
    """A target that mentions an index at all was written against the wrong list."""
    with pytest.raises(NonTradableInstrument):
        admissible(["ETF_EU", "IDX_US"], instruments)


def test_the_first_mistake_reported_does_not_depend_on_the_order_of_the_weights(
    instruments: InstrumentRegistry,
) -> None:
    """Checked in instrument order, so the same target raises the same error."""
    for names in (["IDX_US", "ETF_US"], ["ETF_US", "IDX_US"]):
        with pytest.raises(CurrencyMismatch, match="ETF_US"):
            check_admissible(
                names,
                instruments=instruments,
                universe=("ETF_US", "IDX_US"),
                base_currency="EUR",
            )


def test_every_refusal_is_a_value_error() -> None:
    """A caller catching configuration mistakes catches all of them."""
    refusals = (UnknownInstrument, NonTradableInstrument, CurrencyMismatch, OutsideTradingUniverse)
    for error in refusals:
        assert issubclass(error, InadmissibleTarget)
        assert issubclass(error, ValueError)


def test_a_trading_universe_of_euro_funds_is_valid(instruments: InstrumentRegistry) -> None:
    """Nothing to say about a universe a book could hold."""
    check_trading_universe(UNIVERSE, instruments=instruments, base_currency="EUR")


def test_an_index_in_a_trading_universe_is_named(instruments: InstrumentRegistry) -> None:
    """The run fails on the configuration, with the instrument and the day in the message."""
    with pytest.raises(NonTradableInstrumentInTradingUniverse, match="IDX_US") as raised:
        check_trading_universe(
            ["ETF_EU", "IDX_US"],
            instruments=instruments,
            base_currency="EUR",
            on=date(2026, 9, 1),
        )

    assert "2026-09-01" in str(raised.value)


def test_a_dollar_fund_in_a_euro_trading_universe_is_refused(
    instruments: InstrumentRegistry,
) -> None:
    """Without an FX engine, fail fast."""
    with pytest.raises(CurrencyMismatchInTradingUniverse, match="ETF_US"):
        check_trading_universe(["ETF_EU", "ETF_US"], instruments=instruments, base_currency="EUR")


def test_a_dollar_fund_is_valid_for_a_dollar_book(instruments: InstrumentRegistry) -> None:
    """The rule is one currency per book, not the euro."""
    check_trading_universe(["ETF_US"], instruments=instruments, base_currency="USD")


def test_a_member_the_registry_does_not_know_is_refused(instruments: InstrumentRegistry) -> None:
    """A universe file naming an instrument nobody declared is a typo."""
    with pytest.raises(UnknownInstrumentInTradingUniverse, match="NOPE"):
        check_trading_universe(["NOPE"], instruments=instruments, base_currency="EUR")


def test_every_universe_refusal_is_a_value_error() -> None:
    """The same family, so one ``except`` covers a wrong universe file."""
    for error in (
        UnknownInstrumentInTradingUniverse,
        NonTradableInstrumentInTradingUniverse,
        CurrencyMismatchInTradingUniverse,
    ):
        assert issubclass(error, InvalidTradingUniverse)
        assert issubclass(error, ValueError)
