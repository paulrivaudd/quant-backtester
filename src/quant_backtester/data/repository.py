"""Persistence: the only module that knows Parquet exists.

Layout under the market data root::

    metadata/
        instruments.toml            committed
        accepted_revisions.toml     committed - it changes past results
        calendars/*.toml            committed
    raw/<source>/<instrument_id>/<fetch_id>.parquet   immutable, append-only
    raw/<source>/<instrument_id>/<fetch_id>.json      request manifest
    clean/bars/<instrument_id>.parquet
    clean/levels/<instrument_id>.parquet
    clean/corporate_actions.parquet
    clean/revisions.parquet
    validation/validation_log.parquet

``raw/`` is written once and never touched again: one file per fetch, named by
the fetch instant. That is what answers "what did Yahoo actually give us on
10 September?" and what lets vintages be reconstructed later.

``clean/`` is entirely derived and disposable: it is a pure function of the raw
snapshots, the accepted revisions, the calendars and the normalizer version.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow as pa

from quant_backtester.data.sources.base import RawDownload
from quant_backtester.data.validator import ValidationReport


def write_parquet_atomic(frame: pd.DataFrame, path: Path, schema: pa.Schema) -> None:
    """Write a frame to Parquet so a crash cannot corrupt the dataset.

    Parameters
    ----------
    frame : pd.DataFrame
        Rows to write.
    path : Path
        Destination file; parent directories are created.
    schema : pa.Schema
        Expected schema; a mismatch is an error, not something to coerce.

    Raises
    ------
    ValueError
        If ``frame`` does not match ``schema``.

    Notes
    -----
    Exercice 3.1 (facile, non negociable). Ecris dans un temporaire **dans le
    meme repertoire** que la cible, puis ``os.replace``. Le rename est atomique
    sur le meme systeme de fichiers ; passer par ``/tmp`` casse cette garantie.
    Sans ca, une interruption en cours d'ecriture detruit l'historique complet
    d'un instrument.
    """
    raise NotImplementedError("Exercice 3.1")


class MarketDataRepository:
    """Read and write the market data tree.

    Parameters
    ----------
    root : Path
        Market data root, i.e. the directory holding ``metadata/``, ``raw/``,
        ``clean/`` and ``validation/``. Passed in rather than read from a global
        so tests can point at a temporary directory.
    """

    def __init__(self, root: Path) -> None:
        raise NotImplementedError("Exercice 3.2")

    def save_raw(self, download: RawDownload) -> Path:
        """Persist one provider response, immutably.

        Parameters
        ----------
        download : RawDownload
            Response to archive.

        Returns
        -------
        Path
            File written.

        Raises
        ------
        FileExistsError
            If that ``fetch_id`` already exists. Raw is append-only: overwriting
            would destroy the evidence the layer exists to keep.

        Notes
        -----
        Exercice 3.3 (facile). Ecris aussi le manifeste JSON a cote : symbole
        demande, plage, version de la librairie, nombre de lignes. C'est ce qui
        rend un snapshot lisible trois ans plus tard.
        """
        raise NotImplementedError("Exercice 3.3")

    def load_raw(self, instrument_id: str, source: str, fetch_id: str) -> RawDownload:
        """Load one archived provider response.

        Parameters
        ----------
        instrument_id : str
            Instrument concerned.
        source : str
            Source identifier.
        fetch_id : str
            Fetch identifier.

        Returns
        -------
        RawDownload
            The archived response.

        Notes
        -----
        Exercice 3.4 (facile).
        """
        raise NotImplementedError("Exercice 3.4")

    def list_raw_fetches(self, instrument_id: str, source: str) -> list[str]:
        """List the archived fetch identifiers, oldest first.

        Parameters
        ----------
        instrument_id : str
            Instrument concerned.
        source : str
            Source identifier.

        Returns
        -------
        list[str]
            Fetch identifiers in chronological order.

        Notes
        -----
        Exercice 3.5 (facile). L'ordre chronologique est ce qui rend la regle
        "premier arrive gagne" reproductible lors d'un rebuild.
        """
        raise NotImplementedError("Exercice 3.5")

    def save_bars(self, instrument_id: str, frame: pd.DataFrame) -> None:
        """Replace an instrument's clean bars.

        Parameters
        ----------
        instrument_id : str
            Instrument concerned.
        frame : pd.DataFrame
            Full canonical frame, chronologically sorted.

        Notes
        -----
        Exercice 3.6 (facile). Un fichier par instrument : la mise a jour reste
        bon marche et le remplacement atomique trivial.
        """
        raise NotImplementedError("Exercice 3.6")

    def load_bars(
        self, instrument_id: str, start: date | None = None, end: date | None = None
    ) -> pd.DataFrame:
        """Load an instrument's clean bars.

        Parameters
        ----------
        instrument_id : str
            Instrument concerned.
        start, end : date | None
            Inclusive bounds on ``session_date``; ``None`` means unbounded.

        Returns
        -------
        pd.DataFrame
            Canonical bars; empty frame with the right columns if none.

        Notes
        -----
        Exercice 3.7 (facile). Une frame vide **avec les bonnes colonnes** evite
        un ``KeyError`` a chaque cas limite en aval.

        Cette methode ne filtre **pas** sur la disponibilite : c'est le role du
        reader. Le repository ne connait que des fichiers.
        """
        raise NotImplementedError("Exercice 3.7")

    def save_levels(self, instrument_id: str, frame: pd.DataFrame) -> None:
        """Replace an instrument's clean levels.

        Parameters
        ----------
        instrument_id : str
            Instrument concerned.
        frame : pd.DataFrame
            Full canonical frame.

        Notes
        -----
        Exercice 3.8 (facile).
        """
        raise NotImplementedError("Exercice 3.8")

    def load_levels(
        self, instrument_id: str, start: date | None = None, end: date | None = None
    ) -> pd.DataFrame:
        """Load an instrument's clean levels.

        Parameters
        ----------
        instrument_id : str
            Instrument concerned.
        start, end : date | None
            Inclusive bounds on ``observation_date``.

        Returns
        -------
        pd.DataFrame
            Canonical levels.

        Notes
        -----
        Exercice 3.9 (facile).
        """
        raise NotImplementedError("Exercice 3.9")

    def save_corporate_actions(self, frame: pd.DataFrame) -> None:
        """Replace the corporate actions table.

        Parameters
        ----------
        frame : pd.DataFrame
            Full canonical frame, all instruments.

        Notes
        -----
        Exercice 3.10 (facile). Table unique : elle est minuscule et toujours lue
        en entier.
        """
        raise NotImplementedError("Exercice 3.10")

    def load_corporate_actions(self, instrument_id: str | None = None) -> pd.DataFrame:
        """Load corporate actions.

        Parameters
        ----------
        instrument_id : str | None
            Restrict to one instrument; ``None`` returns all.

        Returns
        -------
        pd.DataFrame
            Canonical corporate actions.

        Notes
        -----
        Exercice 3.11 (facile).
        """
        raise NotImplementedError("Exercice 3.11")

    def append_revisions(self, frame: pd.DataFrame) -> None:
        """Append detected revisions to the detection log.

        Parameters
        ----------
        frame : pd.DataFrame
            Rows matching the revisions schema.

        Notes
        -----
        Exercice 3.12 (facile). Append, jamais remplacement : c'est un journal.
        """
        raise NotImplementedError("Exercice 3.12")

    def load_revisions(self, instrument_id: str | None = None) -> pd.DataFrame:
        """Load the detection log.

        Parameters
        ----------
        instrument_id : str | None
            Restrict to one instrument; ``None`` returns all.

        Returns
        -------
        pd.DataFrame
            Detected revisions.

        Notes
        -----
        Exercice 3.13 (facile).
        """
        raise NotImplementedError("Exercice 3.13")

    def append_validation_log(self, reports: Sequence[ValidationReport]) -> None:
        """Persist validation issues.

        Parameters
        ----------
        reports : Sequence[ValidationReport]
            Reports to flatten into the log.

        Notes
        -----
        Exercice 3.14 (facile). Les warnings comptent autant que les erreurs :
        un warning affiche sur stdout est un warning perdu.
        """
        raise NotImplementedError("Exercice 3.14")

    def exists(self, instrument_id: str) -> bool:
        """Return whether an instrument has any clean data.

        Parameters
        ----------
        instrument_id : str
            Instrument concerned.

        Returns
        -------
        bool
            ``True`` if a clean bars or levels file exists.

        Notes
        -----
        Exercice 3.15 (facile).
        """
        raise NotImplementedError("Exercice 3.15")

    def first_date(self, instrument_id: str) -> date | None:
        """Return the earliest stored observation date.

        Parameters
        ----------
        instrument_id : str
            Instrument concerned.

        Returns
        -------
        date | None
            ``None`` if the instrument has no clean data.

        Notes
        -----
        Exercice 3.16 (facile).
        """
        raise NotImplementedError("Exercice 3.16")

    def last_date(self, instrument_id: str) -> date | None:
        """Return the latest stored observation date.

        Parameters
        ----------
        instrument_id : str
            Instrument concerned.

        Returns
        -------
        date | None
            ``None`` if the instrument has no clean data.

        Notes
        -----
        Exercice 3.17 (facile). C'est le point de depart de ``update()``.
        """
        raise NotImplementedError("Exercice 3.17")
