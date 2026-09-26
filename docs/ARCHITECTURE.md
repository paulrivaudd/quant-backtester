# Architecture

État au 2026-09-26. Ce document décrit comment le projet est découpé, comment
une séance de backtest se déroule et quels mécanismes garantissent qu'un
résultat est juste et reproductible. Les règles de développement sont dans
[CLAUDE.md](../CLAUDE.md). Pour écrire une stratégie, voir le
[guide du développeur](GUIDE_NOUVELLE_STRATEGIE.md).

## 1. Ce que le projet cherche à garantir

Le framework backteste des stratégies quotidiennes, et il vise d'abord la
**confiance** dans un chiffre, pas la vitesse. Tous les choix ci-dessous
servent trois propriétés :

1. **Aucune information du futur.** Une décision ne lit que ce qui était
   publié à son instant. Ce qu'une donnée décrit (sa date) et le moment où
   elle devient disponible sont deux choses distinctes.
2. **Rien d'implicite.** Les calendriers, les coûts, les prix d'exécution, les
   fenêtres et les paramètres sont déclarés et enregistrés avec le résultat.
3. **Reproductible au bit près.** Le même code, la même configuration commitée
   et le même store donnent les mêmes nombres. Un `run_id` le prouve.

## 2. Les couches et la règle de dépendance

```
src/quant_backtester/
    data/        store Parquet local, fournisseurs, calendriers, lecture point-in-time
      │
    signals/     marché à un instant  ->  un nombre par instrument (+ un statut)
      │
    portfolio/   décision  ->  allocation cible admissible (poids, limites, lots)
      │
    execution/   cible  ->  ordres, fills, rejets, coûts
      │
    backtest/    la boucle qui fait avancer le temps, le contexte de décision, le runner
      │
    analytics/   performance brute/nette, benchmark, attribution, incertitude
      │
    strategies/  des règles composées à partir des couches ci-dessus
      │
    research/    hypothèses, registre des expériences, archives de runs, paper trading
```

Les dépendances vont **dans un seul sens**, de haut en bas dans ce schéma. Une
couche basse n'importe jamais une couche haute : si elle a besoin d'une
information d'en haut, on la lui passe en argument. Trois règles
supplémentaires sont vérifiées par des tests (`tests/test_package_structure.py`) :

- `strategies/` et `analytics/` n'importent jamais `quant_backtester.data`.
  Une stratégie ne peut donc pas ouvrir un reader et lire au-delà de son
  instant.
- Aucune couche n'importe `research/`.
- Seul `data/` fait des entrées-sorties réseau.

| Paquet | Rôle | Modules clés |
|---|---|---|
| `data/` | Ingestion, contrôle, stockage et lecture des séries de marché | `sources/`, `normalizer`, `validator`, `crosscheck`, `repository`, `reader`, `calendars`, `instruments`, `universes` |
| `signals/` | Transformations réutilisables d'un historique en un nombre | `base` (`Signal`, `SignalResult`), `windows`, `types`, `engine`, `snapshot`, `price/`, `risk/`, `level/`, `cross_sectional/` |
| `portfolio/` | Ce qu'un livre a le droit de détenir | `targets` (`TargetAllocation`), `allocation`, `constraints`, `limits`, `state`, `view` |
| `execution/` | Ce que le marché fait d'un ordre | `model` (`ExecutionModel`, `Sizing`), `costs` (`CostModel`), `orders`, `fills`, `rounding` |
| `backtest/` | Le temps | `engine`, `timetable`, `schedule`, `context` (`StrategyContext`), `market`, `runner` (`StrategyRunner`, `StrategyResult`) |
| `analytics/` | Ce qu'un run a produit | `performance`, `report`, `comparison`, `attribution`, `contribution`, `uncertainty` |
| `strategies/` | Les règles | `base` (`Strategy`), `functional` (`@strategy`), `examples/` |
| `research/` | La discipline de recherche | `hypotheses`, `registry`, `archive`, `paper`, `journal` |

`provenance.py` (état git du code qui a produit un résultat) et `numbers.py`
(gardes sur les paramètres numériques) sont transverses.

## 3. Une séance, trois instants

Un backtest quotidien parle souvent du « prix du jour », qui n'existe pas. Chaque
séance du calendrier de référence (XPAR, Euronext Paris) a trois instants,
déclarés dans `backtest/timetable.py` et enregistrés avec le résultat :

```
 séance J-1                               séance J
 ─────────────────────────────┬───────────────────────────────────────────────────
                        23:00 │ 09:01             17:30       23:00         23:00
                   DÉCISION   │ EXÉCUTION         clôture     VALORISATION  DÉCISION
                   (lit tout  │ (ordres de J-1    Paris       (livre marqué (signaux de J,
                    ce qui est│  remplis au prix              aux clôtures  cible pour J+1)
                    publié)   │  d'ouverture)                  connues)
```

- **Décision, 23:00 Paris.** Assez tard pour que la clôture de New York du même
  jour soit publiée : une séance américaine et une séance européenne sont
  ainsi comparables. Les signaux sont calculés et la stratégie fixe une cible.
- **Exécution, ouverture de la séance suivante.** Les ordres sont dimensionnés
  et remplis au prix de l'enchère d'ouverture (`Sizing.AT_AUCTION`, par
  défaut). `Sizing.AT_DECISION` fige les quantités à la clôture de la décision,
  comme un ordre passé la veille.
- **Valorisation, après la clôture.** Le livre est marqué aux prix de clôture
  connus à cet instant, puis vient la décision suivante.

L'ordre des instants est vérifié : une décision prise avant la valorisation de
son propre livre recevrait un portefeuille venu de son futur. Le décalage entre
une clôture américaine et l'ouverture européenne suivante est modélisé
explicitement. Il n'est jamais approximé par « la barre suivante ».

## 4. Le déroulé d'un run

```
StrategyRunner.run(strategy, universe, start, end, schedule=...)
 │
 ├─ strategy.validate()                    configuration complète et sérialisable
 ├─ calendrier de référence -> séances     (jamais freq="B")
 │
 └─ BacktestEngine, pour chaque séance :
      1. exécution    ordres en attente -> fills au prix d'ouverture, coûts, rejets
      2. valorisation livre marqué aux clôtures disponibles
      3. si la séance est dans le schedule :
           reader.at(23:00)              -> PointInTimeReader figé à cet instant
           SignalEngine.compute(...)     -> SignalSnapshot (un résultat par signal)
           StrategyContext(...)          -> signaux, marché, livre, univers du jour
           strategy.decide(ctx)          -> TargetAllocation
           portfolio: limites, lots      -> ordres pour la séance suivante
      4. BacktestRecord de la séance     (tout ce qui s'est passé, conservé)
 │
 └─ StrategyResult : records, report() brut/net, compare() au benchmark,
                     run_id, empreinte de la stratégie, état du code
```

Seul `backtest/engine.py` fait avancer le temps. Les signaux et la stratégie
reçoivent un instant et l'historique disponible à cet instant, rien d'autre.

## 5. La couche `data`

### Ingestion

```
fournisseur (Yahoo, Euronext, FRED, ALFRED, BCE)
   │  sources/<fournisseur>.py      seul endroit qui connaît les colonnes du fournisseur
   ▼
raw/          téléchargements immuables, jamais réécrits
   │  normalizer.py                 schéma canonique, horodatage de disponibilité (UTC)
   │  validator.py                  règles par classe d'actifs
   │  crosscheck.py                 plusieurs sources -> une série contrôlée, champ par champ
   ▼
clean/checked_bars/                 ce que les stratégies lisent
```

`scripts/update_market_data.py` pilote l'ingestion. Une promotion écrit les
barres, les verdicts de contrôle, le journal des révisions et celui des
téléchargements appliqués **en une seule transaction** : les fichiers sont
préparés sous `.pending/`, un manifeste SHA-256 est écrit, puis tout est
publié ensemble. Un verrou (`market_data/.lock`) est partagé pour les runs et
exclusif pour les écritures ; un écrivain concurrent reçoit `StoreBusy`.

### Métadonnées commitées

`market_data/metadata/` est de la configuration versionnée, pas de la donnée :

| Fichier | Contenu |
|---|---|
| `instruments.toml` | chaque série : type, calendrier, publication, négociabilité, `history_basis` et `history_note` obligatoires |
| `calendars/` | séances, heures réelles d'ouverture et de clôture, demi-séances |
| `universes.toml` | membres datés (un nom sorti garde sa date de sortie) |
| `crosscheck.toml` | tolérances entre sources |
| `known_gaps.toml` | trous connus et expliqués |
| `conflict_reviews.toml` | conflits entre sources revus et tranchés (statut `REVIEWED`) |
| `bar_corrections.toml` | barres cassées supprimées (jamais réparées), avec la raison |
| `accepted_revisions.toml`, `corporate_actions.toml` | révisions et événements revus |

### Lecture point-in-time

`MarketDataReader.at(instant)` renvoie un `PointInTimeReader` figé. Ses méthodes
ne prennent **aucun** argument de date : il n'existe pas d'expression qui lise
au-delà. Chaque lecture porte un statut : `OK`, `STALE` (dernière valeur trop
ancienne), `NOT_LISTED` (l'instrument n'existait pas) ou `MISSING` (trou, ou
séance contestée par deux sources). Un trou n'est jamais comblé par un
report de prix. L'âge d'une valeur se compte en séances du calendrier de
référence.

## 6. La couche `signals`

Un **signal** transforme le marché à un instant en un nombre par instrument.
Il ne décide rien : « le momentum de ce fonds est +8,1 % » est un signal,
« acheter les deux meilleurs » est une stratégie.

- Un signal est un **dataclass gelé**. `definition()` liste tous les paramètres
  qui changent le nombre, et `fingerprint()` en est le hachage.
- Une fenêtre déclare son contrat (`WindowSpec`) : `CONSECUTIVE_SESSIONS`
  (N séances tenues par la place, sans trou) ou `AVAILABLE_OBSERVATIONS`
  (N observations publiées, pour un indicateur). `signals/windows.py` est le
  seul endroit qui charge une fenêtre, et il refuse celle qui ne correspond
  pas au contrat. `tail(N)` n'est pas une fenêtre.
- La base de prix est explicite : `RAW` (cotation) ou `ADJUSTED` (ajustée des
  opérations connues à l'instant de décision).
- Chaque résultat porte un statut par instrument : `OK`, `NOT_LISTED`,
  `MISSING_INPUT`, `STALE_INPUT`, `INSUFFICIENT_HISTORY`,
  `NON_CONSECUTIVE_HISTORY`, `INSUFFICIENT_CROSS_SECTION` ou `INVALID_INPUT`.
  Un nombre n'existe que si le statut est `OK`, et `SignalResult` le vérifie.
- `SignalEngine` calcule les signaux déclarés et produit un `SignalSnapshot`.
  Un `SignalRequest` calcule un signal sur un univers à lui, par exemple le VIX
  lu comme jauge sans être détenu.

Signaux disponibles : `ReturnSignal`, `MomentumSignal`, `MeanReversionSignal`,
`MovingAverageTrendSignal`, `MovingAverageCrossSignal` (prix), `RealizedVolatilitySignal`,
`CurrentDrawdownSignal` (risque), `LevelChangeSignal`, `LevelZScoreSignal`
(séries publiées), `CrossSectionalRank` (classement).

## 7. Stratégie et contexte de décision

Une stratégie (`strategies/base.py`) déclare ses signaux et prend une décision :

```python
class Strategy(ABC):
    def required_signals(self) -> Sequence[Signal | SignalRequest]: ...
    def decide(self, ctx: StrategyContext) -> TargetAllocation: ...
```

Ses paramètres sont les champs d'un dataclass gelé. Ils entrent dans
`definition()` et `fingerprint()`, donc dans l'identité du run. Le moteur
vérifie que la définition n'a pas changé pendant le run (`StrategyMutated`).

`StrategyContext` (dans `backtest/`, car c'est le moteur qui le construit)
contient tout ce qu'une décision peut voir, figé à un instant :

| Attribut / méthode | Rôle |
|---|---|
| `ctx.signal_value`, `signal_status`, `signal_value_or_none`, `signal` | lire le snapshot |
| `ctx.top`, `bottom`, `where` | sélectionner des noms (`Selection`, qui garde la raison des exclus) |
| `ctx.market.value`, `values`, `history` | lire une série brute, avec statut et âge |
| `ctx.portfolio` | le livre : poids, quantités, coût moyen, cash investi |
| `ctx.universe` | les noms que l'univers autorise ce jour-là |
| `ctx.weights`, `equal_weight`, `cash`, `hold_positions`, `keep_and_buy` | exprimer la cible |

Les constructeurs de cible refusent un livre que personne ne pourrait
détenir : un poids négatif, une somme supérieure à 1, un nom hors de
l'univers ou un instrument non négociable.

## 8. Portefeuille et exécution

- `portfolio/` transforme une `TargetAllocation` en quantités admissibles :
  contraintes (`constraints`), limites (`limits`), lots de la place
  (`execution/rounding`).
- `execution/ExecutionModel` réunit un `CostModel`, où la commission (avec son
  minimum), le demi-spread et le slippage sont des termes séparés et nommés,
  une valeur minimale d'ordre et un mode de dimensionnement (`Sizing`).
- Un ordre non exécuté est un **rejet motivé** : `BELOW_MINIMUM_TRADE`,
  `INSUFFICIENT_CASH`, `NO_DECISION_PRICE` ou `CASH_SHARE_BUDGET`. Un rejet
  ne disparaît pas en silence : il est compté dans le rapport.

## 9. Résultat, analytics et identité d'un run

`StrategyResult` conserve tout : `records` (une entrée par séance),
`orders()`, `fills()`, `rejects()`, `holdings()`, `weights()`, `costs()`,
`equity(book)` et `drawdown(book)`.

- `report()` affiche **brut et net côte à côte**, les coûts décomposés, le
  turnover, le cash moyen, les séances sans prix, les achats coupés, et les
  hypothèses de fill.
- `compare()` confronte le run au benchmark déclaré du runner, valorisé
  pendant le run.
- `analytics.uncertainty.paired_block_bootstrap` rééchantillonne par blocs la
  **différence** entre une stratégie et un témoin exécutable, sous la même
  convention que le rapport.
- `run_id` hache toute la configuration : la stratégie, l'exécution, le
  calendrier, l'univers, l'empreinte du store (`data_state`), celle des
  calendriers et des instruments, l'environnement (Python, `uv.lock`,
  numpy, pandas, pyarrow, scipy) et l'état du code (commit, arbre propre ou
  non). Deux runs de même `run_id` ont produit les mêmes nombres.

## 10. La couche `research`

La couche `research/` porte la discipline de recherche décrite dans
[research/PROTOCOL.md](../research/PROTOCOL.md) :

| Élément | Rôle |
|---|---|
| `research/hypotheses.toml` | hypothèses écrites **avant** leurs runs (`PREREGISTERED`), ou nommées après coup (`EXPLORATORY`) |
| `research/registry.jsonl` + `ExperimentRegistry` | une ligne par run, jamais éditée, rejetés compris, uniquement depuis du code commité |
| `verdicts.jsonl` + `judge()` | les verdicts (`KEPT`, `REJECTED`), des événements ajoutés et jamais réécrits |
| `research.archive.keep()` / `read_back()` | un run conservé en entier, relisible hors ligne, avec copie vérifiée du store en option |
| `research/paper/` + `scripts/paper_trade.py` | le seul vrai test hors échantillon : des plans figés par un `contract_id`, joués séance après séance |

## 11. Mécanismes d'intégrité, en résumé

| Risque | Garde-fou |
|---|---|
| Lire le futur | reader figé à un instant, pas d'argument de date ; test « le futur ne change rien » par couche |
| Fenêtre trouée | `WindowSpec` + `windows.py`, statut `NON_CONSECUTIVE_HISTORY` |
| Donnée contestée | cross-check multi-sources, `CONFLICT` servi comme trou, revue commitée |
| Store à moitié écrit | transactions avec manifeste, verrou partagé ou exclusif |
| Résultat non reproductible | `run_id`, `fingerprint`, état git, environnement ; `uv.lock` commité |
| Stratégie qui triche | pas d'import de `data` (test), contexte sans reader, définition figée |
| Chiffre flatteur | brut et net, témoin exécutable, bootstrap apparié, registre des variantes |
| Régression silencieuse | tests hors ligne, warnings = erreurs, CI à chaque push, `ruff` + `pyright` |

## 12. Où ajouter quoi

| Je veux… | Où | Remarque |
|---|---|---|
| une nouvelle règle d'investissement | `strategies/` (ou un script / notebook avec `@strategy`) | voir le guide |
| une transformation réutilisable d'un prix | `signals/price/`, `signals/risk/`… | dataclass gelé, `compute_window`, tests avec garde anti look-ahead |
| un nouveau fournisseur | `data/sources/` | normaliser toutes ses particularités dans l'adaptateur |
| un nouvel instrument | `market_data/metadata/instruments.toml` | `history_basis` et `history_note` obligatoires |
| un nouvel univers | `market_data/metadata/universes.toml` | membres datés |
| un autre modèle de coûts | `ExecutionModel` / `CostModel` passés au runner | jamais dans la stratégie |
| une nouvelle métrique | `analytics/` | brut et net, même convention que le rapport |
