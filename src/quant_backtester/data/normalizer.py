"""Normalisation: provider frames -> canonical schemas.

This is the only layer that knows a provider's column names, its date handling
and its sign conventions. It is also where availability is stamped: a BAR gets
its two timestamps from the venue calendar, a LEVEL gets its single timestamp
from the instrument's publication rule.

Normalisation is a pure function of (raw frame, instrument, calendar). It must
never look at the clock, the filesystem or the network - that is what makes
``clean/`` rebuildable from ``raw/`` and the test of exercise 9.4 possible.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

import pandas as pd

from quant_backtester.data.calendars import TradingCalendar
from quant_backtester.data.instruments import Instrument
from quant_backtester.data.sources.base import RawDownload


@dataclass(frozen=True, slots=True)
class NormalizedData:
    """Canonical frames produced from one raw download.

    Attributes
    ----------
    bars : pd.DataFrame | None
        Rows matching :data:`~quant_backtester.data.schemas.BARS_SCHEMA`.
    levels : pd.DataFrame | None
        Rows matching :data:`~quant_backtester.data.schemas.LEVELS_SCHEMA`.
    corporate_actions : pd.DataFrame | None
        Rows matching
        :data:`~quant_backtester.data.schemas.CORPORATE_ACTIONS_SCHEMA`.
    """

    bars: pd.DataFrame | None = None
    levels: pd.DataFrame | None = None
    corporate_actions: pd.DataFrame | None = None


def bar_availability(session_date: date, calendar: TradingCalendar) -> tuple[datetime, datetime]:
    """Return the availability instants of a bar's open and close fields.

    Parameters
    ----------
    session_date : date
        Session the bar describes.
    calendar : TradingCalendar
        Venue calendar.

    Returns
    -------
    tuple[datetime, datetime]
        ``(open_available_at_utc, close_available_at_utc)``, both UTC-aware.

    Raises
    ------
    ValueError
        If the venue was closed on ``session_date`` - a bar on a non-session is
        a data error, not something to silently accept.

    Notes
    -----
    Exercice 5.1 (facile, mais c'est la fonction centrale du module). Elle est
    l'endroit unique ou la disponibilite par champ prend corps ; tout le reste du
    systeme en depend.
    """
    raise NotImplementedError("Exercice 5.1")


class Normalizer(Protocol):
    """Turn one provider's frames into canonical ones."""

    source_id: str

    def normalize(
        self,
        instrument: Instrument,
        download: RawDownload,
        calendar: TradingCalendar | None = None,
    ) -> NormalizedData:
        """Convert a raw download to canonical frames.

        Parameters
        ----------
        instrument : Instrument
            Instrument the download belongs to.
        download : RawDownload
            Provider response.
        calendar : TradingCalendar | None
            Required for ``BAR`` instruments, unused for ``LEVEL`` ones.

        Returns
        -------
        NormalizedData
            Canonical frames, columns and dtypes matching the schemas.
        """
        ...


class YahooNormalizer:
    """Normalise Yahoo Finance frames."""

    source_id = "YAHOO"

    def normalize(
        self,
        instrument: Instrument,
        download: RawDownload,
        calendar: TradingCalendar | None = None,
    ) -> NormalizedData:
        """Convert Yahoo bars and actions to canonical frames.

        Parameters
        ----------
        instrument : Instrument
            Instrument the download belongs to.
        download : RawDownload
            Provider response.
        calendar : TradingCalendar | None
            Venue calendar; required here.

        Returns
        -------
        NormalizedData
            Canonical bars, and corporate actions when present.

        Notes
        -----
        Exercice 5.2 (moyen). Points de vigilance :

        - ``Open/High/Low/Close/Volume`` -> minuscules ; ``Adj Close`` est
          **jete** : c'est une serie reecrite retroactivement, elle n'a aucune
          place dans le clean.
        - L'index Yahoo devient ``session_date`` ; s'il est tz-aware, convertis
          d'abord vers le fuseau de la place avant de prendre ``.date()``, sinon
          tu decales les seances d'un jour selon l'heure.
        - Une ligne dont la seance n'existe pas au calendrier doit lever, pas
          etre silencieusement gardee.
        - Recopie ``source`` et ``source_fetch_id`` sur chaque ligne : c'est la
          tracabilite d'une valeur vers le fichier brut exact qui l'a produite.
        """
        raise NotImplementedError("Exercice 5.2")


class FredNormalizer:
    """Normalise FRED frames into levels."""

    source_id = "FRED"

    def normalize(
        self,
        instrument: Instrument,
        download: RawDownload,
        calendar: TradingCalendar | None = None,
    ) -> NormalizedData:
        """Convert a FRED series to canonical levels.

        Parameters
        ----------
        instrument : Instrument
            Instrument the download belongs to.
        download : RawDownload
            Provider response.
        calendar : TradingCalendar | None
            Unused.

        Returns
        -------
        NormalizedData
            Canonical levels.

        Notes
        -----
        Exercice 5.3 (facile). Les ``"."`` deviennent des lignes absentes, pas
        des ``NaN`` : une observation manquante n'existe pas, elle ne vaut pas
        "inconnu". ``available_at_utc`` vient de
        ``instrument.publication_rule.available_at``, jamais d'un calendrier de
        bourse.
        """
        raise NotImplementedError("Exercice 5.3")


class EcbNormalizer:
    """Normalise ECB reference rates into levels."""

    source_id = "ECB"

    def normalize(
        self,
        instrument: Instrument,
        download: RawDownload,
        calendar: TradingCalendar | None = None,
    ) -> NormalizedData:
        """Convert an ECB series to canonical levels.

        Parameters
        ----------
        instrument : Instrument
            Instrument the download belongs to.
        download : RawDownload
            Provider response.
        calendar : TradingCalendar | None
            Unused.

        Returns
        -------
        NormalizedData
            Canonical levels.

        Notes
        -----
        Exercice 5.4 (facile). Attention au sens de la cotation : l'ECB publie
        EUR/USD (dollars par euro). Si une strategie attend l'inverse, c'est ici
        qu'on le fixe une fois, pas dans chaque signal.
        """
        raise NotImplementedError("Exercice 5.4")


def get_normalizer(source_id: str) -> Normalizer:
    """Return the normalizer registered for a source.

    Parameters
    ----------
    source_id : str
        Source identifier, e.g. ``"YAHOO"``.

    Returns
    -------
    Normalizer
        Matching normalizer.

    Raises
    ------
    KeyError
        If no normalizer is registered for that source.

    Notes
    -----
    Exercice 5.5 (facile).
    """
    raise NotImplementedError("Exercice 5.5")
