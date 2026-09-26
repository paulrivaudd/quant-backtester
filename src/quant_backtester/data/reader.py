"""Read access to the clean layer, with look-ahead made unrepresentable.

Nothing above this layer receives a :class:`MarketDataReader`. What is handed
out is a :class:`PointInTimeReader`, built by the engine for one decision
instant, whose methods take no ``as_of`` argument at all. There is therefore no
expression anyone can write against it that reads the future - the protection is
structural, not a rule someone has to remember.

The engine builds two of them per trading day, and the split falls out of
field-level availability::

    pit_decision  = reader.at(23:00 Paris, day t)     # US and EU closes of t
    pit_execution = reader.at(09:01 Paris, day t+1)   # open of t+1 only

The first goes to the signals layer, the second to the execution layer::

    pit_decision  -> SignalContext -> SignalEngine -> SignalSnapshot -> Strategy
    pit_execution -> Execution

A strategy receives the snapshot, not the reader. Holding the reader, it could
write its own ``history(...).tail(20)`` and get twenty observations spanning
twenty-six sessions, which is the one mistake the signals layer exists to make
impossible. And the execution reader never leaves that layer, so a strategy
never holds an object able to show it its own fill price.

Two conventions this module is the only place to state.

**Bars come from the checked series.** ``clean/checked_bars/`` is what the
cross-check produced, so a strategy consumes prices that a second source
confirmed, or that carry ``SINGLE_SOURCE`` because no second source holds the
session. ``clean/bars/`` stays what it is - the normalizer's output for one
source - and no strategy reads it.

**A contested value is not served, field by field.** The reader drops a session
from the series of a field listed in that row's ``conflicting_fields``, not from
every field because one of them is contested: two providers routinely agree on a
close to the cent and differ on the low of the same session, and withholding the
close would hide a good number behind a bad one. What is dropped leaves a
shorter history and, when it is the value a decision is owed, a ``MISSING``
status - a hole, loudly, rather than a price nobody stands behind or a stale one
quietly carried over.

**Staleness is counted on the reference calendar**, the one the engine advances
time on, not on each instrument's own venue calendar. Counted at its own venue,
a US close read on a day New York was closed would look perfectly fresh, and a
``LEVEL`` instrument has no venue calendar at all. One calendar for the whole
decision makes the ages of a European ETF, a US index and an ECB rate
comparable, which is what a strategy actually needs to decide.
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import Enum
from typing import Final, cast
from zoneinfo import ZoneInfo

import pandas as pd

from quant_backtester.data.calendars import (
    MAX_CLOSED_DAYS,
    CalendarRegistry,
    Session,
    TradingCalendar,
)
from quant_backtester.data.instruments import (
    DataType,
    Instrument,
    InstrumentRegistry,
    VintagePolicy,
)
from quant_backtester.data.repository import MarketDataRepository, StoreState
from quant_backtester.data.schemas import (
    AVAILABILITY_COLUMN,
    ActionType,
    BarField,
)


class ObservationStatus(Enum):
    """Why a value is what it is, so three different cases stop being one NaN."""

    OK = "OK"
    """Observed on the most recent session available at ``as_of``."""

    STALE = "STALE"
    """Observed, but on an earlier session - the venue was closed since."""

    NOT_LISTED = "NOT_LISTED"
    """The instrument did not exist yet, or no longer exists. Normal; the
    strategy must drop it from its universe rather than treat it as missing."""

    MISSING = "MISSING"
    """The instrument existed and the session took place, but no row is stored.
    This is a data hole and should be loud."""


VALUES_COLUMNS: Final[tuple[str, ...]] = (
    "value",
    "observation_date",
    "available_at_utc",
    "age_sessions",
    "status",
)
"""Columns of :meth:`PointInTimeReader.values`, in order."""

_VALUES_DTYPES: Final[dict[str, str]] = {
    "value": "float64",
    "observation_date": "object",
    "available_at_utc": "datetime64[us, UTC]",
    "age_sessions": "Int64",
    "status": "object",
}
"""Dtype of each column. ``age_sessions`` is nullable: no age is not age zero."""


@dataclass(frozen=True, slots=True)
class _Observation:
    """One instrument's latest knowable value, as one row of ``values``."""

    value: float
    observation_date: date | None
    available_at_utc: pd.Timestamp | None
    age_sessions: int | None
    status: ObservationStatus


@dataclass(frozen=True, slots=True)
class Observation:
    """One instrument's latest knowable value at an instant, and why it is what it is.

    The typed twin of one row of :meth:`PointInTimeReader.values`, for the
    layers that act on one value at a time - valuing a position, filling an
    order - and must never be handed a bare float. A number without its status
    is how a close from last Thursday ends up valuing a book on Monday without
    anything saying so.

    Attributes
    ----------
    instrument_id : str
        Instrument read.
    value : float | None
        The number, or ``None`` for ``NOT_LISTED`` and ``MISSING`` - which have
        none to give, and are not the same thing as zero.
    status : ObservationStatus
        Why the value is what it is.
    observation_date : date | None
        The session or observation date the value describes.
    available_at : datetime | None
        When it became knowable, in UTC. Never after the instant it was read at.
    age_sessions : int | None
        Sessions of the reference calendar between the observation and the
        instant it was read at.
    """

    instrument_id: str
    value: float | None
    status: ObservationStatus
    observation_date: date | None = None
    available_at: datetime | None = None
    age_sessions: int | None = None

    @property
    def is_current(self) -> bool:
        """Return whether this is a value of the session being read, and not an older one."""
        return self.status is ObservationStatus.OK and self.value is not None


def _require_aware(instant: datetime, name: str) -> datetime:
    """Return ``instant`` in UTC, rejecting a naive datetime.

    Parameters
    ----------
    instant : datetime
        Value to check.
    name : str
        Name quoted in the error message.

    Returns
    -------
    datetime
        The same instant, expressed in UTC.

    Raises
    ------
    ValueError
        If ``instant`` carries no usable timezone.
    """
    if instant.tzinfo is None or instant.tzinfo.utcoffset(instant) is None:
        raise ValueError(f"{name} must be timezone-aware, got {instant!r}")
    return instant.astimezone(UTC)


def _as_instant(value: datetime, context: str) -> pd.Timestamp:
    """Return a stored availability stamp as a timestamp, refusing a missing one.

    Parameters
    ----------
    value : datetime
        Cell read from an availability column.
    context : str
        Quoted in the error message.

    Returns
    -------
    pd.Timestamp
        The instant, timezone-aware.

    Raises
    ------
    ValueError
        If the cell is ``NaT``. Both schemas declare availability non-nullable,
        so a missing one is a corrupt file, not a case to carry along.
    """
    timestamp = pd.Timestamp(value)
    if not isinstance(timestamp, pd.Timestamp):
        raise ValueError(f"{context}: availability timestamp is missing")
    return timestamp


def _is_contested(conflicting_fields: object, field: BarField) -> bool:
    """Return whether the cross-check found this field's value contested.

    Parameters
    ----------
    conflicting_fields : object
        The row's ``conflicting_fields`` cell: field names, sorted and
        comma-separated, empty when the sources agreed on everything they could
        compare.
    field : BarField
        Field about to be served.

    Returns
    -------
    bool
        ``True`` when this field is one two sources disagreed on beyond the
        declared tolerance. A field they could not compare is not contested: it
        is unconfirmed, which is the ordinary state of every single-source
        series in the registry.
    """
    listed = str(conflicting_fields)
    return bool(listed) and field.value in listed.split(",")


def _contested(conflicting_fields: pd.Series, field: BarField) -> pd.Series:
    """Return, row by row, whether the cross-check found this field contested.

    The vectorised form of :func:`_is_contested`, and held to it by a test that
    compares the two cell by cell: ``field`` must be one of the comma-separated
    names of the cell, whole - ``close`` is not contested by ``closed``, nor by
    ``low, close`` written with a space. A missing cell contests nothing.
    """
    pattern = rf"(?:^|,){re.escape(field.value)}(?:,|$)"
    return conflicting_fields.astype("string").str.contains(pattern, regex=True, na=False)


def _field_availability(session: Session, field: BarField) -> datetime:
    """Return the instant at which ``field`` of ``session`` becomes knowable.

    Parameters
    ----------
    session : Session
        Venue session.
    field : BarField
        Field read.

    Returns
    -------
    datetime
        The session's opening auction for ``OPEN``, its closing auction for
        every other field - the same rule
        :func:`~quant_backtester.data.normalizer.bar_availability` stamps into
        the stored rows.
    """
    if AVAILABILITY_COLUMN[field] == "open_available_at_utc":
        return session.open_utc
    return session.close_utc


def _latest_session_opened_at(calendar: TradingCalendar, instant: datetime) -> Session:
    """Return the most recent session of ``calendar`` already opened at ``instant``.

    Parameters
    ----------
    calendar : TradingCalendar
        Calendar to scan.
    instant : datetime
        Timezone-aware instant.

    Returns
    -------
    Session
        Latest session whose ``open_utc`` is at or before ``instant``.

    Raises
    ------
    LookupError
        If no such session lies within ``MAX_CLOSED_DAYS`` days, or if the scan
        reaches the start of the calendar's coverage.
    CalendarCoverageError
        If ``instant`` falls after the covered period. Answering with the last
        covered session would silently date a decision to the wrong day.

    Notes
    -----
    The session that has *opened* - not the one that has closed - is what dates
    a decision. At 09:01 on day ``t+1`` the reference session is ``t+1``, so a
    close carried over from ``t`` reports one session of age rather than none.
    """
    zone = ZoneInfo(calendar.timezone)
    day = instant.astimezone(zone).date()
    for _ in range(MAX_CLOSED_DAYS + 1):
        if day < calendar.covered_from:
            break
        session = calendar.session(day)
        if session is not None and session.open_utc <= instant:
            return session
        day -= timedelta(days=1)
    raise LookupError(
        f"{calendar.calendar_id}: no session opened within {MAX_CLOSED_DAYS} days "
        f"before {instant.isoformat()}"
    )


def _empty_values_frame() -> pd.DataFrame:
    """Return the frame :meth:`PointInTimeReader.values` returns for no instrument."""
    index = pd.Index([], dtype="object", name="instrument_id")
    return pd.DataFrame(
        {name: pd.Series([], index=index, dtype=dtype) for name, dtype in _VALUES_DTYPES.items()},
        columns=list(VALUES_COLUMNS),
    )


@dataclass(frozen=True, slots=True)
class _PreparedSeries:
    """One field's rows with a value, sorted, as every instant starts from them."""

    dates: list[date]
    rows: pd.DataFrame


FileVersion = tuple[int, int, int, int] | None
"""A clean file's version, as :meth:`MarketDataRepository.version` gives it."""

PreparedCache = dict[tuple[str, str], tuple[FileVersion, _PreparedSeries]]
"""The prepared series of each instrument and field, with the file version it was made from.

One entry per series, not per version: a newer version replaces the older one,
so a reader kept for a long session holds one copy of each series however many
promotions it lives through (audit N09).
"""

ActionsCache = dict[str, tuple[FileVersion, pd.DataFrame]]
"""An instrument's corporate actions, sorted, with the version of the action table."""


def _rows(stored: pd.DataFrame, dates: str, values: str, available: str) -> pd.DataFrame:
    """Return the three columns every read works on, taken from a stored frame.

    The instants stay a datetime array end to end: turned into Python objects
    and inferred back, they cost more than everything else here.
    """
    return pd.DataFrame(
        {
            "observation_date": stored[dates].to_numpy(),
            "value": stored[values].to_numpy(dtype="float64"),
            "available_at_utc": stored[available].array,
        }
    )


class PointInTimeReader:
    """Market data as it was knowable at one instant.

    Parameters
    ----------
    repository : MarketDataRepository
        Storage to read from.
    instruments : InstrumentRegistry
        Registry, for listing dates and data types.
    calendars : CalendarRegistry
        Calendars, to express staleness in sessions.
    as_of : datetime
        Timezone-aware decision instant. Every value returned satisfies
        ``available_at <= as_of``.
    reference_calendar_id : str
        Calendar the engine advances time on. It dates the decision and is the
        only calendar ``age_sessions`` is counted on, so the ages of
        instruments from different venues are comparable.

    Raises
    ------
    ValueError
        If ``as_of`` is naive. A naive decision instant is the single most
        expensive bug this layer can have.
    KeyError
        If ``reference_calendar_id`` is not registered.
    """

    def __init__(
        self,
        repository: MarketDataRepository,
        instruments: InstrumentRegistry,
        calendars: CalendarRegistry,
        as_of: datetime,
        reference_calendar_id: str,
        prepared: PreparedCache | None = None,
        actions: ActionsCache | None = None,
    ) -> None:
        self._repository = repository
        self._instruments = instruments
        self._calendars = calendars
        self._as_of = _require_aware(as_of, "as_of")
        self._prepared: PreparedCache = {} if prepared is None else prepared
        self._actions: ActionsCache = {} if actions is None else actions
        # Resolve now: an unknown calendar must fail when the reader is built,
        # not on the first read that happens to need an age.
        self._reference_calendar = calendars.get(reference_calendar_id)

    @property
    def as_of(self) -> datetime:
        """Return the decision instant, in UTC."""
        return self._as_of

    @property
    def reference_calendar_id(self) -> str:
        """Return the calendar staleness is counted on."""
        return self._reference_calendar.calendar_id

    def history(
        self,
        instrument_id: str,
        field: BarField = BarField.CLOSE,
        start: date | None = None,
        end: date | None = None,
    ) -> pd.Series:
        """Return one field's history, truncated at ``as_of``.

        Parameters
        ----------
        instrument_id : str
            Instrument to read.
        field : BarField
            Field to return. Ignored for ``LEVEL`` instruments.
        start, end : date | None
            Inclusive bounds; ``None`` means unbounded.

        Returns
        -------
        pd.Series
            Indexed by session date, named after the field. Raw, unadjusted
            values - see :meth:`adjusted_history` for an adjusted series.

        Raises
        ------
        KeyError
            If the instrument is not registered.

        Notes
        -----
        Exercice 8.2 (moyen). Le filtre porte sur la colonne de disponibilite du
        champ demande, donnee par ``AVAILABILITY_COLUMN`` - pas sur la ligne. Une
        seance dont le close n'est pas encore disponible **disparait** de la
        serie ; elle n'y figure pas avec un ``NaN``. C'est voulu : un ``NaN`` en
        bout de serie se propage silencieusement dans la premiere moyenne mobile
        venue, alors qu'une serie plus courte est visible immediatement.

        Consequence a verifier : appelee a 09:01 le jour t+1, ``field=OPEN``
        renvoie une serie allant jusqu'a t+1, et ``field=CLOSE`` une serie
        s'arretant a t.

        Le meme argument vaut pour les trous : une valeur stockee vide et une
        valeur que deux sources contestent sont absentes de la serie plutot que
        presentes en ``NaN``. Le filtre porte sur le champ demande, pas sur la
        seance : un desaccord sur le ``low`` ne retire pas le ``close``.

        L'index s'appelle ``observation_date`` pour les deux types d'instrument,
        comme la colonne de meme nom dans :meth:`values`.
        """
        instrument = self._instruments.get(instrument_id)
        rows = self._available_rows(instrument, field, start=start, end=end)
        name = field.value if instrument.data_type is DataType.BAR else "value"
        return pd.Series(
            rows["value"].to_numpy(dtype="float64"),
            index=pd.Index(list(rows["observation_date"]), dtype="object", name="observation_date"),
            name=name,
        )

    def values(
        self, instrument_ids: Sequence[str], field: BarField = BarField.CLOSE
    ) -> pd.DataFrame:
        """Return the latest knowable value of several instruments.

        Parameters
        ----------
        instrument_ids : Sequence[str]
            Instruments to read.
        field : BarField
            Field to return for ``BAR`` instruments.

        Returns
        -------
        pd.DataFrame
            Indexed by ``instrument_id``, with columns ``value``,
            ``observation_date``, ``available_at_utc``, ``age_sessions`` and
            ``status``. ``age_sessions`` counts the sessions of the reference
            calendar elapsed since the observation: ``0`` when the value belongs
            to the session dating the decision. It is ``<NA>``, and ``value`` is
            ``NaN``, for ``NOT_LISTED`` and ``MISSING``.

        Raises
        ------
        ValueError
            If an instrument appears twice: the caller would silently read one
            row for two universe members.
        KeyError
            If an instrument is not registered.

        Notes
        -----
        Exercice 8.3 (moyen). C'est la methode que toutes les strategies
        appelleront ; elle doit rendre la fraicheur **visible**.

        Un exemple concret : le soir du 27 novembre, NY a ferme a 13:00 ET et
        Paris etait ouvert normalement. Si NY avait ete ferie, le close US
        renvoye daterait de la veille - la strategie doit pouvoir le voir dans
        ``age_sessions`` et decider, plutot que de croire regarder une donnee du
        jour.

        Distingue bien ``NOT_LISTED`` (l'instrument n'existait pas, on l'exclut
        de l'univers) de ``MISSING`` (trou de donnees, il faut crier). Les faire
        remonter tous deux en ``NaN`` est exactement la confusion qui produit des
        courbes de performance inexplicables.

        La regle exacte, dans l'ordre :

        1. l'instrument n'est pas cote a la date de la seance de reference ->
           ``NOT_LISTED`` ;
        2. sinon, pour un ``BAR``, on demande a **son** calendrier la derniere
           seance dont le champ serait disponible a ``as_of`` : si elle existe
           et qu'aucune ligne ne la porte, c'est un trou -> ``MISSING``, valeur
           ``NaN`` (servir la valeur precedente masquerait le trou) ;
        3. sinon la derniere valeur disponible, ``OK`` si son age vaut zero,
           ``STALE`` sinon.

        Un ``LEVEL`` n'a pas de calendrier : on ne peut pas prouver qu'une
        publication manque, donc il n'est ``MISSING`` que si rien du tout n'est
        disponible alors qu'il est cote.
        """
        requested = list(instrument_ids)
        duplicates = sorted({name for name in requested if requested.count(name) > 1})
        if duplicates:
            raise ValueError(f"values() got duplicate instrument ids: {', '.join(duplicates)}")
        if not requested:
            return _empty_values_frame()
        reference = _latest_session_opened_at(self._reference_calendar, self._as_of)
        observations = [self._observe(name, field, reference) for name in requested]
        index = pd.Index(requested, dtype="object", name="instrument_id")
        columns = {
            "value": [observation.value for observation in observations],
            "observation_date": [observation.observation_date for observation in observations],
            "available_at_utc": [observation.available_at_utc for observation in observations],
            "age_sessions": [observation.age_sessions for observation in observations],
            "status": [observation.status for observation in observations],
        }
        return pd.DataFrame(
            {
                name: pd.Series(values, index=index, dtype=_VALUES_DTYPES[name])
                for name, values in columns.items()
            },
            columns=list(VALUES_COLUMNS),
        )

    def observations(
        self, instrument_ids: Sequence[str], field: BarField = BarField.CLOSE
    ) -> dict[str, Observation]:
        """Return the latest knowable value of several instruments, one object each.

        Parameters
        ----------
        instrument_ids : Sequence[str]
            Instruments to read.
        field : BarField
            Field to return for ``BAR`` instruments.

        Returns
        -------
        dict[str, Observation]
            Keyed by instrument, in the order asked. The same rule as
            :meth:`values`, applied the same way: this is that frame, one row
            at a time, for a caller that acts on each value separately.

        Raises
        ------
        ValueError
            If an instrument appears twice.
        KeyError
            If an instrument is not registered.
        """
        requested = list(instrument_ids)
        duplicates = sorted({name for name in requested if requested.count(name) > 1})
        if duplicates:
            raise ValueError(
                f"observations() got duplicate instrument ids: {', '.join(duplicates)}"
            )
        if not requested:
            return {}
        reference = _latest_session_opened_at(self._reference_calendar, self._as_of)
        observed: dict[str, Observation] = {}
        for name in requested:
            row = self._observe(name, field, reference)
            observed[name] = Observation(
                instrument_id=name,
                value=None if row.value != row.value else row.value,
                status=row.status,
                observation_date=row.observation_date,
                available_at=(
                    None if row.available_at_utc is None else row.available_at_utc.to_pydatetime()
                ),
                age_sessions=row.age_sessions,
            )
        return observed

    def corporate_actions(self, instrument_id: str) -> pd.DataFrame:
        """Return the corporate actions knowable at ``as_of``.

        Parameters
        ----------
        instrument_id : str
            Instrument to read.

        Returns
        -------
        pd.DataFrame
            Actions with ``available_at_utc <= as_of``, ordered by ex-date then
            action type, so two actions sharing an ex-date keep a stable order.

        Notes
        -----
        Exercice 8.4 (facile). Methode du reader, jamais fonction libre : c'est
        le seul garde-fou qui empeche un split posterieur a la date de decision
        de retro-ajuster une serie.
        """
        version = self._repository.version("corporate_actions")
        kept = self._actions.get(instrument_id)
        if kept is not None and kept[0] == version:
            prepared = kept[1]
        else:
            # Read and sorted once per version of the table, as the series
            # are; filtering a sorted frame keeps its order.
            prepared = self._repository.load_corporate_actions(instrument_id)
            prepared = prepared.sort_values(["ex_date", "action_type"], kind="stable")
            prepared = prepared.reset_index(drop=True)
            self._actions[instrument_id] = (version, prepared)
        frame = prepared.loc[prepared["available_at_utc"] <= self._as_of]
        return frame.reset_index(drop=True)

    def adjusted_history(
        self, instrument_id: str, start: date | None = None, end: date | None = None
    ) -> pd.Series:
        """Return an adjusted price series, using only known corporate actions.

        Parameters
        ----------
        instrument_id : str
            Instrument to read.
        start, end : date | None
            Inclusive bounds.

        Returns
        -------
        pd.Series
            Adjusted closes, indexed by session date. The level is arbitrary;
            only the ratios are meaningful. A price series with the actions
            taken out, not a reinvested wealth - see
            :attr:`quant_backtester.signals.types.PriceBasis.ADJUSTED` for the
            difference on an ex-date. Named ``total_return_history`` until
            2026-09-26.

        Raises
        ------
        ValueError
            If the instrument is not a ``BAR``, if a split ratio is not strictly
            positive, or if a dividend is not smaller than the close preceding
            its ex-date - an adjustment factor at or below zero would flip the
            sign of every earlier price.

        Notes
        -----
        Exercice 8.5 (difficile, et c'est l'exercice qui compte le plus). Ce que
        ``adj_close`` faisait mal, fait correctement :

        1. lis les closes bruts et les actions via :meth:`corporate_actions` -
           donc filtrees a ``as_of`` ;
        2. construis un facteur cumule retrograde depuis la derniere seance ;
        3. un split de ratio r divise les prix anterieurs a l'ex-date par r ;
        4. un dividende d sur un close c ajoute un facteur ``(1 - d / c)`` aux
           prix anterieurs, avec ``c`` le close precedant l'ex-date ;
        5. un ``SPIN_OFF`` s'ajuste comme un split et un ``SPECIAL_DIVIDEND``
           comme un dividende : le prix bouge pareil, seul le sens de
           l'evenement differe - et c'est lui que les couches au-dessus lisent.

        Une action est disponible a l'**ouverture** de son ex-date, en meme temps
        que le premier prix qu'elle affecte : le reader d'execution de l'ex-date
        voit l'open deja ajuste *et* l'action, celui de la veille au soir ne voit
        ni l'un ni l'autre, et aucun des deux n'affiche de faux saut.

        Le test a ecrire en meme temps : une serie plate a 100 avec un split 4:1,
        ajustee, doit etre parfaitement plate a 25 avant l'ex-date - aucun saut
        de rendement. Puis rappelle la methode avec un ``as_of`` anterieur au
        split : la serie ne doit contenir aucune trace de l'ajustement.

        ``start`` et ``end`` decoupent **apres** l'ajustement : les facteurs se
        cumulent depuis la derniere seance connue, donc une fenetre ne doit pas
        changer les rapports qu'elle contient.
        """
        instrument = self._instruments.get(instrument_id)
        if instrument.data_type is not DataType.BAR:
            raise ValueError(
                f"adjusted_history is for BAR instruments; "
                f"{instrument_id} is a {instrument.data_type.value}"
            )
        closes = self.history(instrument_id, BarField.CLOSE)
        sessions: list[date] = list(closes.index)
        prices: list[float] = [float(value) for value in closes]
        factors = [1.0] * len(sessions)
        actions = self.corporate_actions(instrument_id)
        for action_type, ex_date, action_value in zip(
            actions["action_type"], actions["ex_date"], actions["value"], strict=True
        ):
            # The series is sorted, so the sessions strictly before the ex-date
            # are exactly its first `prior` entries.
            prior = sum(1 for session in sessions if session < ex_date)
            if prior == 0:
                continue
            factor = self._adjustment_factor(
                instrument_id,
                ActionType(action_type),
                float(action_value),
                prices[prior - 1],
            )
            for position in range(prior):
                factors[position] *= factor
        adjusted = pd.Series(
            [price * factor for price, factor in zip(prices, factors, strict=True)],
            index=closes.index,
            name="adjusted_close",
            dtype="float64",
        )
        keep = [
            (start is None or session >= start) and (end is None or session <= end)
            for session in sessions
        ]
        return adjusted.loc[keep]

    @staticmethod
    def _adjustment_factor(
        instrument_id: str, action_type: ActionType, value: float, previous_close: float
    ) -> float:
        """Return the factor an action applies to every price before its ex-date.

        Parameters
        ----------
        instrument_id : str
            Instrument, quoted in error messages.
        action_type : ActionType
            Kind of action.
        value : float
            Split ratio, or dividend per share in the instrument currency.
        previous_close : float
            Raw close of the last session preceding the ex-date.

        Returns
        -------
        float
            ``1 / ratio`` for a split, and for a spin-off, whose price
            adjustment is the same although no share was multiplied;
            ``1 - amount / close`` for a dividend, ordinary or special.

        Raises
        ------
        ValueError
            If the factor would be zero or negative.
        """
        if action_type in (ActionType.SPLIT, ActionType.SPIN_OFF):
            if value <= 0.0:
                raise ValueError(
                    f"{instrument_id}: {action_type.value.lower().replace('_', '-')} factor "
                    f"{value} is not strictly positive"
                )
            return 1.0 / value
        if previous_close <= 0.0:
            raise ValueError(
                f"{instrument_id}: cannot adjust a dividend of {value} on a close of "
                f"{previous_close}"
            )
        factor = 1.0 - value / previous_close
        if factor <= 0.0:
            raise ValueError(
                f"{instrument_id}: dividend {value} is not smaller than the preceding close "
                f"{previous_close}"
            )
        return factor

    def _available_rows(
        self,
        instrument: Instrument,
        field: BarField,
        start: date | None = None,
        end: date | None = None,
    ) -> pd.DataFrame:
        """Return what is knowable at ``as_of``, as ``observation_date``/``value``.

        Parameters
        ----------
        instrument : Instrument
            Instrument to read.
        field : BarField
            Field read; ignored for a ``LEVEL``.
        start, end : date | None
            Inclusive bounds on the observation date.

        Returns
        -------
        pd.DataFrame
            Columns ``observation_date``, ``value`` and ``available_at_utc``,
            sorted by observation date. Rows whose value is absent are dropped,
            as are sessions where this very field is contested: neither is a
            number to hand a strategy. A session contested on another field is
            kept, since nothing is wrong with the value asked for.
        """
        if instrument.vintage_policy is VintagePolicy.AS_OF_DECISION:
            stored = self._vintage_rows(instrument, start=start, end=end)
            rows = _rows(stored, "observation_date", "value", "available_at_utc")
            rows = rows.loc[rows["available_at_utc"] <= self._as_of]
            rows = rows.loc[rows["value"].notna()]
            return rows.sort_values("observation_date", kind="stable").reset_index(drop=True)
        prepared = self._prepared_series(instrument, field)
        low = 0 if start is None else bisect_left(prepared.dates, start)
        high = len(prepared.dates) if end is None else bisect_right(prepared.dates, end)
        rows = prepared.rows.iloc[low:high]
        rows = rows.loc[rows["available_at_utc"] <= self._as_of]
        return rows.reset_index(drop=True)

    def _prepared_series(self, instrument: Instrument, field: BarField) -> _PreparedSeries:
        """Return a series cleaned of what no instant may see, prepared once per file version.

        Parameters
        ----------
        instrument : Instrument
            A ``BAR`` or a ``LEVEL`` read as one series.
        field : BarField
            Field read; ignored for a ``LEVEL``.

        Returns
        -------
        _PreparedSeries
            Every stored row with a value, less the sessions where this very
            field is contested, sorted by observation date. What is left to do
            at an instant - bounds on the dates, and the rows not yet
            available - is a slice and a comparison.

        Notes
        -----
        None of that preparation depends on the instant, and doing it on every
        read was half of every backtest: the store was copied, a string column
        searched and a frame built and sorted four thousand times a run over
        the same file (profiled 2026-09-26, lot 6). It is cached on the
        reader, keyed on the file's version: a promotion writes a new file,
        whose version is new, so nothing stale is ever served. Filtering and
        sorting commute - both keep order and a stable sort keeps ties - so a
        read returns exactly the frame it returned before.
        """
        table = "checked_bars" if instrument.data_type is DataType.BAR else "levels"
        key = (instrument.id, field.value)
        version = self._repository.version(table, instrument.id)
        kept = self._prepared.get(key)
        if kept is not None and kept[0] == version:
            return kept[1]
        if instrument.data_type is DataType.BAR:
            stored = self._repository.load_checked_bars(instrument.id)
            stored = stored.loc[~_contested(cast(pd.Series, stored["conflicting_fields"]), field)]
            rows = _rows(stored, "session_date", field.value, AVAILABILITY_COLUMN[field])
        else:
            stored = self._repository.load_levels(instrument.id)
            rows = _rows(stored, "observation_date", "value", "available_at_utc")
        rows = rows.loc[rows["value"].notna()]
        rows = rows.sort_values("observation_date", kind="stable").reset_index(drop=True)
        prepared = _PreparedSeries(dates=list(rows["observation_date"]), rows=rows)
        self._prepared[key] = (version, prepared)
        return prepared

    def _vintage_rows(
        self, instrument: Instrument, start: date | None = None, end: date | None = None
    ) -> pd.DataFrame:
        """Return a restated series as it stood at this decision instant.

        Parameters
        ----------
        instrument : Instrument
            A published series read as of each decision.
        start, end : date | None
            Inclusive bounds on the observation date.

        Returns
        -------
        pd.DataFrame
            One row per observation date - the value of the latest vintage this
            instant could have seen, and the instant that value became public.

        Notes
        -----
        This is the whole point of storing an archive rather than a series. US
        GDP for the first quarter of 2019 is 21 098.827 to a reader in January
        2020 and 21 115.309 to one in June 2021; a backtest deciding in 2020 on
        the second number is deciding on information that did not exist. The
        row kept for each observation is therefore the one from the most recent
        vintage available at ``as_of`` - and the availability filter above then
        drops anything whose release had not happened either, so a revision
        published this morning is invisible to a decision taken last night.

        A later vintage that *withdrew* an observation does not resurrect the
        earlier value: the question asked is "what did the series say that
        day", and the answer for each observation is its latest known telling.
        The latest vintage per observation is taken first, withdrawals
        included, and an observation whose latest telling is a withdrawal is
        then left out. Dropping the withdrawals first - which is what a
        normalizer that threw the ``.`` cells away amounted to - served the
        earlier value (audit A09).
        """
        stored = self._repository.load_vintages(instrument.id)
        if stored.empty:
            return stored.rename(columns={})
        knowable = stored.loc[stored["available_at_utc"] <= self._as_of]
        if start is not None:
            knowable = knowable.loc[knowable["observation_date"] >= start]
        if end is not None:
            knowable = knowable.loc[knowable["observation_date"] <= end]
        if knowable.empty:
            return knowable
        latest = knowable.sort_values(
            ["observation_date", "vintage_date"], kind="stable"
        ).drop_duplicates("observation_date", keep="last")
        latest = latest.loc[~latest["withdrawn"].astype(bool)]
        return latest.reset_index(drop=True)

    def _observe(self, instrument_id: str, field: BarField, reference: Session) -> _Observation:
        """Return one row of :meth:`values`.

        Parameters
        ----------
        instrument_id : str
            Instrument to read.
        field : BarField
            Field read.
        reference : Session
            Session of the reference calendar dating the decision.

        Returns
        -------
        _Observation
            Latest knowable value and why it is what it is.
        """
        instrument = self._instruments.get(instrument_id)
        if not instrument.is_listed(reference.session_date):
            return _Observation(float("nan"), None, None, None, ObservationStatus.NOT_LISTED)
        rows = self._available_rows(instrument, field)
        expected = self._expected_session(instrument, field)
        if rows.empty:
            # A BAR with no session due yet - listed, but its first close has
            # not been published - is not part of the universe rather than a
            # hole. Anything else owed and absent is a hole.
            no_session_due = instrument.data_type is DataType.BAR and expected is None
            status = ObservationStatus.NOT_LISTED if no_session_due else ObservationStatus.MISSING
            return _Observation(float("nan"), None, None, None, status)
        last = rows.iloc[-1]
        observation_date: date = last["observation_date"]
        if expected is not None and observation_date < expected.session_date:
            # The venue held a session whose field is due, and we have nothing
            # for it. Serving the previous value here is how a hole disappears.
            return _Observation(float("nan"), None, None, None, ObservationStatus.MISSING)
        age = self._age_in_sessions(observation_date, reference.session_date)
        return _Observation(
            value=float(last["value"]),
            observation_date=observation_date,
            available_at_utc=_as_instant(
                last["available_at_utc"], f"{instrument_id} on {observation_date}"
            ),
            age_sessions=age,
            status=ObservationStatus.OK if age == 0 else ObservationStatus.STALE,
        )

    def _expected_session(self, instrument: Instrument, field: BarField) -> Session | None:
        """Return the last session whose ``field`` is due at ``as_of``, if any.

        Parameters
        ----------
        instrument : Instrument
            Instrument to read.
        field : BarField
            Field read.

        Returns
        -------
        Session | None
            Latest session of the instrument's own calendar, within its listing
            dates, whose ``field`` would already be published at ``as_of``.
            ``None`` for a ``LEVEL`` - it has no calendar, so no publication can
            be proven missing - and ``None`` before the instrument's first
            session.
        """
        if instrument.data_type is not DataType.BAR or instrument.calendar_id is None:
            return None
        calendar = self._calendars.get(instrument.calendar_id)
        zone = ZoneInfo(calendar.timezone)
        day = self._as_of.astimezone(zone).date()
        for _ in range(MAX_CLOSED_DAYS + 1):
            if day < calendar.covered_from:
                return None
            if not instrument.is_listed(day):
                return None
            session = calendar.session(day)
            if session is not None and _field_availability(session, field) <= self._as_of:
                return session
            day -= timedelta(days=1)
        return None

    def _age_in_sessions(self, observation_date: date, reference_date: date) -> int:
        """Return the reference sessions elapsed since ``observation_date``.

        Parameters
        ----------
        observation_date : date
            Date the value describes.
        reference_date : date
            Session of the reference calendar dating the decision.

        Returns
        -------
        int
            ``0`` when the observation is as recent as the reference session -
            including the case where its own venue traded on a day the reference
            venue was closed, which would otherwise count as a negative age.
        """
        if observation_date >= reference_date:
            return 0
        return self._reference_calendar.sessions_between(observation_date, reference_date)


class MarketDataReader:
    """Entry point for reading market data.

    Parameters
    ----------
    repository : MarketDataRepository
        Storage to read from.
    instruments : InstrumentRegistry
        Instrument registry.
    calendars : CalendarRegistry
        Calendar registry.
    reference_calendar_id : str
        Calendar the engine advances time on, handed to every
        :class:`PointInTimeReader` built here. It has no default: which venue
        dates a decision is a research parameter, and a wrong one silently makes
        stale data look fresh.

    Raises
    ------
    KeyError
        If ``reference_calendar_id`` is not registered.
    """

    def __init__(
        self,
        repository: MarketDataRepository,
        instruments: InstrumentRegistry,
        calendars: CalendarRegistry,
        reference_calendar_id: str,
    ) -> None:
        self._repository = repository
        self._instruments = instruments
        self._calendars = calendars
        # Fail here rather than at the first `at()` of a long run.
        self._reference_calendar = calendars.get(reference_calendar_id)
        self._prepared: PreparedCache = {}
        self._actions: ActionsCache = {}

    def at(self, as_of: datetime) -> PointInTimeReader:
        """Return a reader frozen at one instant.

        Parameters
        ----------
        as_of : datetime
            Timezone-aware decision instant.

        Returns
        -------
        PointInTimeReader
            Reader that cannot see past ``as_of``.

        Notes
        -----
        Exercice 8.6 (facile). C'est la seule methode que le moteur de backtest
        doit utiliser.
        """
        return PointInTimeReader(
            self._repository,
            self._instruments,
            self._calendars,
            as_of,
            self._reference_calendar.calendar_id,
            prepared=self._prepared,
            actions=self._actions,
        )

    def pinned(self) -> AbstractContextManager[StoreState]:
        """Hold the store for reading for the block, and return what it holds.

        Returns
        -------
        AbstractContextManager[StoreState]
            Entered, it holds the store against every writer and yields the
            digest of every file a result can depend on. A run does its
            reading inside it, so that nothing it read changes under it.
        """
        return self._repository.reading()

    def latest(self) -> PointInTimeReader:
        """Return a reader frozen at the current wall-clock instant.

        Returns
        -------
        PointInTimeReader
            Reader bound to ``datetime.now(UTC)``.

        Notes
        -----
        Exercice 8.7 (trivial, mais lis l'avertissement).

        **Pour le live et l'exploration uniquement.** Cette methode lit l'horloge
        murale, donc elle rend un resultat non reproductible et n'a aucun sens
        dans un backtest. Elle existe ici, sur le reader non borne, precisement
        pour qu'elle n'existe pas sur l'objet remis aux strategies.
        """
        return self.at(datetime.now(UTC))

    @property
    def instruments(self) -> InstrumentRegistry:
        """Return the instrument registry."""
        return self._instruments

    @property
    def reference_calendar_id(self) -> str:
        """Return the calendar staleness is counted on."""
        return self._reference_calendar.calendar_id

    @property
    def calendars(self) -> CalendarRegistry:
        """Return the calendars this reader dates observations on."""
        return self._calendars
