"""Ingestion: download, normalise, validate, store.

Kept deliberately apart from :mod:`quant_backtester.data.reader` so that the
backtester, which only ever receives a reader, is physically unable to reach the
network mid-run.

The pipeline for one instrument::

    registry -> source.download -> repository.save_raw (immutable)
             -> normalizer     -> validator
             -> merge under the revision policy
             -> repository.save_clean (atomic)
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

from quant_backtester.data.calendars import CalendarRegistry
from quant_backtester.data.instruments import InstrumentRegistry
from quant_backtester.data.normalizer import Normalizer
from quant_backtester.data.repository import MarketDataRepository
from quant_backtester.data.revisions import AcceptedRevisions
from quant_backtester.data.sources.base import DataSource
from quant_backtester.data.validator import ValidationReport


class MarketDataUpdater:
    """Fetch and refresh the market data tree.

    Parameters
    ----------
    repository : MarketDataRepository
        Storage to write to.
    instruments : InstrumentRegistry
        Instrument registry.
    calendars : CalendarRegistry
        Calendar registry.
    sources : Mapping[str, DataSource]
        Adapters, keyed by source identifier.
    normalizers : Mapping[str, Normalizer]
        Normalizers, keyed by source identifier.
    accepted_revisions : AcceptedRevisions
        Reviewed decisions to apply.
    overlap_sessions : int
        How far back an update re-fetches, to detect provider revisions.
    """

    def __init__(
        self,
        repository: MarketDataRepository,
        instruments: InstrumentRegistry,
        calendars: CalendarRegistry,
        sources: Mapping[str, DataSource],
        normalizers: Mapping[str, Normalizer],
        accepted_revisions: AcceptedRevisions,
        overlap_sessions: int = 5,
    ) -> None:
        raise NotImplementedError("Exercice 9.1")

    def download(self, instrument_id: str, start: date, end: date) -> ValidationReport:
        """Fetch an instrument over a range and build its clean series.

        Parameters
        ----------
        instrument_id : str
            Instrument to fetch.
        start, end : date
            Inclusive requested range.

        Returns
        -------
        ValidationReport
            Issues found. Nothing is written to ``clean/`` when it is invalid;
            the raw snapshot is archived regardless, since it is evidence.

        Notes
        -----
        Exercice 9.2 (moyen). Enchaine le pipeline du docstring de module. Note
        l'ordre : ``save_raw`` a lieu **avant** la validation. Un telechargement
        invalide est precisement celui qu'on voudra reexaminer.
        """
        raise NotImplementedError("Exercice 9.2")

    def update(self, instrument_id: str) -> ValidationReport:
        """Extend an instrument's clean series with recent sessions.

        Parameters
        ----------
        instrument_id : str
            Instrument to refresh.

        Returns
        -------
        ValidationReport
            Issues found.

        Notes
        -----
        Exercice 9.3 (difficile - c'est ici que le bug classique se loge).

        Re-telecharge depuis ``last_date - overlap_sessions`` seances, puis
        fusionne via ``merge_with_policy``.

        **Le piege.** Le recouvrement detecte les revisions ponctuelles, mais ne
        peut rien contre un restatement retroactif : apres un split 4:1, le
        fournisseur reecrit *tout* l'historique. Fusionner cinq jours de
        nouvelles valeurs dans un stock reste a l'ancienne base fabrique un
        -75% fictif au milieu de la serie - qui passe tous les controles, parce
        que les dates sont triees, sans doublon, et les prix positifs.

        Comme on ne stocke que des prix bruts, le cas ne devrait pas se produire.
        Mais un fournisseur qui change silencieusement de convention, si. Donc :
        si les valeurs de recouvrement different de l'ancien stock par un
        **facteur constant**, ce n'est pas une revision, c'est un changement de
        base - refetch integral de l'instrument et signalement, jamais une
        fusion partielle.
        """
        raise NotImplementedError("Exercice 9.3")

    def update_all(self) -> dict[str, ValidationReport]:
        """Refresh every registered instrument.

        Returns
        -------
        dict[str, ValidationReport]
            One report per instrument.

        Notes
        -----
        Exercice 9.4 (facile). L'echec d'un instrument ne doit pas interrompre
        les autres : collecte les erreurs et rends-les toutes.
        """
        raise NotImplementedError("Exercice 9.4")

    def rebuild_clean(self, instrument_id: str) -> ValidationReport:
        """Rebuild an instrument's clean series from the raw archive alone.

        Parameters
        ----------
        instrument_id : str
            Instrument to rebuild.

        Returns
        -------
        ValidationReport
            Issues found.

        Notes
        -----
        Exercice 9.5 (difficile, et c'est la methode qui prouve tout le reste).

        Rejoue les snapshots ``raw/`` dans l'ordre chronologique, applique
        normalizer, validator et politique de revision, et reecrit ``clean/``.
        Aucun acces reseau.

        Elle materialise la propriete centrale du module :

            raw + instruments.toml + accepted_revisions.toml + calendriers
            + version du normalizer  ->  clean

        Le test associe est celui qu'on oublie toujours d'ecrire : deux appels
        consecutifs doivent produire des fichiers **identiques octet pour
        octet**. S'il echoue, il y a un etat cache quelque part - une horloge
        lue, un ordre de dictionnaire, un chemin absolu - et la reproductibilite
        n'est qu'une intention.
        """
        raise NotImplementedError("Exercice 9.5")
