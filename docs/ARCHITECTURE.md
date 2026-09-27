# Architecture

État au 2026-09-27. Ce document décrit comment le projet est découpé, comment
une séance de backtest se déroule et quels mécanismes garantissent qu'un
résultat est juste et reproductible. Les règles de développement sont dans
[CLAUDE.md](../CLAUDE.md).

| Document | Pour |
|---|---|
| [GUIDE_NOUVELLE_STRATEGIE.md](GUIDE_NOUVELLE_STRATEGIE.md) | lancer un premier run hors ligne, écrire un signal et une stratégie, les juger |
| [DONNEES.md](DONNEES.md) | la couche `data` en détail ; ajouter un instrument ou une source |
| [FORMULES.md](FORMULES.md) | chaque formule du code : signaux, coûts, portefeuille, métriques |
| [OPERATIONS_SUR_TITRES.md](OPERATIONS_SUR_TITRES.md) | splits, dividendes, scissions : ce qui est géré et ce qui ne l'est pas |
| [GLOSSAIRE.md](GLOSSAIRE.md) | les termes de finance, en français et en anglais |
| [AMELIORATIONS.md](AMELIORATIONS.md) | ce qui reste à faire |

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
    portfolio/   cible demandée  ->  cible admissible (poids, limites), état du livre
      │
    execution/   cible admissible  ->  quantités sur les lots, ordres, fills, rejets, coûts
      │
    backtest/    la boucle qui fait avancer le temps, le contexte de décision, le runner
      │
    analytics/   performance brute/nette, benchmark, attribution, incertitude
      │
    strategies/  des règles composées à partir des couches ci-dessus
      │
    research/    hypothèses, registre des expériences, archives de runs, paper trading
```

Les dépendances vont **dans un seul sens** : un module peut importer une couche
placée au-dessus de la sienne dans ce schéma, jamais une couche placée
en dessous. Si une couche a besoin d'une information qui vient d'en dessous, on
la lui passe en argument. `tests/test_package_structure.py` vérifie cette règle
sur chaque module.

**Une exception, et une seule : `backtest/runner.py`.** C'est une façade de
composition. Elle construit le moteur, exécute une stratégie et rend son
rapport. Elle importe donc `strategies.base` (le contrat d'une stratégie) et
`analytics` (le rapport, les courbes, les graphiques). Le test la déclare dans
`COMPOSITION_FACADES`, et aucun autre module ne peut faire de même. Le reste de
`backtest/`, en particulier `engine.py` et `context.py`, respecte la règle. Les
stratégies importent `backtest/context.py`, placé au-dessus d'elles : c'est un
import autorisé.

Trois règles supplémentaires sont vérifiées par les mêmes tests :

- `strategies/` et `analytics/` n'importent jamais `quant_backtester.data`.
  Une stratégie ne peut donc pas ouvrir un reader et lire au-delà de son
  instant.
- Aucune couche n'importe `research/`.
- Seul `data/` fait des entrées-sorties réseau.

| Paquet | Rôle | Modules clés |
|---|---|---|
| `data/` | Ingestion, contrôle, stockage et lecture des séries de marché | `sources/`, `schemas`, `normalizer`, `validator`, `crosscheck`, `revisions`, `bar_corrections`, `corporate_actions`, `known_gaps`, `conflict_reviews`, `repository`, `updater`, `reader`, `calendars`, `instruments`, `universes` |
| `signals/` | Transformations réutilisables d'un historique en un nombre | `base` (`Signal`, `SignalResult`), `windows`, `types`, `engine`, `snapshot`, `price/`, `risk/`, `level/`, `cross_sectional/` |
| `portfolio/` | Ce qu'un livre a le droit de détenir, et ce qu'il détient | `targets` (`TargetAllocation`), `allocation` (`PortfolioModel`, `ConstrainedTarget`), `constraints`, `limits` (`PortfolioLimits`), `holdings`, `state` (`PortfolioState`), `view` |
| `execution/` | Ce que le marché fait d'un ordre | `model` (`ExecutionModel`, `Sizing`), `costs` (`CostModel`), `rounding` (lots), `orders`, `fills` (`Fill`, `ExecutionReject`) |
| `backtest/` | Le temps | `config` (`BacktestConfig`), `engine`, `timetable`, `schedule`, `context` (`StrategyContext`), `market`, `records` (`BacktestRecord`), `result` (`BacktestResult`), `runner` (`StrategyRunner`, `StrategyResult`) |
| `analytics/` | Ce qu'un run a produit | `config` (`AnalyticsConfig`), `curves`, `performance`, `report`, `comparison`, `attribution`, `contribution`, `uncertainty`, `plots` |
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
- **Contrôle des opérations sur titres, avant l'ouverture.** Si une position
  détenue passe ex-date sur une opération (split, dividende…) depuis la
  séance précédente, le run s'arrête avec `UnsupportedCorporateAction`. Il
  s'arrête même si la stratégie allait vendre à cette ouverture, parce que la
  vente aurait lieu après l'événement. Voir
  [OPERATIONS_SUR_TITRES.md](OPERATIONS_SUR_TITRES.md).
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
      0. contrôle     position détenue qui passe ex-date -> UnsupportedCorporateAction
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

Le détail est dans [DONNEES.md](DONNEES.md).

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

Pièges du contexte : `signal_value` lève `UnusableSignal` si le statut n'est
pas `OK`, alors que `signal_value_or_none` renvoie `None`. `keep_and_buy`
répartit une fraction du **cash restant** entre des lignes nouvelles : ce n'est
pas un poids du portefeuille, et il refuse une ligne déjà détenue.
`hold_positions` n'envoie aucun ordre, sauf si une limite coupe le livre.
`@strategy` enregistre le nom qualifié de la fonction, pas son code : seul l'état
git trace une modification de son corps.

### Les stratégies livrées (`strategies/examples/`)

| Classe | Règle exacte | Si le signal est inutilisable |
|---|---|---|
| `BuyAndHold(instruments)` | achète à parts égales puis garde les quantités ; les poids dérivent. Un nom dont l'achat a échoué est acheté plus tard avec le cash restant, sans revendre les lignes déjà détenues (D5) | pas de signal |
| `EqualWeightRebalance(instruments)` | poids égaux redemandés à chaque décision, donc vend le gagnant et rachète le perdant | pas de signal |
| `MomentumRotation(lookback_sessions=60, top_n=2)` | classe le momentum ajusté et détient les `top_n` premiers à `1/top_n` chacun. Il ne demande **pas** un momentum positif : le moins mauvais peut être retenu. Un rang incomplet laisse du cash | nom exclu du classement |
| `MomentumSingleAsset(instrument_id, lookback_sessions=60, minimum=0.0)` | investi si le momentum ajusté est strictement supérieur à `minimum` | cash |
| `MomentumVix(gauge_id, …, maximum, flat_when_unknown)` | rotation tant que le z-score de la jauge est ≤ `maximum`. Un z-score de 1,5 veut dire 1,5 écart-type au-dessus de sa moyenne récente, pas un VIX à 1,5 | cash si `flat_when_unknown`, sinon rotation (paramètre obligatoire) |
| `MovingAverageCross(instrument_id, first_sessions=50, second_sessions=20)` | investi si `MA_first / MA_second − 1 > 0`. Avec 50/20, la règle **achète la baisse** ; le « golden cross » s'écrit 20/50 | cash |

Les scripts de référence passent `top_n=1` sur l'univers à deux fonds. Avec la
valeur par défaut `top_n=2`, la rotation détiendrait les deux.

## 8. Portefeuille et exécution

Il faut distinguer quatre objets :

| Objet | Ce qu'il décrit | Produit par |
|---|---|---|
| `TargetAllocation` | ce que la stratégie **demande** (des poids) | `strategy.decide(ctx)` |
| `ConstrainedTarget` (dans `PortfolioDecision`) | ce que les limites **autorisent** (des poids), avec chaque coupe nommée | `PortfolioModel.decide` |
| `Order` / `Fill` / `ExecutionReject` | ce qui est **demandé au marché** et ce qui en est **fait** (des quantités) | `ExecutionModel.rebalance` |
| `PortfolioState` | ce que le livre **détient** (quantités, coût moyen, cash) | les fills appliqués |

- `portfolio/` travaille en **poids**. `PortfolioModel.decide` refuse une cible
  inadmissible : un instrument inconnu, non négociable, dans une autre devise
  ou hors de l'univers du jour lève `InadmissibleTarget`. Il n'y a pas de
  coupe silencieuse. `PortfolioLimits` plafonne ensuite chaque ligne, puis
  réduit les poids proportionnellement si l'exposition brute dépasse son
  plafond. Les poids retirés restent en cash et ne sont pas redistribués. Ces
  plafonds s'appliquent à la cible **avant coûts et arrondis**.
- `execution/` passe des poids aux **quantités**. Les quantités sont arrondies
  vers zéro au lot de l'instrument (`rounding`). Les ventes passent avant les
  achats, et un achat que le cash ne couvre pas est réduit.
  `ExecutionModel` réunit un `CostModel`, dont la commission (avec son
  minimum), le demi-spread et le slippage sont des termes séparés et nommés,
  une valeur minimale d'ordre et un mode de dimensionnement (`Sizing`). Les
  équations sont dans [FORMULES.md](FORMULES.md).
- Un ordre non exécuté est un **rejet motivé**. Il ne disparaît pas en
  silence : il est compté dans le rapport. Une cible exécutée une fois n'est
  jamais remise en file. Si un achat est rejeté, c'est à la décision suivante
  de le redemander.

| `ExecutionRejectReason` | Sens |
|---|---|
| `NON_TRADABLE` | instrument déclaré `tradable = false` (dernier garde-fou ; `portfolio` le refuse avant) |
| `CURRENCY_MISMATCH` | instrument coté dans une autre devise que le livre (même rôle) |
| `NO_EXECUTION_PRICE` | aucun prix d'ouverture à l'instant d'exécution |
| `STALE_EXECUTION_PRICE` | le dernier prix d'ouverture date d'une séance antérieure |
| `NO_DECISION_PRICE` | `Sizing.AT_DECISION` sans clôture à la décision pour fixer la quantité |
| `BELOW_MINIMUM_TRADE` | ordre inférieur à la valeur minimale déclarée |
| `INSUFFICIENT_CASH` | achat réduit ou refusé faute de cash, coûts compris |
| `CASH_SHARE_BUDGET` | achat `keep_and_buy` ramené à sa part de cash, au prix réellement payé |
| `INVALID_QUANTITY` | position détenue hors de la grille des lots (livre construit hors du moteur) |
| `OUTSIDE_TRADING_UNIVERSE` | achat d'un nom sorti de l'univers entre la décision et l'ouverture ; une vente n'est jamais refusée pour ce motif |

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
| un nouveau fournisseur | `data/sources/` + un normaliseur qui finit par `bars_frame` | normaliser toutes ses particularités dans l'adaptateur ; voir [DONNEES.md](DONNEES.md) §11 |
| un nouvel instrument | `market_data/metadata/instruments.toml` | `history_basis` et `history_note` obligatoires ; voir [DONNEES.md](DONNEES.md) §10 |
| un nouvel univers | `market_data/metadata/universes.toml` | membres datés |
| un autre modèle de coûts | `ExecutionModel` / `CostModel` passés au runner | jamais dans la stratégie |
| une nouvelle métrique | `analytics/` | brut et net, même convention que le rapport |

## 13. Scripts et environnement

| Script | Rôle | Réseau |
|---|---|---|
| `scripts/demo.py` | premier backtest sur un marché synthétique (`quant_backtester.demo`), rapports et figures | non |
| `scripts/update_market_data.py` | télécharger, contrôler et promouvoir (`--archive`, `--coverage`, `--only`, `--rebuild`) | oui, sauf `--coverage` et `--rebuild` |
| `scripts/accept_revision.py` | préparer le bloc TOML d'une révision à relire ; ne modifie aucun fichier | non |
| `scripts/generate_calendars.py` | régénérer les calendriers depuis `exchange_calendars` et les vérifier | non |
| `scripts/check_calendar_coverage.py` | échouer quand il reste moins de 90 jours de calendrier | non |
| `scripts/run_baselines.py` | suites nommées (`--suite readme|baselines|all`, `--period`, `--records`, `--keep`, `--register`) | non |
| `scripts/sensitivity.py` | la référence sous `AT_AUCTION` / `AT_DECISION`, avec coûts ×1 et ×2 | non |
| `scripts/paper_trade.py` | vérifier et prolonger les plans de paper trading | non |

**Référence d'API.** Chaque module, classe et fonction publique a une docstring
numpy qui donne les unités, le fuseau et l'instant de disponibilité. On la lit
avec `pydoc`, sans dépendance supplémentaire et toujours à jour du code :

```bash
uv run python -m pydoc quant_backtester.backtest.runner   # un module dans le terminal
uv run python -m pydoc -b                                  # tout le paquet dans le navigateur
```

Une référence recopiée à la main, avec des numéros de ligne, serait fausse dès
le commit suivant.

Un script ne contient pas de calcul métier. Il charge la configuration, vérifie
les préconditions, appelle le paquet et écrit dans un dossier neuf.

**Environnement.** Python 3.12 exactement (`requires-python = ">=3.12,<3.13"`),
et `uv` avec `uv.lock` commité. Les verrous du store et des journaux utilisent
`fcntl`/`flock`, qui offre le mode partagé dont un run a besoin : **Linux, macOS
ou WSL, pas Windows natif** (décision D11). L'import du store y échoue avec un
message qui le dit. `numbers.py` refuse un `bool` là où l'on attend un nombre, car
en Python `True` est un `int` et passerait sinon pour un taux ou une durée.

**Annualisation.** Les rapports déclarent `AnalyticsConfig(sessions_per_year=255,
risk_free_rate=0.02)` pour XPAR. `RealizedVolatilitySignal.annualization` n'a pas
de valeur par défaut : on la déclare, 252 pour XNYS ou 255 pour XPAR.

Les dossiers de la couche `data` sont sous `market_data/` : `metadata/` est
commité, `raw/`, `clean/` et `validation/` ne le sont pas.
