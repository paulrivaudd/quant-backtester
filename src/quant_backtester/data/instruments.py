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
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, fields
from datetime import UTC, date, datetime, time, timedelta
from enum import Enum
from pathlib import Path
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
        # Le lag porte sur la date, pas sur l'instant : convertir en UTC puis
        # ajouter 24 h decale d'une heure autour d'un changement d'heure.
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

        Notes
        -----
        Exercice 1.5 (moyen). Utilise ``tomllib.load`` en mode binaire. TOML
        rend les dates nativement (``first_session = 1990-01-02``), mais les
        enums et ``PublicationRule`` sont a reconstruire a la main. Fais
        remonter une erreur claire sur une cle inconnue plutot que de l'ignorer :
        une faute de frappe dans la config doit echouer bruyamment.
        """
        with path.open("rb") as fh:
            raw = tomllib.load(fh)

        instruments = []
        for raw_instrument in raw["instrument"]:
            unknown = set(raw_instrument) - INSTRUMENT_KEYS
            if unknown:
                entry = raw_instrument.get("id", "<entry without an id>")
                raise ValueError(
                    f"Instrument {entry} has unknown key(s): {', '.join(sorted(unknown))}"
                )
            publication_rule = None
            if "publication_rule" in raw_instrument:
                raw_rule = raw_instrument["publication_rule"]
                publication_rule = PublicationRule(
                    publication_time=time.fromisoformat(raw_rule["publication_time"]),
                    timezone=raw_rule["timezone"],
                    lag_days=raw_rule.get("lag_days", 0),
                )
            instrument = Instrument(
                id=raw_instrument["id"],
                name=raw_instrument["name"],
                asset_type=AssetType(raw_instrument["asset_type"]),
                data_type=DataType(raw_instrument["data_type"]),
                currency=raw_instrument["currency"],
                primary_source=raw_instrument["primary_source"],
                source_symbol=raw_instrument["source_symbol"],
                tradable=raw_instrument["tradable"],
                calendar_id=raw_instrument.get("calendar_id"),
                publication_rule=publication_rule,
                first_session=raw_instrument.get("first_session"),
                last_session=raw_instrument.get("last_session"),
            )
            instruments.append(instrument)
        return cls(instruments)

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
        return sorted(self._instruments.values(), key=lambda x: x.id)
        # lambda x: x.id est une fonction anonyme qui prend un instrument x et retourne son id.

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
