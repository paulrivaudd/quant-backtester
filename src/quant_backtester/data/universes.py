"""Which instruments a strategy was allowed to choose from, on the day it chose.

A universe written as a list of names is a list of the names that **still
exist**, which is the oldest bias in the business. Yahoo returns nothing for
TWTR, SIVB or CELG: a backtest whose universe is "the S&P 500 today" run back
over ten years is a backtest of the companies that made it through, and it will
show a return the strategy never earned.

So membership is data, dated like everything else here. A universe is a set of
windows - this name, from this date, until that one - and the engine asks it
what the universe held on the session it is deciding on, not what it holds now.
Two things follow, and both are deliberate:

- A member that left is still in the file. Removing it would recreate the bias
  the file exists to remove, and a window that ended is what says a name was
  there and then was not.
- A window left open in the file is closed with the instrument's own listing
  dates when it is read. A fund launched in 2018 is not a member of anything in
  2010, and a universe that answered otherwise would hand a backtest a name to
  rank that did not exist.
- A membership window must lie inside the instrument's listing window. A name
  cannot be in an index before it was listed, and a file that says otherwise is
  a mistake, not an edge case to be worked around silently.

What this module does not do is get the data. A name whose history the provider
no longer serves needs its raw archived before it disappears; membership dated
correctly and history missing is a different failure, and the reader reports it
as ``NOT_LISTED`` or as a hole rather than hiding it.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from quant_backtester.data.instruments import InstrumentRegistry


@runtime_checkable
class UniverseSource(Protocol):
    """What anything asking a universe a question needs of it: its members on a day.

    A :class:`Universe` answers it from dated memberships and a
    :class:`StaticUniverse` answers the same thing every day. The question is
    asked once per session, and the caller never learns which kind it holds.

    It is declared here, in the layer that owns membership, rather than in the
    engine that walks the sessions: a signal may be computed over a dated
    universe of its own, and ``signals`` sits below ``backtest`` and cannot
    import from it.
    """

    def members_at(self, on: date) -> Sequence[str]:
        """Return the instruments the universe held on ``on``."""
        ...


@dataclass(frozen=True, slots=True)
class Membership:
    """One instrument's stay in a universe.

    Attributes
    ----------
    instrument_id : str
        The member.
    from_date : date | None
        First session it was a member on, inclusive. ``None`` is an open
        bound - a universe read from a file never carries one, because the
        loader fills it in from the instrument's first session: a name cannot
        be a member of anything before it was listed, and a window left open
        would say it was.
    until_date : date | None
        Last session it was a member on, inclusive. ``None`` is open in the
        same sense, and is filled in from a delisted instrument's last session.

    Raises
    ------
    ValueError
        If the window is empty - a membership that ends before it starts is a
        typo, and the day it is read is the day to say so.
    """

    instrument_id: str
    from_date: date | None = None
    until_date: date | None = None

    def __post_init__(self) -> None:
        """Reject a window that cannot describe a stay."""
        if not self.instrument_id or not self.instrument_id.strip():
            raise ValueError("a membership names an instrument")
        if (
            self.from_date is not None
            and self.until_date is not None
            and self.from_date > self.until_date
        ):
            raise ValueError(
                f"{self.instrument_id} is a member from {self.from_date} until "
                f"{self.until_date}, which is before it started"
            )

    def covers(self, on: date) -> bool:
        """Return whether the instrument was a member on ``on``."""
        after_start = self.from_date is None or on >= self.from_date
        before_end = self.until_date is None or on <= self.until_date
        return after_start and before_end

    def overlaps(self, other: Membership) -> bool:
        """Return whether two stays of the same instrument share a day.

        Parameters
        ----------
        other : Membership
            The stay to compare with.

        Returns
        -------
        bool
            ``True`` when both windows hold a common date. A name that left an
            index and came back years later has two stays, and that is
            legitimate; two stays that overlap say the file was edited twice
            for the same period and nobody noticed.
        """
        start = _latest(self.from_date, other.from_date)
        end = _earliest(self.until_date, other.until_date)
        if start is None or end is None:
            return True
        return start <= end


def _latest(first: date | None, second: date | None) -> date | None:
    """Return the later of two open-ended starts, ``None`` if both are open."""
    if first is None:
        return second
    if second is None:
        return first
    return max(first, second)


def _earliest(first: date | None, second: date | None) -> date | None:
    """Return the earlier of two open-ended ends, ``None`` if both are open."""
    if first is None:
        return second
    if second is None:
        return first
    return min(first, second)


@dataclass(frozen=True, slots=True)
class Universe:
    """A named set of dated memberships.

    Attributes
    ----------
    universe_id : str
        Stable identifier, e.g. ``"ROTATION_2"``.
    name : str
        Human-readable label, for reports.
    memberships : tuple[Membership, ...]
        The stays, in declared order.

    Raises
    ------
    ValueError
        If the universe holds no member, or if one instrument has two stays
        that overlap.
    """

    universe_id: str
    name: str
    memberships: tuple[Membership, ...]

    def __post_init__(self) -> None:
        """Reject a universe nobody could choose from, or one that repeats itself."""
        if not self.universe_id or not self.universe_id.strip():
            raise ValueError("a universe has an id")
        if not self.memberships:
            raise ValueError(f"universe {self.universe_id} holds no member")
        by_instrument: dict[str, list[Membership]] = {}
        for membership in self.memberships:
            by_instrument.setdefault(membership.instrument_id, []).append(membership)
        for instrument_id, stays in by_instrument.items():
            for index, stay in enumerate(stays):
                for other in stays[index + 1 :]:
                    if stay.overlaps(other):
                        raise ValueError(
                            f"universe {self.universe_id} holds two overlapping stays of "
                            f"{instrument_id}"
                        )

    def members_at(self, on: date) -> tuple[str, ...]:
        """Return the instruments in the universe on a given session.

        Parameters
        ----------
        on : date
            Session date of the decision, on the engine's reference calendar.

        Returns
        -------
        tuple[str, ...]
            Sorted, so a run does not depend on the order of the file, and
            possibly empty: a universe can have no member on a day, and an
            empty set is an answer rather than a failure.
        """
        return tuple(
            sorted(
                {
                    membership.instrument_id
                    for membership in self.memberships
                    if membership.covers(on)
                }
            )
        )

    def instruments(self) -> tuple[str, ...]:
        """Return every instrument that was ever a member, sorted."""
        return tuple(sorted({membership.instrument_id for membership in self.memberships}))


@dataclass(frozen=True, slots=True)
class StaticUniverse:
    """The same instruments on every session.

    Attributes
    ----------
    members : tuple[str, ...]
        The instruments, in declared order.

    Raises
    ------
    ValueError
        If an instrument appears twice.

    Notes
    -----
    Honest for a run over two funds that both existed throughout, and a lie for
    anything with entries and exits. It exists so that a test or a one-off
    script does not have to write a file, and it answers the same question a
    :class:`Universe` does, so nothing above has to know which one it was given.
    """

    members: tuple[str, ...]

    def __post_init__(self) -> None:
        """Reject a universe that holds an instrument twice."""
        repeated = sorted({name for name in self.members if self.members.count(name) > 1})
        if repeated:
            raise ValueError(f"Universe holds {', '.join(repeated)} more than once")

    def members_at(self, on: date) -> tuple[str, ...]:
        """Return the members, whatever the date."""
        return self.members

    def instruments(self) -> tuple[str, ...]:
        """Return every member, sorted."""
        return tuple(sorted(self.members))


class UniverseRegistry:
    """Every universe declared in committed configuration.

    Parameters
    ----------
    universes : Sequence[Universe]
        The universes, each with a unique id.

    Raises
    ------
    ValueError
        If two universes share an id.
    """

    def __init__(self, universes: Sequence[Universe]) -> None:
        self._universes: dict[str, Universe] = {}
        for universe in universes:
            if universe.universe_id in self._universes:
                raise ValueError(f"Two universes share the id {universe.universe_id}")
            self._universes[universe.universe_id] = universe

    @classmethod
    def from_toml(cls, path: Path, instruments: InstrumentRegistry) -> UniverseRegistry:
        """Load the universes from a TOML file and check them against the registry.

        Parameters
        ----------
        path : Path
            File of ``[[universe]]`` tables, each holding ``[[universe.member]]``
            sub-tables with an ``instrument_id`` and optional ``from_date`` and
            ``until_date``. TOML dates are read as dates, not as strings.
        instruments : InstrumentRegistry
            Registry every member is resolved against. Required, not optional:
            a membership naming an instrument nobody declared, or one that
            starts before its instrument was listed, is exactly the mistake
            this file exists to prevent, and it is caught when the file is
            read rather than when a backtest walks over that date.

        Returns
        -------
        UniverseRegistry
            The declared universes.

        Raises
        ------
        FileNotFoundError
            If the file does not exist.
        ValueError
            If a table is malformed, a member is unknown, or a stay falls
            outside its instrument's listing window.
        """
        with path.open("rb") as handle:
            document = tomllib.load(handle)
        tables = document.get("universe", [])
        if not isinstance(tables, list):
            raise ValueError(f"{path}: 'universe' must be a list of tables")
        universes = [_universe_from_table(table, path, instruments) for table in tables]
        return cls(universes)

    def get(self, universe_id: str) -> Universe:
        """Return one universe by id.

        Raises
        ------
        KeyError
            If no universe carries that id.
        """
        try:
            return self._universes[universe_id]
        except KeyError:
            raise KeyError(f"Unknown universe: {universe_id}") from None

    def __iter__(self) -> Iterator[Universe]:
        """Iterate over the universes, in declared order."""
        return iter(self._universes.values())

    def __len__(self) -> int:
        """Return how many universes are declared."""
        return len(self._universes)

    def __contains__(self, universe_id: object) -> bool:
        """Return whether a universe id is declared."""
        return universe_id in self._universes


def _universe_from_table(table: object, path: Path, instruments: InstrumentRegistry) -> Universe:
    """Build one universe from its TOML table, checked against the registry."""
    if not isinstance(table, dict):
        raise ValueError(f"{path}: each 'universe' entry must be a table")
    universe_id = table.get("id")
    if not isinstance(universe_id, str):
        raise ValueError(f"{path}: a universe needs a string 'id'")
    name = table.get("name", universe_id)
    if not isinstance(name, str):
        raise ValueError(f"{path}: universe {universe_id} has a non-string 'name'")
    members = table.get("member", [])
    if not isinstance(members, list):
        raise ValueError(f"{path}: universe {universe_id} must hold a list of 'member' tables")
    memberships = tuple(
        _membership_from_table(member, path, universe_id, instruments) for member in members
    )
    return Universe(universe_id=universe_id, name=name, memberships=memberships)


def _membership_from_table(
    table: object, path: Path, universe_id: str, instruments: InstrumentRegistry
) -> Membership:
    """Build one membership, resolving its instrument and checking its window."""
    if not isinstance(table, dict):
        raise ValueError(f"{path}: each member of {universe_id} must be a table")
    unknown = sorted(set(table) - {"instrument_id", "from_date", "until_date"})
    if unknown:
        raise ValueError(f"{path}: member of {universe_id} holds unknown key(s): {unknown}")
    instrument_id = table.get("instrument_id")
    if not isinstance(instrument_id, str):
        raise ValueError(f"{path}: a member of {universe_id} needs a string 'instrument_id'")
    instrument = instruments.get(instrument_id)
    declared_from = _optional_date(table.get("from_date"), path, universe_id, "from_date")
    declared_until = _optional_date(table.get("until_date"), path, universe_id, "until_date")
    for bound, day in (("from_date", declared_from), ("until_date", declared_until)):
        if day is not None and not instrument.is_listed(day):
            raise ValueError(
                f"{path}: {instrument_id} is a member of {universe_id} with {bound} {day}, "
                f"outside its listing window "
                f"[{instrument.first_session}, {instrument.last_session}]"
            )
    # An absent bound is closed with the instrument's own: a fund launched in
    # 2018 was not a member of anything in 2010, and a run reaching back that
    # far must see a universe without it rather than a name the reader will
    # then have to report as NOT_LISTED.
    return Membership(
        instrument_id=instrument_id,
        from_date=declared_from if declared_from is not None else instrument.first_session,
        until_date=declared_until if declared_until is not None else instrument.last_session,
    )


def _optional_date(value: object, path: Path, universe_id: str, key: str) -> date | None:
    """Return a TOML date, or ``None`` when the key is absent."""
    if value is None:
        return None
    # A TOML date-time is a date to Python, and it is not one here: a
    # membership changes at a session boundary, and an instant would suggest
    # an intraday precision the calendar behind it cannot serve.
    if isinstance(value, datetime) or not isinstance(value, date):
        raise ValueError(
            f"{path}: {key} of a member of {universe_id} must be a TOML date, got {value!r}"
        )
    return value
