"""What a book may hold at all, checked before anything is sized.

Two kinds of rule stand between a strategy's wish and an order, and they are
handled in opposite ways on purpose:

- a **risk limit** - no more than 40% in one name - is policy. Exceeding it is
  an ordinary outcome of a strategy's arithmetic, so the weight is cut to it
  and the cut is recorded (:mod:`quant_backtester.portfolio.limits`);
- an **admissibility rule** - the instrument exists, can be bought, is quoted in
  the book's currency and is in the trading universe of the day - is a fact
  about the world. Breaking one is a configuration or wiring mistake, and it
  raises here rather than becoming a flat day: a strategy that ranked, chose
  and sized a position in an index would otherwise report a rotation whose
  orders were quietly never sent.

The trading universe is checked the same way, and earlier still: a run whose
universe holds an instrument the book may not hold fails before its first
session, not on the day that instrument first comes up.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from datetime import date

from quant_backtester.data.instruments import InstrumentRegistry


class InadmissibleTarget(ValueError):
    """Raised when a target names an instrument the book may not hold."""


class UnknownInstrument(InadmissibleTarget):
    """The registry does not know the instrument - a typo, or an id from elsewhere."""


class NonTradableInstrument(InadmissibleTarget):
    """The registry declares the instrument ``tradable = false``: it can be read, not held."""


class CurrencyMismatch(InadmissibleTarget):
    """The instrument is quoted in another currency than the book, and nothing converts it."""


class OutsideTradingUniverse(InadmissibleTarget):
    """The instrument is not in the trading universe on the session being decided."""


class InvalidTradingUniverse(ValueError):
    """Raised when a trading universe holds an instrument no book could hold."""


class UnknownInstrumentInTradingUniverse(InvalidTradingUniverse):
    """A member the registry does not know."""


class NonTradableInstrumentInTradingUniverse(InvalidTradingUniverse):
    """A member declared ``tradable = false`` - an index, a yield, a gauge."""


class CurrencyMismatchInTradingUniverse(InvalidTradingUniverse):
    """A member quoted in another currency than the book."""


def check_admissible(
    instrument_ids: Iterable[str],
    *,
    instruments: InstrumentRegistry,
    universe: Collection[str],
    base_currency: str,
) -> None:
    """Raise unless every instrument named is one the book may hold now.

    Parameters
    ----------
    instrument_ids : Iterable[str]
        Every instrument a target names, a zero weight included: a target
        that mentions an index at all was written against the wrong list.
    instruments : InstrumentRegistry
        What each instrument is.
    universe : Collection[str]
        The trading universe on the session being decided.
    base_currency : str
        The currency the book is kept in.

    Raises
    ------
    UnknownInstrument
        If the registry does not know an instrument. It is also how two
        spellings of one instrument - a stray space, another case - are
        refused rather than held as two positions.
    NonTradableInstrument
        If an instrument is declared ``tradable = false``.
    CurrencyMismatch
        If an instrument is quoted in another currency than the book.
    OutsideTradingUniverse
        If an instrument is not in the day's trading universe. A strategy may
        read anything the registry declares, and may only target these.

    Notes
    -----
    Checked in instrument order, so the error a wrong target raises does not
    depend on the order its weights were written in.
    """
    for instrument_id in sorted(instrument_ids):
        if instrument_id not in instruments:
            raise UnknownInstrument(f"{instrument_id!r} is not an instrument of the registry")
        instrument = instruments.get(instrument_id)
        if not instrument.tradable:
            raise NonTradableInstrument(
                f"{instrument_id} is declared tradable = false: a strategy may read it and may "
                "not hold it"
            )
        if instrument.currency != base_currency:
            raise CurrencyMismatch(
                f"{instrument_id} is quoted in {instrument.currency} and the book is kept in "
                f"{base_currency}; nothing here converts a currency"
            )
        if instrument_id not in universe:
            raise OutsideTradingUniverse(
                f"{instrument_id} is not in this session's trading universe "
                f"({', '.join(sorted(universe)) or 'empty'}); it can be read, not held"
            )


def check_trading_universe(
    members: Iterable[str],
    *,
    instruments: InstrumentRegistry,
    base_currency: str,
    on: date | None = None,
) -> None:
    """Raise unless every member of a trading universe is one a book could hold.

    Parameters
    ----------
    members : Iterable[str]
        The members, on one session or over a whole run.
    instruments : InstrumentRegistry
        What each instrument is.
    base_currency : str
        The currency the book is kept in.
    on : date | None
        The session the members were read for, quoted in the message.

    Raises
    ------
    UnknownInstrumentInTradingUniverse
        If a member is not in the registry.
    NonTradableInstrumentInTradingUniverse
        If a member is declared ``tradable = false``. A signal reads such an
        instrument through a request of its own; it is never a thing to buy.
    CurrencyMismatchInTradingUniverse
        If a member is quoted in another currency than the book. An instrument
        a signal only reads may be quoted in anything, since it is never held.
    """
    when = f" on {on.isoformat()}" if on is not None else ""
    for instrument_id in sorted(set(members)):
        if instrument_id not in instruments:
            raise UnknownInstrumentInTradingUniverse(
                f"{instrument_id!r} is in the trading universe{when} and not in the registry"
            )
        instrument = instruments.get(instrument_id)
        if not instrument.tradable:
            raise NonTradableInstrumentInTradingUniverse(
                f"{instrument_id} is declared tradable = false and cannot be in the trading "
                f"universe{when}; a signal reads it through a SignalRequest of its own"
            )
        if instrument.currency != base_currency:
            raise CurrencyMismatchInTradingUniverse(
                f"{instrument_id} is quoted in {instrument.currency} and the book is kept in "
                f"{base_currency}; nothing here converts a currency"
            )
