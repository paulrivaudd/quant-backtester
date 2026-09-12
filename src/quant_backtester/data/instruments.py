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
from dataclasses import dataclass, fields
from datetime import UTC, date, datetime, time, timedelta
from enum import Enum
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


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

    A published series has no exchange calendar: its availability is set by the
    publisher's release schedule. ECB reference rates are published around 16:00
    CET for the same day; a FRED series may land the following business day.

    Attributes
    ----------
    publication_time : time
        Local wall-clock release time, in ``timezone``.
    timezone : str
        IANA zone name, e.g. ``"Europe/Paris"``. Never a fixed UTC offset: the
        release time is a local wall clock and moves with DST.
    lag_days : int
        Calendar days between the observation date and the release date.
    """

    publication_time: time
    timezone: str
    lag_days: int = 0

    def available_at(self, observation_date: date) -> datetime:
        """Return the UTC instant at which ``observation_date`` becomes public.

        Parameters
        ----------
        observation_date : date
            Calendar day the observation describes.

        Returns
        -------
        datetime
            Timezone-aware UTC instant.

        Notes
        -----
        Exercice 1.1 (facile). Compose ``observation_date + lag_days`` avec
        ``publication_time`` dans ``ZoneInfo(self.timezone)``, puis convertis en
        UTC. Piege : ne construis jamais un datetime naif puis ne lui greffe un
        fuseau apres coup - passe ``tzinfo`` a la construction.
        """
        # Le lag porte sur la date, pas sur l'instant : les jours sont ajoutes au
        # calendrier local avant la conversion. Ajouter 24 h a l'instant UTC
        # decalerait la publication d'une heure autour d'un changement d'heure.
        jour_de_diffusion = observation_date + timedelta(days=self.lag_days)
        zone = ZoneInfo(self.timezone)
        local_time = datetime.combine(jour_de_diffusion, self.publication_time, tzinfo=zone)
        return local_time.astimezone(UTC)


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

    def __post_init__(self) -> None:
        """Reject an instrument whose availability could not be computed.

        Raises
        ------
        ValueError
            If a ``BAR`` has no ``calendar_id``, if a ``LEVEL`` has no
            ``publication_rule``, or if either carries the other's field.

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
sharper one: ``lag_days`` carries a default, so a mistyped key falls back to
zero rather than failing, and a series released on D+1 silently becomes
readable on D. That is look-ahead bias introduced by a typo.
"""


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


def _require(table: Mapping[str, Any], key: str, context: str) -> object:
    """Return ``table[key]``, naming both the key and its location if absent.

    Parameters
    ----------
    table : Mapping[str, Any]
        Parsed TOML table.
    key : str
        Required key.
    context : str
        Where the table sits.

    Returns
    -------
    object
        The value, deliberately untyped: TOML guarantees nothing about it, and
        the conversion to the field's real type belongs to the caller.

    Raises
    ------
    ValueError
        If the key is absent. ``tomllib`` hands back a plain dict, so this would
        otherwise surface as a bare ``KeyError('name')`` with nothing to say
        which entry of which file to go and fix.
    """
    if key not in table:
        raise ValueError(f"{context} is missing the required key {key!r}")
    return table[key]


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
        publication_rule = PublicationRule(
            publication_time=_as_publication_time(
                _require(raw_rule, "publication_time", rule_context), rule_context
            ),
            timezone=_require(raw_rule, "timezone", rule_context),
            lag_days=raw_rule.get("lag_days", 0),
        )

    return Instrument(
        id=_require(table, "id", context),
        name=_require(table, "name", context),
        asset_type=AssetType(_require(table, "asset_type", context)),
        data_type=DataType(_require(table, "data_type", context)),
        currency=_require(table, "currency", context),
        primary_source=_require(table, "primary_source", context),
        source_symbol=_require(table, "source_symbol", context),
        tradable=_require(table, "tradable", context),
        calendar_id=table.get("calendar_id"),
        publication_rule=publication_rule,
        first_session=_as_session_date(table.get("first_session"), "first_session", context),
        last_session=_as_session_date(table.get("last_session"), "last_session", context),
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
