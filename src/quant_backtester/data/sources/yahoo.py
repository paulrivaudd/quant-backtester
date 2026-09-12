"""Yahoo Finance adapter, via ``yfinance``.

Provider quirks, all handled here and never leaked downstream:

- ``auto_adjust=True`` is the library default and must be turned **off**. With
  it on, the OHLC series itself is restated at every corporate action, so the
  value stored for a past date changes depending on the day it was downloaded.
- Splits and dividends are fetched separately and stored as their own table.
- The index is tz-aware in exchange local time for intraday, tz-naive dates for
  daily. Do not assume; check and normalise in the normalizer.
- On thinly traded European ETFs the opening print is unreliable: it is
  sometimes zero, sometimes the previous close. Since the open is our execution
  price, the validator watches for it.

Yahoo is a restated series, not a point-in-time one. We cannot reconstruct what
it said before we started archiving; from the first fetch onwards, ``raw/``
gives us the vintages.
"""

from __future__ import annotations

from datetime import date

from quant_backtester.data.instruments import Instrument
from quant_backtester.data.sources.base import RawDownload


class YahooSource:
    """Download daily bars and corporate actions from Yahoo Finance."""

    source_id = "YAHOO"

    def download(self, instrument: Instrument, start: date, end: date) -> RawDownload:
        """Fetch daily bars.

        Parameters
        ----------
        instrument : Instrument
            Instrument to fetch.
        start, end : date
            Inclusive requested range.

        Returns
        -------
        RawDownload
            Provider response, columns untouched.

        Notes
        -----
        Exercice 4.2 (moyen). Appelle ``yfinance.Ticker(...).history`` avec
        ``auto_adjust=False`` et ``actions=False``. Deux pieges :

        - ``end`` est exclusif chez yfinance, ta signature l'annonce inclusif.
        - ``filterwarnings = ["error"]`` est actif : le moindre ``FutureWarning``
          de yfinance fera echouer le test. Garde cet appel le plus fin possible
          et marque le test ``@pytest.mark.network``.

        Enregistre ``yfinance.__version__`` dans ``request`` : le jour ou une
        mise a jour change les colonnes, tu sauras quels snapshots sont concernes.
        """
        raise NotImplementedError("Exercice 4.2")

    def download_corporate_actions(
        self, instrument: Instrument, start: date, end: date
    ) -> RawDownload | None:
        """Fetch splits and dividends.

        Parameters
        ----------
        instrument : Instrument
            Instrument to fetch.
        start, end : date
            Inclusive requested range.

        Returns
        -------
        RawDownload | None
            ``None`` for instruments that cannot have corporate actions.

        Notes
        -----
        Exercice 4.3 (facile). ``Ticker.actions`` renvoie un DataFrame indexe par
        ex-date, colonnes ``Dividends`` et ``Stock Splits``, avec des zeros
        plutot que des NaN pour les jours sans evenement.
        """
        raise NotImplementedError("Exercice 4.3")


class FredSource:
    """Download published series from FRED (levels only).

    FRED series are revised, some heavily. A daily rate such as ``DGS10`` is
    stable in practice; a macro aggregate is not, and would need true vintages
    (ALFRED) rather than this adapter.
    """

    source_id = "FRED"

    def download(self, instrument: Instrument, start: date, end: date) -> RawDownload:
        """Fetch one published series.

        Parameters
        ----------
        instrument : Instrument
            Instrument to fetch.
        start, end : date
            Inclusive requested range.

        Returns
        -------
        RawDownload
            Provider response with its original ``DATE``/value columns.

        Notes
        -----
        Exercice 4.4 (facile). L'endpoint CSV public suffit et evite une
        dependance. Attention : FRED encode les jours sans valeur par un point
        ``"."``, qui doit rester tel quel dans le raw et n'etre interprete que
        par le normalizer.
        """
        raise NotImplementedError("Exercice 4.4")

    def download_corporate_actions(
        self, instrument: Instrument, start: date, end: date
    ) -> RawDownload | None:
        """Return ``None``: a published series has no corporate actions.

        Parameters
        ----------
        instrument : Instrument
            Ignored.
        start, end : date
            Ignored.

        Returns
        -------
        RawDownload | None
            Always ``None``.

        Notes
        -----
        Exercice 4.5 (trivial).
        """
        raise NotImplementedError("Exercice 4.5")


class EcbSource:
    """Download ECB reference rates (levels only).

    The ECB publishes its reference rates once a day, around 16:00 CET, for the
    same day. That release time is the instrument's ``PublicationRule``; it is
    not an exchange close and must not be derived from a calendar.
    """

    source_id = "ECB"

    def download(self, instrument: Instrument, start: date, end: date) -> RawDownload:
        """Fetch one reference series from the ECB data portal.

        Parameters
        ----------
        instrument : Instrument
            Instrument to fetch.
        start, end : date
            Inclusive requested range.

        Returns
        -------
        RawDownload
            Provider response, untouched.

        Notes
        -----
        Exercice 4.6 (facile).
        """
        raise NotImplementedError("Exercice 4.6")

    def download_corporate_actions(
        self, instrument: Instrument, start: date, end: date
    ) -> RawDownload | None:
        """Return ``None``: a reference rate has no corporate actions.

        Parameters
        ----------
        instrument : Instrument
            Ignored.
        start, end : date
            Ignored.

        Returns
        -------
        RawDownload | None
            Always ``None``.

        Notes
        -----
        Exercice 4.7 (trivial).
        """
        raise NotImplementedError("Exercice 4.7")
