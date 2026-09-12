"""Read access to the clean layer, with look-ahead made unrepresentable.

A strategy never receives a :class:`MarketDataReader`. It receives a
:class:`PointInTimeReader`, built by the engine for one decision instant, whose
methods take no ``as_of`` argument at all. There is therefore no expression a
strategy can write that reads the future - the protection is structural, not a
rule someone has to remember.

The engine builds two of them per trading day, and the split falls out of
field-level availability::

    pit_decision  = reader.at(23:00 Paris, day t)     # US and EU closes of t
    pit_execution = reader.at(09:01 Paris, day t+1)   # open of t+1 only

The first goes to the strategy. The second stays inside the execution layer, so
the strategy never holds an object able to show it its own fill price.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from enum import Enum

import pandas as pd

from quant_backtester.data.calendars import CalendarRegistry
from quant_backtester.data.instruments import InstrumentRegistry
from quant_backtester.data.repository import MarketDataRepository
from quant_backtester.data.schemas import BarField


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

    Raises
    ------
    ValueError
        If ``as_of`` is naive. A naive decision instant is the single most
        expensive bug this layer can have.
    """

    def __init__(
        self,
        repository: MarketDataRepository,
        instruments: InstrumentRegistry,
        calendars: CalendarRegistry,
        as_of: datetime,
    ) -> None:
        raise NotImplementedError("Exercice 8.1")

    @property
    def as_of(self) -> datetime:
        """Return the decision instant, in UTC."""
        raise NotImplementedError("Exercice 8.1")

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
            values - see :meth:`total_return_history` for an adjusted series.

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
        """
        raise NotImplementedError("Exercice 8.2")

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
            ``status``.

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
        """
        raise NotImplementedError("Exercice 8.3")

    def corporate_actions(self, instrument_id: str) -> pd.DataFrame:
        """Return the corporate actions knowable at ``as_of``.

        Parameters
        ----------
        instrument_id : str
            Instrument to read.

        Returns
        -------
        pd.DataFrame
            Actions with ``available_at_utc <= as_of``, ordered by ex-date.

        Notes
        -----
        Exercice 8.4 (facile). Methode du reader, jamais fonction libre : c'est
        le seul garde-fou qui empeche un split posterieur a la date de decision
        de retro-ajuster une serie.
        """
        raise NotImplementedError("Exercice 8.4")

    def total_return_history(
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
            only the ratios are meaningful.

        Notes
        -----
        Exercice 8.5 (difficile, et c'est l'exercice qui compte le plus). Ce que
        ``adj_close`` faisait mal, fait correctement :

        1. lis les closes bruts et les actions via :meth:`corporate_actions` -
           donc filtrees a ``as_of`` ;
        2. construis un facteur cumule retrograde depuis la derniere seance ;
        3. un split de ratio r divise les prix anterieurs a l'ex-date par r ;
        4. un dividende d sur un close c ajoute un facteur ``(1 - d / c)`` aux
           prix anterieurs, avec ``c`` le close precedant l'ex-date.

        Le test a ecrire en meme temps : une serie plate a 100 avec un split 4:1,
        ajustee, doit etre parfaitement plate a 25 avant l'ex-date - aucun saut
        de rendement. Puis rappelle la methode avec un ``as_of`` anterieur au
        split : la serie ne doit contenir aucune trace de l'ajustement.
        """
        raise NotImplementedError("Exercice 8.5")


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
    """

    def __init__(
        self,
        repository: MarketDataRepository,
        instruments: InstrumentRegistry,
        calendars: CalendarRegistry,
    ) -> None:
        raise NotImplementedError("Exercice 8.6")

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
        raise NotImplementedError("Exercice 8.6")

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
        raise NotImplementedError("Exercice 8.7")

    @property
    def instruments(self) -> InstrumentRegistry:
        """Return the instrument registry."""
        raise NotImplementedError("Exercice 8.6")
