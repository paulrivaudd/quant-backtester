"""Instrument registry: the static description of every series we track.

Static attributes (currency, calendar, source symbol, listing dates) are stored
once here and never repeated on an observation row. The registry is the single
place mapping a stable internal ``instrument_id`` onto a provider symbol, so a
provider renaming a ticker (FB -> META) changes one line of configuration and
nothing else.

The registry is *configuration*, not data: it lives in a committed TOML file,
because a backtest result must follow from committed code plus committed config.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, fields, replace
from datetime import UTC, date, datetime, time
from enum import Enum
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from quant_backtester.data.calendars import TradingCalendar


class DataType(Enum):
    """Shape of the observations an instrument produces."""

    BAR = "BAR"
    """Traded instrument with an opening and a closing auction (ETF, index)."""

    LEVEL = "LEVEL"
    """Single published value per observation date (rate, FX fixing, macro)."""


class AssetType(Enum):
    """Economic nature of an instrument, used to select validation rules."""

    INDEX = "INDEX"
    ETF = "ETF"
    EQUITY = "EQUITY"
    RATE = "RATE"
    FX = "FX"
    VOLATILITY = "VOLATILITY"


@dataclass(frozen=True, slots=True)
class PublicationRule:
    """When a LEVEL observation becomes publicly available.

    A published series has no exchange calendar of its own: its availability is
    set by the publisher's release schedule. ECB reference rates are published
    around 16:00 CET for the same day; a FRED series lands on the next business
    day of its publisher.

    Attributes
    ----------
    publication_time : time
        Local wall-clock release time, in ``timezone``.
    timezone : str
        IANA zone name, e.g. ``"Europe/Paris"``. Never a fixed UTC offset: the
        release time is a local wall clock and moves with DST.
    lag_sessions : int
        Sessions of ``calendar_id`` between the observation date and the release
        date. ``0`` means the value is published on the day it describes.
    calendar_id : str | None
        Calendar the lag is counted on, required when ``lag_sessions`` is not
        zero and forbidden when it is - a calendar with nothing to count would
        only suggest the rule consults one.

    Raises
    ------
    ValueError
        If ``lag_sessions`` is negative, or if it and ``calendar_id`` do not
        agree as described above.

    Notes
    -----
    The lag counts **sessions, not calendar days**. A rate observed on a Friday
    and released "the next day" is readable on Monday, and on Tuesday when the
    Monday is a holiday. Counting calendar days would make it readable on the
    Saturday, which is a decision taken on data nobody had - the exact look-ahead
    this project exists to prevent. It is also why there is no weekday-only
    option: holidays are data held by a calendar, never a ``freq="B"``
    assumption.
    """

    publication_time: time
    timezone: str
    lag_sessions: int = 0
    calendar_id: str | None = None

    def __post_init__(self) -> None:
        """Reject a lag that cannot be counted, or a calendar with nothing to count."""
        if self.lag_sessions < 0:
            raise ValueError(f"lag_sessions must be zero or more, got {self.lag_sessions}")
        if self.lag_sessions > 0 and self.calendar_id is None:
            raise ValueError(
                f"A lag of {self.lag_sessions} session(s) needs a calendar_id to count them on"
            )
        if self.lag_sessions == 0 and self.calendar_id is not None:
            raise ValueError(
                f"calendar_id {self.calendar_id!r} is set but lag_sessions is zero: "
                "a same-day release counts nothing"
            )

    def available_at(
        self, observation_date: date, calendar: TradingCalendar | None = None
    ) -> datetime:
        """Return the UTC instant at which ``observation_date`` becomes public.

        Parameters
        ----------
        observation_date : date
            Calendar day the observation describes.
        calendar : TradingCalendar | None
            Calendar named by :attr:`calendar_id`, required as soon as
            :attr:`lag_sessions` is not zero and ignored otherwise.

        Returns
        -------
        datetime
            Timezone-aware UTC instant.

        Raises
        ------
        ValueError
            If the rule counts sessions and ``calendar`` is missing or is not
            the one it names.
        CalendarCoverageError
            If the release date falls outside the calendar's covered period.

        Notes
        -----
        Exercice 1.1 (facile). Compose la date de diffusion avec
        ``publication_time`` dans ``ZoneInfo(self.timezone)``, puis convertis en
        UTC. Piege : ne construis jamais un datetime naif puis ne lui greffe un
        fuseau apres coup - passe ``tzinfo`` a la construction.
        """
        release_date = observation_date
        if self.lag_sessions:
            if calendar is None:
                raise ValueError(
                    f"A lag of {self.lag_sessions} session(s) needs the {self.calendar_id} "
                    "calendar to resolve a release date"
                )
            if calendar.calendar_id != self.calendar_id:
                raise ValueError(
                    f"The rule counts sessions of {self.calendar_id}, "
                    f"got the {calendar.calendar_id} calendar"
                )
            for _ in range(self.lag_sessions):
                release_date = calendar.next_session(release_date).session_date
        # Le lag porte sur la date, pas sur l'instant : les seances sont comptees
        # sur le calendrier local avant la conversion. Ajouter 24 h a l'instant
        # UTC decalerait la publication d'une heure autour d'un changement d'heure.
        zone = ZoneInfo(self.timezone)
        local_time = datetime.combine(release_date, self.publication_time, tzinfo=zone)
        return local_time.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class CheckSource:
    """A second provider consulted to cross-check an instrument's bars.

    Attributes
    ----------
    source : str
        Source identifier, e.g. ``"EURONEXT"``.
    source_symbol : str
        Symbol understood by that source, e.g. ``"LU1681043599-XPAR"``.
        Providers rarely share a symbology, so each check source carries its own.
    """

    source: str
    source_symbol: str


@dataclass(frozen=True, slots=True)
class Instrument:
    """Static description of one market data series.

    Attributes
    ----------
    id : str
        Stable internal identifier. Never a provider ticker: tickers are reused
        and renamed, this one is ours and never changes.
    name : str
        Human-readable label, used in reports only.
    asset_type : AssetType
        Drives the validation rules that apply.
    data_type : DataType
        ``BAR`` rows go to ``clean/bars/``, ``LEVEL`` rows to ``clean/levels/``.
    currency : str
        ISO 4217 code of the quoted value. ``"NA"`` for a rate expressed in
        percent.
    primary_source : str
        Source identifier, e.g. ``"YAHOO"``.
    source_symbol : str
        Symbol understood by that source, e.g. ``"^GSPC"``.
    tradable : bool
        Whether the execution layer may send orders on this instrument. A
        signal-only instrument (VIX, US10Y) is never tradable.
    calendar_id : str | None
        Required for ``BAR``, forbidden for ``LEVEL``.
    publication_rule : PublicationRule | None
        Required for ``LEVEL``, forbidden for ``BAR``.
    first_session : date | None
        First session on which the instrument existed. Before it, the reader
        reports ``NOT_LISTED`` rather than a missing value - the two must never
        collapse into the same ``NaN``.
    last_session : date | None
        Last session, for a delisted instrument. ``None`` means still listed.
    check_sources : tuple[CheckSource, ...]
        Further providers whose bars are compared with the primary source's, in
        declared order. Empty for a series with a single source.
    """

    id: str
    name: str
    asset_type: AssetType
    data_type: DataType
    currency: str
    primary_source: str
    source_symbol: str
    tradable: bool
    calendar_id: str | None = None
    publication_rule: PublicationRule | None = None
    first_session: date | None = None
    last_session: date | None = None
    check_sources: tuple[CheckSource, ...] = ()

    def __post_init__(self) -> None:
        """Reject an instrument whose availability could not be computed.

        Raises
        ------
        ValueError
            If a ``BAR`` has no ``calendar_id``, if a ``LEVEL`` has no
            ``publication_rule``, or if either carries the other's field; if
            ``check_sources`` is not a tuple of :class:`CheckSource`, names a
            source twice (primary included), or is set on a ``LEVEL``.

        Notes
        -----
        Exercice 1.2 (facile). Ces invariants sont la seule garantie que
        ``available_at`` sera toujours calculable. Les verifier a la
        construction evite un ``None`` qui remonte jusqu'au reader.
        """
        if self.data_type == DataType.BAR:
            if self.calendar_id is None:
                raise ValueError(f"BAR instrument {self.id} has no calendar_id")
            if self.publication_rule is not None:
                raise ValueError(f"BAR instrument {self.id} has a publication_rule")
        if self.data_type == DataType.LEVEL:
            if self.publication_rule is None:
                raise ValueError(f"LEVEL instrument {self.id} has no publication_rule")
            if self.calendar_id is not None:
                raise ValueError(f"LEVEL instrument {self.id} has a calendar_id")
        if not isinstance(self.check_sources, tuple) or not all(
            isinstance(check, CheckSource) for check in self.check_sources
        ):
            raise ValueError(f"Instrument {self.id}: check_sources must be a tuple of CheckSource")
        repeated = sorted({source for source in self.sources if self.sources.count(source) > 1})
        if repeated:
            raise ValueError(
                f"Instrument {self.id} lists source(s) {', '.join(repeated)} more than once"
            )
        if self.check_sources and self.data_type != DataType.BAR:
            raise ValueError(
                f"Instrument {self.id} is a {self.data_type.value}: "
                "only BAR series are cross-checked"
            )

    @property
    def sources(self) -> tuple[str, ...]:
        """Return every source of the instrument, primary first, then check sources."""
        return (self.primary_source, *(check.source for check in self.check_sources))

    def for_source(self, source: str) -> Instrument:
        """Return the instrument as one of its sources sees it.

        Adapters read ``primary_source`` and ``source_symbol`` only. For a check
        source, the copy returned carries that source and its symbol and no check
        sources of its own; ``id`` and every other field are unchanged, so the
        download lands under the same instrument.

        Parameters
        ----------
        source : str
            Primary or check source identifier.

        Returns
        -------
        Instrument
            ``self`` for the primary source, a re-pointed copy otherwise.

        Raises
        ------
        KeyError
            If ``source`` is neither the primary source nor a check source.
        """
        if source == self.primary_source:
            return self
        for check in self.check_sources:
            if check.source == source:
                return replace(
                    self,
                    primary_source=check.source,
                    source_symbol=check.source_symbol,
                    check_sources=(),
                )
        raise KeyError(f"Instrument {self.id} has no source {source}")

    def is_listed(self, on: date) -> bool:
        """Return whether the instrument existed on ``on``.

        Parameters
        ----------
        on : date
            Session date to test.

        Returns
        -------
        bool
            ``True`` if ``on`` falls within ``[first_session, last_session]``.

        Notes
        -----
        Exercice 1.3 (facile). Des bornes ``None`` sont ouvertes.
        """
        after_first = self.first_session is None or on >= self.first_session
        before_last = self.last_session is None or on <= self.last_session
        return after_first and before_last


INSTRUMENT_KEYS = frozenset(f.name for f in fields(Instrument))
"""Legitimate keys of an ``[[instrument]]`` table, derived from the dataclass.

Derived rather than retyped: a field added to :class:`Instrument` is accepted by
the loader the same day, and a key that is not one is a typo by construction.
"""

PUBLICATION_RULE_KEYS = frozenset(f.name for f in fields(PublicationRule))
"""Legitimate keys of an ``[instrument.publication_rule]`` sub-table.

Derived for the same reason as :data:`INSTRUMENT_KEYS`, and checked for a
sharper one: ``lag_sessions`` carries a default, so a mistyped key falls back
to zero rather than failing, and a series released on D+1 silently becomes
readable on D. That is look-ahead bias introduced by a typo.
"""

CHECK_SOURCE_KEYS = frozenset(f.name for f in fields(CheckSource))
"""Legitimate keys of an ``[[instrument.check_sources]]`` sub-table, all required."""


def _reject_unknown_keys(table: Mapping[str, Any], allowed: frozenset[str], context: str) -> None:
    """Raise if ``table`` carries a key outside ``allowed``.

    Parameters
    ----------
    table : Mapping[str, Any]
        Parsed TOML table.
    allowed : frozenset[str]
        The keys this table may carry.
    context : str
        Where the table sits, quoted verbatim in the error message.

    Raises
    ------
    ValueError
        If at least one key is not in ``allowed``. Every offending key is
        listed, sorted, so one run reports every typo in the entry.
    """
    unknown = set(table) - allowed
    if unknown:
        raise ValueError(f"{context} has unknown key(s): {', '.join(sorted(unknown))}")


def _require(table: Mapping[str, Any], keys: Sequence[str], context: str) -> None:
    """Check that every key is present, naming the first absent one and its location.

    Parameters
    ----------
    table : Mapping[str, Any]
        Parsed TOML table.
    keys : Sequence[str]
        Required keys, checked in order.
    context : str
        Where the table sits.

    Raises
    ------
    ValueError
        If a key is absent. ``tomllib`` hands back a plain dict, so this would
        otherwise surface as a bare ``KeyError('name')`` with nothing to say
        which entry of which file to go and fix.

    Notes
    -----
    The caller then reads ``table[key]`` itself. The value is deliberately
    untyped: TOML guarantees nothing about it, and the conversion to the field's
    real type belongs to the caller.
    """
    for key in keys:
        if key not in table:
            raise ValueError(f"{context} is missing the required key {key!r}")


def _as_session_date(value: object, key: str, context: str) -> date | None:
    """Return a session bound as a plain ``date``.

    Parameters
    ----------
    value : object
        Value parsed from TOML, or ``None`` when the key is absent.
    key : str
        Name of the bound, for the error message.
    context : str
        Where the entry sits.

    Returns
    -------
    date | None
        The bound, or ``None`` for an open one.

    Raises
    ------
    ValueError
        If the value is not a bare TOML date. ``datetime`` is rejected
        explicitly because it is a *subclass* of ``date``: it would pass a naive
        ``isinstance`` check and only fail later, inside
        :meth:`Instrument.is_listed`, comparing a datetime to a date.
    """
    if value is None:
        return None
    if isinstance(value, datetime) or not isinstance(value, date):
        raise ValueError(
            f"{context} has {key} = {value!r}; expected a bare date such as 1990-01-02"
        )
    return value


def _as_publication_time(value: object, context: str) -> time:
    """Return a release time from either TOML spelling.

    Parameters
    ----------
    value : object
        Value parsed from TOML.
    context : str
        Where the sub-table sits.

    Returns
    -------
    time
        The local wall-clock release time.

    Raises
    ------
    ValueError
        If the value is neither a TOML local time nor a string parsing as one.

    Notes
    -----
    TOML has a native local-time type, so ``publication_time = 16:15:00`` parses
    straight to a ``time`` while ``"16:15:00"`` arrives as a string. Both are
    accepted: leaving the unquoted spelling to fail would raise a ``TypeError``
    from deep inside the loader, naming neither the file nor the instrument.
    """
    if isinstance(value, time):
        return value
    if isinstance(value, str):
        return time.fromisoformat(value)
    raise ValueError(
        f"{context} has publication_time = {value!r}; expected a local time such as 16:15:00"
    )


def _instrument_from_table(table: Mapping[str, Any], path: Path) -> Instrument:
    """Build one instrument from a parsed ``[[instrument]]`` table.

    Parameters
    ----------
    table : Mapping[str, Any]
        One entry of the ``instrument`` array, as ``tomllib`` returns it.
    path : Path
        File the entry came from. Named in every error message: whoever reads
        the error is looking for a line in a TOML file.

    Returns
    -------
    Instrument
        The instrument the entry describes.

    Raises
    ------
    ValueError
        If the entry carries an unknown key, lacks a required one, or spells a
        date or a time in a way that would only fail further downstream.
    """
    context = f"Instrument {table.get('id', '<entry without an id>')} in {path}"
    _reject_unknown_keys(table, INSTRUMENT_KEYS, context)

    publication_rule = None
    raw_rule = table.get("publication_rule")
    if raw_rule is not None:
        rule_context = f"{context}: publication_rule"
        _reject_unknown_keys(raw_rule, PUBLICATION_RULE_KEYS, rule_context)
        _require(raw_rule, ("publication_time",), rule_context)
        publication_time = _as_publication_time(raw_rule["publication_time"], rule_context)
        _require(raw_rule, ("timezone",), rule_context)
        publication_rule = PublicationRule(
            publication_time=publication_time,
            timezone=raw_rule["timezone"],
            lag_sessions=raw_rule.get("lag_sessions", 0),
            calendar_id=raw_rule.get("calendar_id"),
        )

    raw_checks = table.get("check_sources", [])
    if not isinstance(raw_checks, list):
        raise ValueError(
            f"{context}: check_sources must be an array of [[instrument.check_sources]] tables"
        )
    check_sources: list[CheckSource] = []
    for position, raw_check in enumerate(raw_checks):
        check_context = f"{context}: check_sources[{position}]"
        if not isinstance(raw_check, dict):
            raise ValueError(f"{check_context} must be a table")
        _reject_unknown_keys(raw_check, CHECK_SOURCE_KEYS, check_context)
        _require(raw_check, ("source", "source_symbol"), check_context)
        check_sources.append(
            CheckSource(source=raw_check["source"], source_symbol=raw_check["source_symbol"])
        )

    _require(
        table,
        (
            "id",
            "name",
            "asset_type",
            "data_type",
            "currency",
            "primary_source",
            "source_symbol",
            "tradable",
        ),
        context,
    )
    return Instrument(
        id=table["id"],
        name=table["name"],
        asset_type=AssetType(table["asset_type"]),
        data_type=DataType(table["data_type"]),
        currency=table["currency"],
        primary_source=table["primary_source"],
        source_symbol=table["source_symbol"],
        tradable=table["tradable"],
        calendar_id=table.get("calendar_id"),
        publication_rule=publication_rule,
        first_session=_as_session_date(table.get("first_session"), "first_session", context),
        last_session=_as_session_date(table.get("last_session"), "last_session", context),
        check_sources=tuple(check_sources),
    )


class InstrumentRegistry:
    """In-memory collection of :class:`Instrument`, keyed by ``id``.

    Parameters
    ----------
    instruments : Sequence[Instrument]
        Instruments to index. Duplicate ids are a configuration error.
    """

    def __init__(self, instruments: Sequence[Instrument]) -> None:
        self._instruments: dict[str, Instrument] = {}
        for instrument in instruments:
            if instrument.id in self._instruments:
                raise ValueError(f"Duplicate instrument id {instrument.id}")
            self._instruments[instrument.id] = instrument

    @classmethod
    def from_toml(cls, path: Path) -> InstrumentRegistry:
        """Build a registry from a committed TOML file.

        Parameters
        ----------
        path : Path
            File containing an array of tables named ``instrument``.

        Returns
        -------
        InstrumentRegistry
            Registry holding one entry per table.

        Raises
        ------
        ValueError
            If the file declares no ``[[instrument]]`` table, or if any entry is
            malformed. Every message names the file and the offending entry.

        Notes
        -----
        Exercice 1.5 (moyen). Utilise ``tomllib.load`` en mode binaire. TOML
        rend les dates nativement (``first_session = 1990-01-02``), mais les
        enums et ``PublicationRule`` sont a reconstruire a la main. Fais
        remonter une erreur claire sur une cle inconnue plutot que de l'ignorer :
        une faute de frappe dans la config doit echouer bruyamment.

        Le controle des cles inconnues porte sur la sous-table
        ``publication_rule`` autant que sur l'entree elle-meme : voir
        :data:`PUBLICATION_RULE_KEYS`.
        """
        with path.open("rb") as fh:
            raw = tomllib.load(fh)

        if "instrument" not in raw:
            raise ValueError(f"{path} declares no [[instrument]] table")

        return cls([_instrument_from_table(table, path) for table in raw["instrument"]])

    def get(self, instrument_id: str) -> Instrument:
        """Return one instrument.

        Parameters
        ----------
        instrument_id : str
            Internal identifier.

        Returns
        -------
        Instrument
            The registered instrument.

        Raises
        ------
        KeyError
            If no instrument carries that id.

        Notes
        -----
        Exercice 1.6 (facile).
        """
        return self._instruments[instrument_id]

    def list_all(self) -> list[Instrument]:
        """Return every instrument, ordered by id.

        Returns
        -------
        list[Instrument]
            All registered instruments.

        Notes
        -----
        Exercice 1.7 (facile). L'ordre stable compte : il rend reproductible
        l'ordre d'ecriture des fichiers et donc les diffs.
        """
        return sorted(self._instruments.values(), key=lambda instrument: instrument.id)

    def list_tradable(self) -> list[Instrument]:
        """Return the instruments the execution layer may trade.

        Returns
        -------
        list[Instrument]
            Instruments with ``tradable=True``.

        Notes
        -----
        Exercice 1.8 (facile).
        """
        return [instr for instr in self.list_all() if instr.tradable]

    def list_by_source(self, source: str) -> list[Instrument]:
        """Return the instruments fetched from one source.

        Parameters
        ----------
        source : str
            Source identifier, e.g. ``"YAHOO"``.

        Returns
        -------
        list[Instrument]
            Matching instruments, ordered by id.

        Notes
        -----
        Exercice 1.9 (facile). Sert a grouper les telechargements par source.
        """
        return [instr for instr in self.list_all() if instr.primary_source == source]

    def __iter__(self) -> Iterator[Instrument]:
        """Iterate over instruments in id order."""
        return iter(self.list_all())

    def __len__(self) -> int:
        """Return the number of registered instruments."""
        return len(self._instruments)

    def __contains__(self, instrument_id: object) -> bool:
        """Return whether an id is registered."""
        return instrument_id in self._instruments
