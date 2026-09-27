# Formules

État au 2026-09-27. Chaque formule est celle du code, avec le fichier qui la
calcule. Les définitions financières sont dans le [glossaire](GLOSSAIRE.md),
l'architecture dans [ARCHITECTURE.md](ARCHITECTURE.md).

Conventions : un rendement de `0.05` vaut 5 %. Un point de base (pb) vaut 10⁻⁴.
Une fenêtre `P_0, …, P_L` est ordonnée du plus ancien au plus récent : elle
contient `L + 1` prix, donc `L` rendements. Les historiques ne sont lus qu'après
validation de la fenêtre par `signals/windows.py` (voir ARCHITECTURE §6). Une
formule qui renvoie `None` produit le statut `INVALID_INPUT`, jamais un nombre.

## 1. Signaux

Pour les signaux de prix, `PriceBasis.RAW` lit les cotations et
`PriceBasis.ADJUSTED` les clôtures ajustées des OST connues à l'instant de
décision (voir [OPERATIONS_SUR_TITRES.md](OPERATIONS_SUR_TITRES.md)).

| Signal | Fenêtre | Formule | Refus |
|---|---|---|---|
| `ReturnSignal` (`price/returns.py`) | `L + 1` séances | `R = P_L / P_0 − 1` | `P_0 ≤ 0` |
| `MomentumSignal` (`price/momentum.py`) | `L + 1` séances, `L = lookback_sessions` | `M = P_{L−k} / P_0 − 1`, `k = skip_recent_sessions`, `0 ≤ k < L` | `P_0 ≤ 0` |
| `MeanReversionSignal` (`price/mean_reversion.py`) | `L + 1` séances | `−(P_L / P_0 − 1)` | `P_0 ≤ 0` |
| `MovingAverageTrendSignal` (`price/trend.py`) | `n` séances | `P_L / mean(P_{L−n+1..L}) − 1` | moyenne ≤ 0 |
| `MovingAverageCrossSignal` (`price/trend.py`) | `max(a, b)` séances | `MA_a / MA_b − 1`, chaque `MA` sur les derniers prix de la même fenêtre | `MA_b ≤ 0`, `a = b`, `a < 2` ou `b < 2` |
| `RealizedVolatilitySignal` (`risk/volatility.py`) | `n + 1` séances, `n = window_returns` | `σ = sqrt(A) · sqrt( Σ (r_i − r̄)² / (n − d) )` | un prix ≤ 0, `n ≤ d` |
| `CurrentDrawdownSignal` (`risk/drawdown.py`) | `n` séances | `P_L / max(P_{L−n+1..L}) − 1 ≤ 0` | max ≤ 0 |
| `LevelChangeSignal` (`level/change.py`) | `L + 1` observations | `x_L − x_0`, dans l'unité de la série | — |
| `LevelZScoreSignal` (`level/zscore.py`) | `n` observations | `(x_{n−1} − x̄) / s`, `s` avec `ddof = 1` | `s = 0` |
| `CrossSectionalRank` (`cross_sectional/rank.py`) | le signal source | `(ρ_i − 1) / (m − 1)` | `m < minimum` → `INSUFFICIENT_CROSS_SECTION` |

Précisions :

- **Momentum avec skip.** Le point de départ reste `P_0`. Sauter les `k` dernières
  séances **raccourcit** la période mesurée à `L − k` rendements : la fenêtre ne
  se décale pas vers le passé. Pour `k = 0`, le momentum est le rendement.
- **Moyennes mobiles.** `MovingAverageCross(first_sessions=50, second_sessions=20)`
  donne un score positif quand la moyenne 50 est **au-dessus** de la moyenne 20 :
  c'est une règle qui achète la baisse. Le « golden cross » s'écrit
  `first_sessions=20, second_sessions=50`.
- **Volatilité.** Par défaut, les rendements sont logarithmiques
  (`r_i = log(P_i / P_{i−1})`), `d = ddof = 1` et `A = annualization`. `A` n'a
  **pas de valeur par défaut** : on la déclare comme les autres paramètres de
  recherche, 252 pour XNYS ou 255 pour XPAR. Multiplier par `sqrt(A)` suppose des
  rendements non corrélés et de variance comparable. C'est une convention, pas
  une propriété des données.
- **Z-score.** La dernière observation fait partie de la moyenne et de l'écart-type.
  Une fenêtre constante est refusée.
- **Rang.** `ρ_i` est le rang moyen en cas d'égalité, et `m` le nombre
  d'instruments dont le score est utilisable. Par défaut (`ascending=False`), le
  plus grand score reçoit 1 et le plus petit 0. Un instrument sans score garde son
  statut et ne reçoit jamais 0. Un rang n'est pas un écart économique : être
  premier sur deux n'est pas une conviction de 100 %.

Exemple à la main (`tests/signals/price/test_trend.py`) : pour 100, 101, …, 109,
`MA_2 = 108,5`, `MA_5 = 107`, et le cross vaut `108,5 / 107 − 1 = 1,40 %`.

## 2. Portefeuille

Avec `C` le cash, `q_i` les quantités et `P_i` les prix de valorisation
(`portfolio/state.py`) :

```
V   = C + Σ q_i · P_i
w_i = q_i · P_i / V                    (V > 0 exigé)
```

Une cible est admissible si `0 ≤ w_i ≤ 1` et `Σ w_i ≤ 1 + 10⁻⁹`.
`PortfolioLimits` plafonne d'abord chaque ligne, puis multiplie tous les poids par
`plafond_brut / Σ w_i` si leur somme dépasse le plafond brut. Ce qui est retiré
reste en cash.

**Coût moyen** (`portfolio/holdings.py`). `K` est le prix payé par unité, coûts
compris :

```
achat de Δq au prix K :   P̄' = (q · P̄ + Δq · K) / (q + Δq)
vente de Δq          :   P̄' = P̄
```

Ce n'est pas un calcul fiscal par lot.

## 3. Exécution

`P` est le prix de référence (l'ouverture), `q > 0` la quantité, `h` le
demi-spread, `s` le slippage, `c` le taux de commission et `m` son plancher
(`execution/costs.py`) :

```
prix payé        P_f = P · (1 + h + s)      achat
                 P_f = P · (1 − h − s)      vente
commission       F   = max(c · q · P_f, m)  (0 si q = 0)
cash             −(q · P_f + F)             achat
                 +(q · P_f − F)             vente
coût de spread   q · P · h
coût de slippage q · P · s
```

Spread et slippage sont **déjà dans `P_f`**. Le rapport les montre à part, mais il
ne faut pas les retirer une seconde fois.

Exemple : `P = 100`, `q = 10`, `h = 0,0002`, `s = 0,0001`, `c = 0,0005`, `m = 1`.
On paie `P_f = 100,03` et `F = max(0,50 ; 1) = 1`, soit un décaissement de
1 001,30. Les coûts sont de 0,20 de spread, 0,10 de slippage et 1 de commission.

**Lots** (`execution/rounding.py`). Une variation de position est **tronquée vers
zéro** au pas de l'instrument, avec une tolérance de 10⁻⁹ :
`floor(q / pas + 10⁻⁹) · pas`. Une vente de 4,5 lots en trop vend 4 lots, pas 5.

**Budget** (`execution/model.py`) :

- Les ventes passent avant les achats.
- Le cash dépensable avant commission est
  `max(0, min(C − m, C / (1 + c)))`.
- Si plusieurs achats dépassent ce cash, un facteur commun `λ ∈ [0, 1]` les
  réduit. Le cash nécessaire croît par paliers avec `λ` (lots, plancher de
  commission), donc `λ` est trouvé par **60 bissections**. Aucun achat n'est
  favorisé. La part coupée est un rejet `INSUFFICIENT_CASH`.
- Un achat `keep_and_buy` est ramené à sa part du cash, au prix réellement payé
  (`CASH_SHARE_BUDGET`). On retire un lot à la fois tant que le débit dépasse
  cette part.

## 4. Analyse

`V_0, …, V_T` sont les valeurs du livre aux séances `d_0, …, d_T`, et
`r_t = V_t / V_{t−1} − 1`. `A = sessions_per_year` et `R_f = risk_free_rate`
viennent de l'`AnalyticsConfig`. `Y = (d_T − d_0) / 365,25` est la durée en
années calendaires (`analytics/curves.py`, `performance.py`).

| Mesure | Formule | Défini si |
|---|---|---|
| Rendement total | `V_T / V_0 − 1` | toujours |
| Rendement annualisé | `(V_T / V_0)^(1/Y) − 1` | au moins `minimum_sessions` séances (60) et `Y > 0` |
| Volatilité annualisée | `std(r, ddof = 1) · sqrt(A)` | au moins 2 rendements |
| Sharpe | `mean(r − r_f) / std(r − r_f, ddof = 1) · sqrt(A)`, avec `r_f = (1 + R_f)^(1/A) − 1` | 60 séances, écart-type non nul |
| Drawdown | `D_t = V_t / max_{u ≤ t} V_u − 1` ; maximum = `min_t D_t` | toujours ; le **premier** creux minimal est retenu |
| Turnover | `Σ |q_j · P_f,j| / mean(V)`, achats et ventes comptés | `mean(V) > 0` |
| Turnover annuel | `turnover / Y` | `Y > 0` |
| Coût en rendement | `R_brut − R_net` | toujours |
| Part du brut absorbée | `(R_brut − R_net) / R_brut` | `R_brut > 0` |

- `r_f` est composé vers le bas, pas divisé par `A`. Le cash du livre ne
  rapporte **rien** : `R_f` ne sert qu'au Sharpe.
- Le livre **brut** rejoue les mêmes fills au prix de marché, sans frais. Ce n'est
  pas une autre stratégie qui aurait acheté plus faute de coûts. Avec les mêmes
  quantités, le coût en rendement vaut les coûts cumulés divisés par le capital
  initial.
- Tout vendre puis tout racheter donne un turnover d'environ 2.
- **Contribution par instrument** (`analytics/contribution.py`) : variation de la
  valeur détenue plus flux de cash de ses transactions. Le résidu non expliqué est
  montré, jamais réparti.
- Une métrique non définie est `None` et s'affiche « - ». Elle ne vaut jamais 0.

**Benchmark** (`backtest/runner.py`, `value_benchmark`) : une part détenue sans
coûts ni lots. La richesse est chaînée sur les séances du benchmark :

```
croissance d'une séance = (titres · C_t + cash reçu) / C_{t−1}
```

Un split multiplie le nombre de titres. Sous `TOTAL_RETURN`, un dividende est
versé sur chaque titre à la date ex et réinvesti à cette clôture.

**Bootstrap apparié** (`analytics/uncertainty.py`). Les rendements de la stratégie
et du témoin sont alignés sur les mêmes séances. Des blocs de `b` séances
consécutives sont tirés avec remise, **avec les mêmes indices pour les deux
séries**. La statistique est l'une des deux suivantes :

- `MEAN_RETURN` : `A · (r̄_a − r̄_b)`, une différence de moyennes annualisées, pas
  de taux composés ;
- `SHARPE` : `Sharpe_a − Sharpe_b`, avec le taux sans risque du rapport. Il ne
  s'annule pas en général, parce que chaque série a son propre écart-type.

L'intervalle est donné par les quantiles empiriques. Les conditions sont : au moins
2 rendements, `1 ≤ b ≤ T`, au moins 100 tirages, un niveau dans `(0, 1)` et une
graine explicite. Une statistique indéfinie dans un tirage lève
`UndefinedStatistic` : on ne jette pas les tirages qui dérangent. L'intervalle ne
protège pas contre le choix du meilleur de nombreux essais.

## 5. Données

**Écart entre deux sources** (`data/crosscheck.py`) :

```
δ(a, b) = |a − b| / max(|a|, |b|)      δ(0, 0) = 0
```

Deux valeurs manquantes donnent 0, une seule donne `∞`. Le comparateur de champs
ignore d'abord les valeurs manquantes : avec moins de deux valeurs finies, le
champ est **non confirmé**, ce qui n'est pas un accord. Un champ dont l'écart
dépasse sa tolérance (`metadata/crosscheck.toml`) est `CONFLICT`, et le lecteur ne
sert pas ce champ.

**Ajustement des OST** (`data/reader.py`, `adjusted_history`) : chaque prix
antérieur à la date ex `e` est multiplié par

```
1 / r               split de ratio r, ou scission de facteur r
1 − D / C_{e−1}     dividende D (ordinaire ou spécial), C_{e−1} = clôture brute qui précède
```

Les facteurs de plusieurs événements se multiplient. Un facteur ≤ 0 est refusé.
