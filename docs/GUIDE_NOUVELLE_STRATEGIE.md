# Guide du développeur : écrire une nouvelle stratégie

Ce guide suit un exemple complet : **détenir un fonds quand sa moyenne mobile
50 jours est au-dessus de sa moyenne mobile 20 jours**. L'architecture est
décrite dans [ARCHITECTURE.md](ARCHITECTURE.md) et les règles de
développement dans [CLAUDE.md](../CLAUDE.md).

> **Attention au sens de la règle.** La MM50 au-dessus de la MM20 signifie
> que les prix récents sont passés **sous** leur tendance lente : c'est une
> règle qui achète la baisse. Le « golden cross » classique est l'inverse,
> la MM20 au-dessus de la MM50. Les deux s'écrivent avec le même code en
> inversant les paramètres, et le registre les compte comme deux variantes.

## Premier run, sans données réelles

Avant de télécharger quoi que ce soit, on peut lancer un vrai backtest sur un
marché inventé :

```bash
uv run python scripts/demo.py --figures demo_output
```

`quant_backtester.demo` tire deux fonds fictifs, `FUND_A` et `FUND_B`, d'une
graine fixe (la même graine donne les mêmes prix au bit près). Il les écrit
dans un store temporaire sur un calendrier `DEMO`, qui recopie les fériés
Euronext de 2024-2025, puis construit un `StrategyRunner` dont toutes les
hypothèses sont déclarées : coûts, lots entiers, 10 000 EUR, benchmark
`FUND_A`. Le lecteur, le moteur, l'exécution et le rapport sont ceux du projet.
Seuls les prix sont faux. On peut y essayer une stratégie en cours d'écriture :

```python
from pathlib import Path

from quant_backtester.demo import demo_runner
from quant_backtester.strategies import MovingAverageCross

runner = demo_runner(Path("demo_store"), seed=20240101)  # un dossier neuf et vide
result = runner.run(
    MovingAverageCross(instrument_id="FUND_A", first_sessions=20, second_sessions=50),
    ("FUND_A", "FUND_B"),
    "2025-01-02",
    "2025-12-31",
)
print(result.report().render())
```

2024 sert de warm-up aux signaux, et 2025 est la période mesurée. Un chiffre
obtenu sur la démo ne dit rien d'une règle. Il montre comment le moteur
fonctionne, rien de plus.

## 0. Avant d'écrire du code : l'hypothèse

Écrivez l'hypothèse dans `research/hypotheses.toml` **avant le premier run**,
et commitez-la :

```toml
[[hypothesis]]
hypothesis_id = "ma50_over_ma20_world"
status = "PREREGISTERED"
written_on = 2026-09-27
statement = "Holding ETF_WORLD only while its 50-session average is above its 20-session one beats holding it."
universe = "ROTATION_2"
prediction = "Higher net Sharpe than buy and hold of ETF_WORLD, at x1 and x2 costs, for 40/50/60 x 15/20/25."
refutation = "Paired Sharpe interval against the control includes or is below zero, or the edge exists at one parameter point only."
```

Un run qui n'est pas rattaché à une hypothèse écrite à l'avance ne teste rien
(voir [research/PROTOCOL.md](../research/PROTOCOL.md)). L'historique 2018-2026
de `ROTATION_2` a déjà été regardé : il ne constitue plus un échantillon de
test.

## 1. Séparer le signal de la décision

- **Signal** : la transformation réutilisable, ici `MA_a / MA_b − 1`.
- **Décision** : ce qu'on en fait, ici « investi si > 0, sinon cash ».

Cherchez d'abord un signal existant dans `signals/` (voir la liste dans
ARCHITECTURE.md §6). Le croisement de deux moyennes existe :
`MovingAverageCrossSignal` dans `signals/price/trend.py`. Si rien ne convient,
écrivez le vôtre en suivant la section 2.

N'utilisez pas `ctx.market.history(...)` pour recalculer une moyenne dans la
stratégie. `ctx.market` sert à lire une valeur ponctuelle, par exemple « le
VIX est-il au-dessus de 30 ». Une transformation réutilisable doit être un
signal : elle est ainsi testée, elle a une empreinte, et le contrat de fenêtre
est vérifié.

## 2. Écrire un signal (anatomie de `MovingAverageCrossSignal`)

```python
@dataclass(frozen=True, slots=True)
class MovingAverageCrossSignal(Signal):
    signal_id: str
    first_sessions: int
    second_sessions: int
    price_basis: PriceBasis
    bar_field: BarField = BarField.CLOSE
    max_age_sessions: int = 1

    def __post_init__(self) -> None:          # refuser une configuration absurde
        ...

    def definition(self) -> Mapping[str, object]:
        return {"type": "MovingAverageCrossSignal", "first_sessions": ..., ...}

    def compute(self, context, instrument_ids) -> SignalResult:
        return self.compute_window(
            context, instrument_ids,
            spec=WindowSpec(max(self.first_sessions, self.second_sessions)),
            bar_field=self.bar_field,
            basis=self.price_basis,
            max_age_sessions=self.max_age_sessions,
            formula=self._ratio_of_averages,
        )

    def _ratio_of_averages(self, window: LoadedWindow) -> float | None:
        first = _average_of_last(window.points, self.first_sessions)
        second = _average_of_last(window.points, self.second_sessions)
        if second <= 0:
            return None                          # -> INVALID_INPUT
        return first / second - 1.0
```

Les règles à respecter :

- **Dataclass gelé**, et tous les paramètres qui changent le nombre figurent
  dans `definition()`. Un identifiant qui garde son nom doit garder son sens.
- **`WindowSpec(n)` compte des prix**, pas des rendements : 20 rendements
  demandent 21 observations. Le mode par défaut, `CONSECUTIVE_SESSIONS`,
  refuse une fenêtre trouée. Une série publiée (un taux, un indice
  macroéconomique) demande `AVAILABLE_OBSERVATIONS`.
- **Passez par `compute_window`.** Il gère tous les statuts (`NOT_LISTED`,
  `STALE_INPUT`, `INSUFFICIENT_HISTORY`, etc.). La formule ne décide qu'une
  chose : renvoyer `None` quand ces nombres-là la rendent indéfinie.
- **Choisissez la base de prix explicitement.** `ADJUSTED` convient ici, car
  un dividende tombé dans la fenêtre longue ferait sinon passer la MM courte
  sous la longue sans aucune tendance. `RAW` convient pour un niveau coté.
- Aucun forward-fill, aucune interpolation, aucune normalisation sur tout
  l'échantillon.
- Exportez le signal dans `signals/__init__.py`.
- **Un modèle estimé dans la décision** (`signals/models/garch.py` en est
  l'exemple) reste une fonction pure de sa configuration et de sa fenêtre :
  aucun modèle gardé dans l'objet, aucun point de départ repris d'un appel
  précédent, aucun fichier écrit dans `compute()`. Une dépendance optionnelle
  s'importe au moment du calcul, pas en tête de module, pour que le catalogue
  et les autres stratégies s'importent sans elle ; son absence arrête le
  lancement (`validate()`), elle ne devient jamais un statut ni un repli. Un
  échec numérique sur des données valides a un repli **déclaré** et tracé ;
  des données invalides n'en ont pas.

### Tester le signal (`tests/signals/price/test_trend.py`)

Le marché synthétique de `tests/conftest.py` monte de 1 par séance : `ETF_EU`
vaut 100 à 109 sur dix séances de septembre 2026. Tout se vérifie à la main.
Les tests minimums :

| Test | Exemple |
|---|---|
| Valeur calculable à la main | MM2 = 108,5 ; MM5 = 107 → `108.5/107 − 1` |
| Comparaison avec une boucle naïve | chaque moyenne recalculée en boucle |
| Cas limite | `ETF_LATE` (4 séances) → `INSUFFICIENT_HISTORY` |
| Trou dans la fenêtre | barre contestée → `NON_CONSECUTIVE_HISTORY` |
| **Garde anti look-ahead** | ajouter un prix *après* la décision ne change pas le résultat (`frame.equals`) |
| Configuration refusée | longueur < 2, longueurs égales → `ValueError` |

## 3. Écrire la stratégie

### Forme rapide (essai, notebook) : `@strategy`

```python
from quant_backtester.signals import MovingAverageCrossSignal, PriceBasis
from quant_backtester.signals.types import SignalStatus
from quant_backtester.strategies import strategy

ma = MovingAverageCrossSignal(
    signal_id="ma50_over_ma20",
    first_sessions=50,
    second_sessions=20,
    price_basis=PriceBasis.ADJUSTED,
)


@strategy(strategy_id="ma_cross_try", signals=[ma], instrument_id="ETF_WORLD")
def ma_cross(ctx):
    if ctx.signal_status("ma50_over_ma20", "ETF_WORLD") is not SignalStatus.OK:
        return ctx.cash()
    if ctx.signal_value("ma50_over_ma20", "ETF_WORLD") <= 0.0:
        return ctx.cash()
    return ctx.weights({"ETF_WORLD": 1.0})
```

Déclarez en `**paramètres` du décorateur toute valeur capturée par la fonction
(seuil, instrument) : sinon elle n'entre pas dans l'empreinte du run.

### Forme conservée : une classe

La version conservée est `strategies/examples/moving_average_cross.py` :

```python
@dataclass(frozen=True, slots=True)
class MovingAverageCross(Strategy):
    instrument_id: str
    first_sessions: int = 50
    second_sessions: int = 20
    strategy_id: str = "moving_average_cross"

    def required_signals(self):
        return (self.signal(),)  # MovingAverageCrossSignal, ADJUSTED

    def decide(self, ctx):
        status = ctx.signal_status(self.signal_id, self.instrument_id)
        among = ctx.considering({self.instrument_id: status})
        if status is not SignalStatus.OK:
            return ctx.cash(among=among)
        if ctx.signal_value(self.signal_id, self.instrument_id) <= 0.0:
            return ctx.cash(among=among)
        return ctx.weights({self.instrument_id: 1.0}, among=among)
```

Les règles de la décision :

- **Un signal inutilisable est un cas à trancher explicitement.** `ctx.cash()`
  sort du marché ; `ctx.hold_positions()` garde les positions sans passer
  d'ordre. Ce sont deux stratégies différentes : écrivez le choix dans la
  docstring.
- **Enregistrez ce que la décision a lu.** `ctx.considering({fonds: statut})`
  construit la sélection à passer en `among` : un signal valide compte un
  instrument considéré, quelle que soit la réponse ; un signal inutilisable
  n'en compte aucun et garde son statut. Sans cela, « la règle a dit non » et
  « la règle n'avait rien à lire » donnent le même enregistrement.
- **Aucun état mutable.** Ce qui dépend du passé vient du contexte
  (`ctx.portfolio`), jamais d'un attribut ou d'une closure qu'on incrémente.
- **Aucun import de `quant_backtester.data`**, aucune date « du jour », aucune
  lecture de fichier. Un test fait échouer le build sinon.
- Les poids sont des fractions de capital dans [0, 1], de somme ≤ 1, pour des
  noms de `ctx.universe` négociables. Le reste est du cash.
- Exportez la classe dans `strategies/examples/__init__.py` et
  `strategies/__init__.py`, et ajoutez-la au test « chaque stratégie exportée
  est exécutable ».

### Tester la stratégie (`tests/strategies/test_examples.py`)

Le helper `decide_with(strategy, context, make_decision, universe)` calcule les
signaux déclarés puis appelle `decide`. Testez ce que la règle **décide** :
investie sur une série montante (2 sur 5), en cash quand les moyennes sont
inversées, en cash quand l'historique manque, identifiant du signal déclaré,
configuration refusée. Vérifiez aussi que la forme `@strategy` décide comme la
classe.

## 4. Lancer un backtest

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path("scripts").resolve()))
from run_baselines import runner  # le même store, coûts, cash et benchmark que les suites

from quant_backtester.backtest.schedule import EverySession
from quant_backtester.strategies import MovingAverageCross

runs = runner()
result = runs.run(
    MovingAverageCross(instrument_id="ETF_WORLD", first_sessions=50, second_sessions=20),
    "ROTATION_2",
    "2025-01-02",
    "2026-09-17",
    schedule=EverySession(),
)
print(result.run_id)
print(result.report().render())  # brut / net, coûts, turnover, cash moyen, hypothèses
print(result.compare().render())  # contre ETF_WORLD
print(result.rejects())  # ordres refusés, avec leur raison
```

Lancez-le avec `uv run python mon_essai.py`, store local rempli
(`scripts/update_market_data.py`).

- **Schedules** : `EverySession()`, `EveryNSessions(n)`, `Weekly()`,
  `Monthly()`.
- **Warm-up** : les données avant `start` restent lisibles par les signaux.
  Une MM50 est donc calculable dès la première séance mesurée si l'historique
  existe.
- **Coûts** : `dataclasses.replace(runs, execution=...)` pour un autre
  `ExecutionModel` (voir `scripts/sensitivity.py` pour les coûts ×2).
- **Lire le rapport** : « sessions with nothing to choose from » compte les
  décisions où aucun signal n'était lisible. Une séance passée en cash sur un
  signal valide n'y figure pas, à condition que la stratégie passe `among`
  comme ci-dessus.

## 5. Juger une variante honnêtement

1. **Commitez** le code, puis enregistrez chaque run :
   `ExperimentRegistry(...).register(record_of(result, experiment_id=..., hypothesis="ma50_over_ma20_world", recorded_at=...))`.
   Le registre refuse du code non commité. `run_baselines.py --register`
   montre le câblage.
2. **Comparez à un témoin exécutable**, par exemple
   `BuyAndHold(instruments=("ETF_WORLD",))` sous les mêmes coûts, sur les mêmes
   séances, avec `paired_block_bootstrap(result.equity(), control.equity(),
   statistic=PairedStatistic.SHARPE, block=10, draws=2000, seed=..., level=0.90,
   config=ANALYTICS)`. Si l'intervalle contient zéro, il n'y a pas de
   conclusion.
3. **Raisonnez en voisinages** : 40/50/60 × 15/20/25, plusieurs dates de
   départ, coûts ×1 et ×2. Un résultat qui n'existe qu'en un point est du
   bruit. Chaque point est un run enregistré.
4. **Rendez un verdict** : `registry.judge(experiment_id, Verdict.KEPT |
   Verdict.REJECTED, note, decided_at)`. Les rejets restent comptés.
5. **Conservez les runs cités** : `research.archive.keep(result, dossier,
   store=...)`.
6. Une règle retenue ne se prouve que **hors échantillon** : un plan de paper
   trading dans `research/paper/`, figé par son `contract_id`.

## 6. Check-list avant commit

```bash
set -o pipefail
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest
```

- [ ] Hypothèse écrite et commitée avant le premier run.
- [ ] Signal : dataclass gelé, `definition()` complète, `WindowSpec` correcte,
      base de prix explicite, docstring numpy (unités, disponibilité).
- [ ] Tests du signal : valeur à la main, cas limite, trou, **look-ahead**,
      configuration refusée.
- [ ] Stratégie : aucun import de `data`, aucun état, cas « signal
      inutilisable » tranché et documenté.
- [ ] Tests de la stratégie, et test d'export mis à jour.
- [ ] Aucun paramètre caché : tout est un champ ou un paramètre déclaré.
- [ ] ruff, format, pyright et pytest propres (les warnings sont des erreurs).
