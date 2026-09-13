"""Yahoo Finance adapter, via ``yfinance``.

Provider quirks, all handled here and never leaked downstream:

- ``auto_adjust=True`` is the library default and must be turned **off**. With
  it on, the OHLC series itself is restated at every corporate action, so the
  value stored for a past date changes depending on the day it was downloaded.
- Splits and dividends are fetched separately and stored as their own table.
- The daily index is tz-aware, in the exchange's local time
  (``datetime64[s, America/New_York]`` for SPY with yfinance 1.7.0). Do not
  assume it stays so; check and normalise in the normalizer.
- yfinance never raises for an unknown symbol: it logs a 404 and returns an
  empty frame, exactly as for a valid request over a holiday or a weekend. The
  adapter tells the two apart and raises for the unknown symbol.
- On thinly traded European ETFs the opening print is unreliable: it is
  sometimes zero, sometimes the previous close. Since the open is our execution
  price, the validator watches for it.

Yahoo is a restated series, not a point-in-time one. We cannot reconstruct what
it said before we started archiving; from the first fetch onwards, ``raw/``
gives us the vintages.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta

import yfinance

from quant_backtester.data.instruments import AssetType, Instrument
from quant_backtester.data.sources.base import RawDownload, make_fetch_id, utc_now

ASSET_TYPES_WITH_ACTIONS = frozenset({AssetType.ETF, AssetType.EQUITY})
"""Asset types that can pay dividends or split. INDEX, RATE, FX, VOLATILITY cannot."""

YAHOO_TIMEZONE_KEY = "exchangeTimezoneName"
"""History metadata key Yahoo fills for every symbol it lists, even over an empty range."""


def _require_known_symbol(ticker: yfinance.Ticker, symbol: str) -> None:
    """Raise if Yahoo does not know ``symbol``.

    Call it only on an empty answer: an empty frame is legitimate over a
    holiday or a weekend, but it is also all yfinance returns for an unknown
    symbol. The history metadata tells the two apart, because Yahoo sets the
    exchange timezone of every symbol it lists.

    Parameters
    ----------
    ticker : yfinance.Ticker
        Ticker whose request came back empty.
    symbol : str
        Yahoo symbol, for the error message.

    Raises
    ------
    ValueError
        If the metadata carries no exchange timezone.
    """
    metadata = ticker.history_metadata
    if not metadata.get(YAHOO_TIMEZONE_KEY):
        raise ValueError(f"Yahoo does not know symbol {symbol!r} (unknown or delisted)")


class YahooSource:
    """Download daily bars and corporate actions from Yahoo Finance.

    Parameters
    ----------
    clock : Callable[[], datetime]
        Returns the timezone-aware UTC instant of a download. Injected so tests
        never depend on the wall clock.
    """

    source_id = "YAHOO"

    def __init__(self, clock: Callable[[], datetime] = utc_now) -> None:
        self._clock = clock

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
            Provider response, columns untouched. Empty when the range holds no
            session, e.g. a single holiday.

        Raises
        ------
        ValueError
            If ``start`` is after ``end``, if the clock is not UTC, or if Yahoo
            does not know ``instrument.source_symbol``.

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
        if start > end:
            raise ValueError(f"start {start} is after end {end}")
        # yfinance treats ``end`` as exclusive; our range is inclusive.
        end_sent = end + timedelta(days=1)
        request: dict[str, object] = {
            "symbol": instrument.source_symbol,
            "start": start.isoformat(),
            "end_inclusive": end.isoformat(),
            "end_sent": end_sent.isoformat(),
            "interval": "1d",
            "auto_adjust": False,
            "actions": False,
            "yfinance_version": yfinance.__version__,
        }
        # Read the clock once, before the call: fetch_id and retrieved_at_utc
        # must name the same instant, and a non-UTC clock fails before any I/O.
        retrieved_at_utc = self._clock()
        fetch_id = make_fetch_id(retrieved_at_utc)
        ticker = yfinance.Ticker(instrument.source_symbol)
        frame = ticker.history(
            start=start, end=end_sent, interval="1d", auto_adjust=False, actions=False
        )
        if frame.empty:
            _require_known_symbol(ticker, instrument.source_symbol)
        return RawDownload(
            instrument_id=instrument.id,
            source=self.source_id,
            fetch_id=fetch_id,
            retrieved_at_utc=retrieved_at_utc,
            frame=frame,
            request=request,
        )

    def download_corporate_actions(
        self, instrument: Instrument, start: date, end: date
    ) -> RawDownload | None:
        """Fetch splits and dividends.

        Parameters
        ----------
        instrument : Instrument
            Instrument to fetch.
        start, end : date
            Inclusive requested range. Recorded in ``request`` but **not**
            applied: see Notes.

        Returns
        -------
        RawDownload | None
            ``None`` for instruments that cannot have corporate actions, decided
            from ``asset_type`` before any call to Yahoo. An empty frame when a
            known symbol never had any event.

        Raises
        ------
        ValueError
            If ``start`` is after ``end``, if the clock is not UTC, or if Yahoo
            does not know ``instrument.source_symbol``.

        Notes
        -----
        Exercice 4.3 (facile). ``Ticker.actions`` renvoie un DataFrame indexe par
        ex-date, colonnes ``Dividends`` et ``Stock Splits``, avec des zeros
        plutot que des NaN pour les jours sans evenement.

        ``Ticker.actions`` takes no range: yfinance always downloads
        ``period="max"``. The frame is archived whole, as Yahoo sent it, and
        ``request`` says so. Restricting it to ``[start, end]`` is the
        normalizer's job; filtering here would make the raw archive lie about
        what the provider returned.
        """
        if instrument.asset_type not in ASSET_TYPES_WITH_ACTIONS:
            return None
        if start > end:
            raise ValueError(f"start {start} is after end {end}")
        request: dict[str, object] = {
            "symbol": instrument.source_symbol,
            "endpoint": "actions",
            "period": "max",
            "start": start.isoformat(),
            "end_inclusive": end.isoformat(),
            "yfinance_version": yfinance.__version__,
        }
        retrieved_at_utc = self._clock()
        fetch_id = make_fetch_id(retrieved_at_utc)
        ticker = yfinance.Ticker(instrument.source_symbol)
        frame = ticker.actions
        if frame.empty:
            _require_known_symbol(ticker, instrument.source_symbol)
        return RawDownload(
            instrument_id=instrument.id,
            source=self.source_id,
            fetch_id=fetch_id,
            retrieved_at_utc=retrieved_at_utc,
            frame=frame,
            request=request,
        )
