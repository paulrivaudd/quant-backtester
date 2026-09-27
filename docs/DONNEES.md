# La couche `data`

État au 2026-09-27. Ce document explique comment une réponse de fournisseur
devient une observation qu'une décision pouvait connaître, et comment ajouter un
instrument ou une source. Le résumé est dans [ARCHITECTURE.md](ARCHITECTURE.md)
§5, les formules dans [FORMULES.md](FORMULES.md) §5, et les opérations sur titres
dans [OPERATIONS_SUR_TITRES.md](OPERATIONS_SUR_TITRES.md).

La couche doit préserver trois choses : **la valeur d'origine, sa provenance et
l'instant où elle est devenue disponible**. Combler un trou avec la dernière
valeur donne un joli graphique, mais c'est inventer une donnée. Mélanger un prix
brut et un prix ajusté crée un rendement qui n'a pas existé.

## 1. Les instruments déclarés

`market_data/metadata/instruments.toml` :

| Id | Nature | Source principale (contrôle) | Calendrier | Négociable | Depuis | `history_basis` |
|---|---|---|---|---|---|---|
| `SP500` | indice, USD | Yahoo `^GSPC` | XNYS | non | 1990-01-02 | `ASSUMED_UNREVISED` |
| `ETF_SP500_PEA` | ETF capitalisant, EUR, parts entières | Yahoo `ESE.PA` (Euronext) | XPAR | oui | 2014-03-18 | `ASSUMED_UNREVISED` |
| `ETF_WORLD` | ETF capitalisant, EUR, parts entières | Yahoo `CW8.PA` (Euronext) | XPAR | oui | 2018-04-18 | `ASSUMED_UNREVISED` |
| `VIX` | niveau de volatilité, sans devise | FRED `VIXCLS` | publication 16:15 New York | non | 1990-01-02 | `ASSUMED_UNREVISED` |
| `US10Y` | taux, en points de pourcentage | FRED `DGS10` | publication J+1 sur XNYS | non | 1990-01-02 | **`RESTATED`** |
| `ECB_EURUSD` | change, USD par EUR | BCE `EXR.D.USD.EUR.SP00.A` | publication le jour même | non | 1999-01-04 | `ASSUMED_UNREVISED` |

Univers (`universes.toml`, membres datés) : `ROTATION_2` contient les deux ETF,
`ETF_SP500_PEA` à partir du 2018-04-18. `MACRO_3` contient les trois séries
publiées, qu'on lit comme information et qu'on ne négocie jamais.

Unités : un taux de 4,25 signifie 4,25 % par an, pas 425 %. EURUSD est un nombre
de dollars par euro. Le VIX est un indice calculé sur des options : ce n'est ni
un rendement ni une part qu'on peut détenir. Un fixing de la BCE n'est pas un
prix d'exécution.

## 2. Les sources et leurs limites

| Source | Sert | Limites déclarées |
|---|---|---|
| Yahoo (`sources/yahoo.py`) | barres quotidiennes, splits et dividendes (table à part) | avec `auto_adjust=False`, les prix antérieurs à un split restent quand même ajustés, donc **une action ou un ETF avec un split dans son historique est refusé** ; aucune date d'annonce ni de paiement ; rien pour un titre radié |
| Euronext (`sources/euronext.py`) | seconde série de barres, pour le contrôle croisé | fenêtre glissante de 730 jours (`EURONEXT_WINDOW`, une convention de l'adaptateur, pas une promesse du fournisseur) ; la demande est adaptée après `ProviderRangeUnavailable` |
| FRED (`sources/fred.py`) | niveaux publiés | la **dernière version** de la série, donc restatée |
| ALFRED (`sources/alfred.py`) | les versions (*vintages*) d'une série FRED | implémenté, mais aucun instrument ne l'utilise |
| BCE (`sources/ecb.py`) | taux de référence | un fixing, pas des barres OHLC |

Toutes les erreurs d'un fournisseur héritent de `ProviderError`
(`ProviderUnavailable`, `ProviderRateLimited`, `ProviderResponseError`, …). Une
source de contrôle qui ne répond pas devient un avertissement, et l'ingestion
continue. Un `TypeError` dans notre propre code de lecture arrête tout.

**Calendriers** (`metadata/calendars/`, générés par
`scripts/generate_calendars.py` depuis `exchange_calendars`, puis vérifiés
séance par séance) : XNYS de 1990 à fin 2027, XPAR de 2002 à fin 2027. En dehors,
on obtient `CalendarCoverageError`. Un jour de semaine n'est jamais supposé être
une séance. `scripts/check_calendar_coverage.py` échoue quand il reste moins de
90 jours de couverture.

## 3. Les quatre dates

| Champ | Sens |
|---|---|
| `session_date` / `observation_date` | le jour que la donnée **décrit** (`date`) |
| `open_available_at_utc`, `close_available_at_utc` / `available_at_utc` | l'instant à partir duquel le lecteur la **sert** |
| `retrieved_at_utc` | l'instant du téléchargement |
| `vintage_date` | la version de publication d'une série révisée |

Le lecteur impose `disponible ≤ instant de décision`. Une barre a **deux**
instants : l'OPEN est disponible à l'ouverture, alors que HIGH, LOW, CLOSE et
VOLUME le sont à la clôture (`schemas.AVAILABILITY_COLUMN`). Connaître le plus
haut de la séance avant sa fin, ce serait lire le futur. Un niveau publié est
disponible selon sa `PublicationRule` : heure, fuseau et décalage en séances d'un
calendrier déclaré.

## 4. Les schémas canoniques (`data/schemas.py`)

Tous les horodatages sont en UTC, à la microseconde. Les prix sont des `float64`
dans la devise de l'instrument, et le volume est un nombre d'unités échangées.

- `BARS_SCHEMA` : identifiant, date, OHLCV, les deux disponibilités, `source`,
  `source_fetch_id`.
- `CHECKED_BARS_SCHEMA` : la barre retenue, plus `check_status`,
  `checked_sources`, `checked_fetch_ids`, `conflicting_fields`,
  `unconfirmed_fields`, `max_price_rel_diff` et `max_volume_rel_diff`. **C'est
  ce que lisent les stratégies.**
- `LEVELS_SCHEMA` : date, valeur, disponibilité, provenance.
- `VINTAGES_SCHEMA` : ajoute `vintage_date` et `withdrawn`. Une valeur retirée par
  une publication ultérieure est une **ligne de retrait**. Si on la supprimait,
  l'ancienne valeur reviendrait.
- `CORPORATE_ACTIONS_SCHEMA` : type, date ex, valeur, disponibilité, provenance.

## 5. Nettoyer sans inventer

1. **Normaliser** (`normalizer.py`). Les colonnes du fournisseur deviennent les
   champs canoniques, et les dates deviennent des séances de la place.
   `bars_frame` date chaque champ et écarte trois cas, qu'il nomme dans
   `RejectedRows` :
   - `non_session` : un jour où la place n'a pas tenu séance ;
   - `unlisted` : un jour hors de la période de cotation. Yahoo sert 74 valeurs
     liquidatives plates de CW8 avant sa cotation ;
   - `unpublished` : une barre téléchargée avant sa clôture, qui n'est donc pas
     définitive.
2. **Valider** (`validator.py`). Il y a deux niveaux :
   - `ERROR` bloque la promotion : prix nul ou négatif, volume négatif, OHLC
     incohérent, doublon, action invalide ;
   - `WARNING` la laisse passer. **Un mouvement extrême est un avertissement,
     pas une erreur** : supprimer un vrai krach embellirait la stratégie.
3. **Corriger ce qui doit l'être, sans rien réparer.** Une `BarCorrection`
   (`bar_corrections.toml`) **supprime** une barre précise et donne sa raison.
   Elle ne fabrique jamais de prix de remplacement. Si le défaut qu'elle vise a
   disparu d'une nouvelle réponse, la correction est refusée et doit être revue.
   Un `KnownGap` (`known_gaps.toml`) explique un trou sans le combler.

## 6. Réconcilier deux sources (`crosscheck.py`)

L'écart `δ` est défini dans [FORMULES.md](FORMULES.md) §5, les tolérances par champ
dans `crosscheck.toml`.

- Un champ dont l'écart dépasse sa tolérance rend la ligne `CONFLICT`. Le lecteur
  **ne bloque que ce champ** : un plus bas contesté ne masque pas une clôture
  concordante.
- Moins de deux valeurs finies pour un champ, c'est un champ **non confirmé**,
  pas un accord.
- La série retenue contient les dates de la source principale. Une date que seule
  la source de contrôle possède est signalée, mais elle n'est pas servie.
- `REVIEWED` (`conflict_reviews.toml`) veut dire qu'une revue a choisi une source
  pour les valeurs exactes qu'elle a examinées. **Ce n'est pas un consensus.** Si
  les valeurs changent, la revue ne s'applique plus.

## 7. Révisions et historique

Les fournisseurs réécrivent le passé. Par défaut, **la première valeur stockée
reste la valeur canonique**. `detect_revisions` journalise chaque différence, et
`merge_with_policy` ajoute les nouvelles dates. Il n'applique un changement ancien
que si son identité exacte (source, instrument, date, champ, ancienne et nouvelle
valeur) figure dans `accepted_revisions.toml`. `scripts/accept_revision.py`
prépare le bloc à relire. La barre qui en résulte est revalidée : accepter un seul
champ peut rendre l'OHLC incohérent.

Chaque instrument déclare ce qu'est son historique, avec `history_basis` et
`history_note`, tous deux obligatoires dans le TOML :

| `HistoryBasis` | Ce qu'on peut affirmer |
|---|---|
| `ASSUMED_UNREVISED` | les valeurs servies aujourd'hui sont supposées être celles du passé (une clôture de bourse, un fixing publié une fois) ; `history_note` dit pourquoi |
| `RESTATED` | la série contient des corrections postérieures aux décisions : un backtest qui la lit a une anticipation qu'il doit déclarer (`US10Y`) |
| `ARCHIVED_VINTAGES` | chaque valeur telle qu'elle a été publiée ; uniquement pour une série lue par versions, avec `vintage_policy = AS_OF_DECISION` |

Une série lue par versions déclare aussi sa `VintagePolicy`. `AS_OF_DECISION`
donne la dernière version que la décision pouvait voir. `PINNED` fige une seule
version pour toute l'étude : c'est reproductible, mais pas fidèle à ce que
chaque date savait.

Horodater les champs protège la lecture. Cela ne transforme pas une série restatée
en archive des publications. Les revues et les corrections sont une configuration
de recherche : elles ne sont pas datées.

## 8. Stocker et rejouer (`repository.py`, `updater.py`)

- `raw/` est immuable : chaque téléchargement est archivé avec un manifeste JSON,
  y compris ceux qui ont été **refusés**.
- `clean/` est la couche dérivée. Une promotion écrit les barres contrôlées, les
  révisions, les problèmes de validation et `applied_fetches.parquet`, **en une
  seule transaction** : les fichiers sont préparés sous `.pending/`, un manifeste
  SHA-256 est écrit, puis tout est publié sous un verrou exclusif. Une reprise
  termine une publication décidée ou jette une préparation inachevée.
- Le verrou (`market_data/.lock`, `flock`, POSIX seulement) est partagé pour un
  run et exclusif pour une écriture. Un écrivain concurrent reçoit `StoreBusy`.
- Limite : ce n'est **pas** un instantané atomique au niveau du système de
  fichiers. Pendant les quelques microsecondes des renommages, un lecteur qui ne
  prendrait pas le verrou pourrait voir un ancien fichier et un nouveau.
- `rebuild_clean` (`--rebuild`) rejoue **les seuls téléchargements listés dans
  `applied_fetches.parquet`**, puisque `raw/` contient aussi des refus. Le rebuild
  complet est une seule transaction. Il échoue sans rien écrire si un
  téléchargement du journal manque dans `raw/`, ou si un rejeu ne passe plus.

> **Ne supprimez jamais `clean/` pour « repartir de zéro ».** Le journal
> `applied_fetches.parquet` est dedans. Sans lui, le rejeu ne sait plus quels
> téléchargements avaient été promus, et reconstruit un store vide. Pour
> reconstruire, lancez `--rebuild` sur un `clean/` intact. Pour conserver un
> run, utilisez `research.archive.keep(..., store=...)`, qui copie le store lu.

## 9. Lire (`reader.py`)

`MarketDataReader.at(instant)` renvoie un `PointInTimeReader` figé. Ses méthodes
ne prennent aucune date au-delà de cet instant. `_available_rows` applique la
disponibilité, les conflits et les versions, puis `_observe` ajoute un statut
(`OK`, `STALE`, `NOT_LISTED`, `MISSING`) et un âge compté en séances du
calendrier de référence. Un trou n'est jamais comblé par un report de prix.

Séquence complète d'une mise à jour :

1. `scripts/update_market_data.py:build_updater` charge les TOML, les
   adaptateurs (`SOURCES`) et les normaliseurs (`NORMALIZERS`).
2. `update` ou `archive_history` télécharge. `save_raw` archive chaque réponse.
3. Les normaliseurs et corrections s'appliquent, puis la validation.
4. Si rien ne bloque, la promotion fusionne, contrôle les sources entre elles et
   écrit dans une transaction.
5. Pendant un backtest, `MarketDataReader.at` fournit le lecteur daté aux signaux
   et au moteur.

## 10. Ajouter un instrument d'une source existante

1. **Identifier précisément l'instrument** : nom, ISIN, devise de cotation,
   symbole chez le fournisseur, dates de cotation, politique de distribution.
   Distinguer les parts d'un même fonds.
2. **Le déclarer** dans `instruments.toml` en copiant un instrument comparable :
   `history_basis` et `history_note` sont obligatoires, ainsi que
   `distribution_policy` pour un fonds. `tradable = true` demande un modèle
   d'exécution qui convient (même devise que le livre, lots `quantity_step`) :
   qu'un cours soit téléchargeable ne suffit pas.
3. Pour une **barre**, indiquer le calendrier exact de la place. Pour un
   **niveau**, indiquer l'heure, le fuseau et le décalage de publication. Pour des
   versions réellement archivées, utiliser ALFRED avec `AS_OF_DECISION`.
4. **L'ajouter à un univers** daté dans `universes.toml`. Un indicateur
   macroéconomique se demande comme information (`SignalRequest`), il n'entre pas
   dans l'univers négocié.
5. **Télécharger, puis contrôler** :

   ```bash
   uv run python scripts/update_market_data.py --archive --only ETF_WORLD   # tout l'historique déclaré
   uv run python scripts/update_market_data.py --coverage --only ETF_WORLD  # ce qui manque, sans télécharger
   uv run python scripts/update_market_data.py --only ETF_WORLD             # prolonger la série
   uv run python scripts/update_market_data.py --rebuild --only ETF_WORLD   # rejouer raw/, sans réseau
   ```

   Lire le rapport : bornes, trous, OHLC, avertissements, conflits,
   disponibilité. Vérifier quelques séances à la main contre le site de la place.
   Un conflit se tranche dans `conflict_reviews.toml`, un trou s'explique dans
   `known_gaps.toml`, et rien ne se corrige en silence.

## 11. Ajouter une source

Deux classes, et l'adaptateur garde **toutes** les particularités du fournisseur :

```python
"""Une source locale : un CSV par instrument, prix bruts, sans flux d'OST."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from quant_backtester.data.calendars import TradingCalendar
from quant_backtester.data.instruments import Instrument
from quant_backtester.data.normalizer import NormalizedData, bars_frame
from quant_backtester.data.sources.base import RawDownload, make_fetch_id


class CsvSource:
    """Lit ``<répertoire>/<source_symbol>.csv`` : date,open,high,low,close,volume."""

    source_id = "LOCAL_CSV"

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def available_from(self, instrument: Instrument) -> date | None:
        return None  # aucune fenêtre déclarée

    def download(self, instrument: Instrument, start: date, end: date) -> RawDownload:
        if start > end:
            raise ValueError(f"période inversée : {start} > {end}")
        path = self.directory / f"{instrument.source_symbol}.csv"
        frame = pd.read_csv(path, dtype={"date": str})
        days = frame["date"].map(date.fromisoformat)
        now = datetime.now(UTC)  # l'instant du téléchargement : c'est une donnée
        return RawDownload(
            instrument_id=instrument.id,
            source=self.source_id,
            fetch_id=make_fetch_id(now),
            retrieved_at_utc=now,
            frame=frame.loc[days.between(start, end)].reset_index(drop=True),
            request={"path": str(path), "start": str(start), "end_inclusive": str(end)},
        )

    def download_corporate_actions(
        self, instrument: Instrument, start: date, end: date
    ) -> RawDownload | None:
        return None  # pas de flux d'OST : à réserver à une série sans événement


class CsvNormalizer:
    source_id = "LOCAL_CSV"

    def normalize(
        self, instrument: Instrument, download: RawDownload, calendar: TradingCalendar | None = None
    ) -> NormalizedData:
        if calendar is None:
            raise ValueError(f"{instrument.id}: une barre demande son calendrier")
        frame = download.frame
        days = [date.fromisoformat(day) for day in frame["date"]]
        values = {
            field: [float(value) for value in frame[field]]
            for field in ("open", "high", "low", "close", "volume")
        }
        bars, rejected = bars_frame(instrument, download, calendar, days, values)
        return NormalizedData(bars=bars, rejected=rejected)
```

L'exemple omet les docstrings numpy pour rester court. Elles restent obligatoires
dans le code livré.

Pour la brancher :

- ajouter `"LOCAL_CSV": lambda: CsvSource(Path("mes_csv"))` à `SOURCES` dans
  `scripts/update_market_data.py` ;
- ajouter `CsvNormalizer()` à `NORMALIZERS` dans `data/normalizer.py` ;
- déclarer `primary_source = "LOCAL_CSV"`, avec `source_symbol` égal au nom du
  fichier sans extension.

`bars_frame` date les champs et écarte les week-ends, les jours hors cotation et
les barres pas encore publiées. Il refuse un champ manquant ou une séance en
double. L'adaptateur n'a qu'à produire des dates de séance et cinq colonnes de
nombres. Pour un Excel, seule la lecture change. Une source sans flux d'OST ne
convient qu'à une série vérifiée sans événement. Sinon, il faut écrire son flux
d'OST avant de l'utiliser.

**Tests minimums d'une nouvelle source** (sur le modèle de
`tests/data/test_normalizer.py`, `test_reader.py`, `test_updater.py`, sans
réseau, sur une réponse enregistrée) :

- trois séances connues : ouverture, clôture et instants UTC exacts ;
- un doublon, une date de week-end, une clôture hors de `[low, high]` et une ligne
  téléchargée avant la clôture : chacun donne un diagnostic explicite ;
- une lecture juste avant l'ouverture, juste après, puis après la clôture ;
- **la garde anti look-ahead** : ajouter une ligne future ne change aucune
  lecture antérieure ;
- un test réel `@pytest.mark.network`, lancé à part (`uv run pytest -m network`).
