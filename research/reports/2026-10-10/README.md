# Résultats et analyses du 10 octobre 2026

Un rapport par stratégie, écrit par `scripts/write_strategy_reports.py` à
partir des exports de `scripts/run_garch_study.py`, après mise à jour du
magasin jusqu'au 2026-10-09.

Chaque fichier `strategy<CODE>_ResultsAndAnalysis_10102026.md` a trois
sections : (1) les indicateurs de résultat globaux, à côté du fonds détenu ;
(2) l'analyse — périodes mesurées, baisses sous un sommet avec leur date de
récupération, années et mois, puis points forts, points faibles, pire et
meilleure période, situations de marché les plus risquées et ce qui reste à
mesurer ; (3) l'historique séance par séance du sous-jacent, des indicateurs
lus par la stratégie, de ses poids et de sa valeur.

**Version 2 des analyses.** Les commentaires ont été réécrits après une revue
indépendante faite sur le commit `4e04eae`
(`revue_analyses_strategies_resultats_10102026.md`). Les chiffres globaux
n'ont pas changé. Ont changé : les chronologies de positions (SA3, SA4, SA6,
SA9, SA10, SA11, ML1), les conclusions causales non démontrées, la
distinction entre fait mesuré et lecture, l'ajout de la récupération des
baisses, des mois sans variation, des périodes partielles, du contrôle 50/50,
des deux rapports de référence et d'un intervalle sur les écarts de QLIKE.

**Version 3 des analyses.** Une vérification indépendante faite sur le commit
`ad310bc` (`verification_resultats_corriges_10102026.md`) a retrouvé les
chiffres globaux et les historiques, et demandé de borner plusieurs lectures.
Les chiffres globaux n'ont pas changé. Ont changé : le résidu de l'attribution
de `SA2` et `SA5` n'est plus appelé « exécution » ; les témoins sont dits « à
cible constante » et la comparaison ne prétend plus isoler le timing ; l'écart
de prix clôture-ouverture est remesuré à quantités données et n'est plus
présenté comme un coût ; le séjour encore ouvert de `SA1` est compté à part ;
`ML1` est rejoué à coûts doublés avec son modèle figé ; les contradictions
relevées dans les textes de `SA2`, `SA3`, `SA4`, `SA9`, `SA10`, `SA11`, de
l'EWMA et de `ML1` sont corrigées.

## Comment lire

- Une décision est prise le soir de la séance t (signal et poids cible de la
  ligne t) et exécutée à l'ouverture de t + 1 ; elle n'apparaît dans le poids
  détenu qu'à la ligne t + 1.
- Dans les commentaires, **Fait** désigne ce qui est relu dans les exports,
  **Lecture** une interprétation plausible non démontrée, **Observé** et
  **Plausible** un risque vu dans ces historiques ou seulement attendu.
- Le cash n'est pas rémunéré et le taux sans risque est nul.
- 2021 commence le 1er avril et 2026 s'arrête au 9 octobre : ce sont des
  années partielles, et octobre 2026 un mois incomplet.

## Classement commun (exploratoire)

Période 2021-04-01 → 2026-10-09 (1 416 valorisations), 100 000 EUR, commission
5 pb (minimum 1 EUR), demi-spread 3 pb, slippage 2 pb, quantités fixées à la
décision. Score `QUALITY_V1` contre `ETF_WORLD` détenu, déflaté par 10 essais.

| Rang | Livre | Score | Net | Sharpe | Perte max. | Retour au sommet | Coûts (EUR) | Rapport |
|---:|---|---:|---:|---:|---:|---:|---:|---|
| 1 | 50/50 rebalancé (référence, hors catalogue) | 77,9 % | +103,3 % | 0,96 | -22,5 % | 232 j | 736 | [rapport](strategyREF_5050Rebalanced_ResultsAndAnalysis_10102026.md) |
| 2 | EWMA 0,94 (témoin de SA11, sans code) | 53,6 % | +73,4 % | 0,93 | -15,4 % | 321 j | 1 519 | [rapport](strategyEWMA94control_ResultsAndAnalysis_10102026.md) |
| 3 | SA6 - vol control | 52,0 % | +67,4 % | 0,90 | -15,7 % | 330 j | 1 445 | [rapport](strategySA6_ResultsAndAnalysis_10102026.md) |
| 4 | SA10 - ensemble, **sans facteurs ni monétaire** | 51,1 % | +32,1 % | 0,86 | -11,8 % | 442 j | 1 986 | [rapport](strategySA10_ResultsAndAnalysis_10102026.md) |
| 5 | SA3 - smooth MA | 49,0 % | +57,9 % | 0,79 | -21,6 % | 540 j | 680 | [rapport](strategySA3_ResultsAndAnalysis_10102026.md) |
| 6 | **SA11 - GARCH vol control** | 48,6 % | +66,0 % | 0,87 | -16,5 % | 324 j | 3 749 | [rapport](strategySA11_ResultsAndAnalysis_10102026.md) |
| 7 | SA2 - dual momentum | 44,1 % | +69,2 % | 0,78 | -22,8 % | 422 j | 4 629 | [rapport](strategySA2_ResultsAndAnalysis_10102026.md) |
| 8 | SA5 - relative tilt | 29,4 % | +72,8 % | 0,76 | -22,9 % | 252 j | 20 517 | [rapport](strategySA5_ResultsAndAnalysis_10102026.md) |
| 9 | SA1 - std MA20 | 0,0 % | +20,5 % | 0,42 | -18,9 % | 794 j | 15 730 | [rapport](strategySA1_ResultsAndAnalysis_10102026.md) |
| 9 | SA4 - pullback | 0,0 % | +4,4 % | 0,41 | -3,4 % | non récupéré | 4 572 | [rapport](strategySA4_ResultsAndAnalysis_10102026.md) |
| 9 | SA9 - VIX relief | 0,0 % | -0,7 % | -0,04 | -8,0 % | non récupéré | 2 041 | [rapport](strategySA9_ResultsAndAnalysis_10102026.md) |
| — | ETF_WORLD détenu (étalon, non noté) | — | +94,8 % | 0,93 | -21,6 % | 229 j | 100 | [rapport](strategyREF_WorldBuyHold_ResultsAndAnalysis_10102026.md) |

« Retour au sommet » : jours calendaires entre le sommet qui précède la perte
maximale et la première valorisation revenue à ce niveau.

Ce classement est **exploratoire**. Le score est une moyenne géométrique
pondérée de cinq blocs : un seul bloc à zéro donne un score nul, ce qui
explique les trois zéros du rang 9 et ne signifie ni égalité économique ni
probabilité de gain nulle. Il est déflaté par les dix essais de cette étude,
pas par les variantes des exercices antérieurs. Un écart de quelques points
(53,6 / 52,0 / 48,6) n'est pas un test de supériorité. Aucune stratégie du
catalogue ne bat le panier passif 50/50 des deux mêmes fonds.

## SA11 : les critères préinscrits ne sont pas satisfaits

Le statut `REFUTED` de l'hypothèse `sa11_garch_vol_control` est **opérationnel** :
les critères écrits avant le run sont atteints, puisque le Sharpe net de
`SA11` (0,87) n'est pas au-dessus de celui de `SA6` (0,90) ni du témoin EWMA
(0,93) et que sa perte maximale est plus profonde. Ce n'est pas une preuve
statistique d'infériorité : aux coûts de base, les intervalles à 95 % de la
différence de Sharpe incluent zéro ([-0,141 ; +0,076] contre `SA6`,
[-0,147 ; +0,009] contre l'EWMA) ; dans le second run à coûts doublés,
celui contre l'EWMA est négatif ([-0,172 ; -0,014]).

`SA11` a la **plus faible QLIKE moyenne observée** (-8,6225, contre -8,6033
pour l'EWMA et -8,5649 pour l'estimateur de `SA6`). L'avance est établie contre
`SA6` (différence appariée -0,058, intervalle [-0,108 ; -0,017]) et ne l'est
pas contre l'EWMA (-0,019, intervalle [-0,051 ; +0,009]). Aucun fit n'a été
rejeté sur 1 416 décisions. Mieux prévoir la variance de clôture à clôture ne
s'est pas traduit par une meilleure allocation après exécution à l'ouverture,
bande et coûts (2,5 fois ceux de `SA6`). Les témoins simples sont conservés ;
`SA11` reste au catalogue comme référence fixe. Cela ne dit rien des modèles
GARCH en général. Détail : [SA11_study_10102026.md](SA11_study_10102026.md).

## SA12 : une étude à part, sur la même période

[strategySA12_ResultsAndAnalysis_10102026.md](strategySA12_ResultsAndAnalysis_10102026.md)
vient de sa propre étude (`scripts/run_arima_garch_study.py`, commit `10f6d90`,
même magasin, même période 2021-04-01 → 2026-10-09), qui exécute aussi trois
contrôles sans code de catalogue : D0 (même ARIMA et même variance, filtre de
direction toujours ouvert), D1 (variance EWMA), D2 (moyenne constante). Son
registre compte 14 essais : ses scores ne se lisent pas dans le tableau
ci-dessus, déflaté par 10. Détail : [SA12_study_10102026.md](SA12_study_10102026.md).

| Livre | Net | Net, coûts ×2 | Sharpe | Perte max. | Exposition | Coûts (EUR) |
|---|---:|---:|---:|---:|---:|---:|
| **SA12 - ARIMA GARCH** | -1,72 % | -5,70 % | -0,14 | -6,99 % | 4 % | 4 022 |
| D0, même risque sans filtre | +64,07 % | +56,33 % | 0,85 | -17,77 % | 86 % | 5 788 |
| D1, ARIMA et variance EWMA | -2,46 % | -6,52 % | -0,20 | -7,32 % | 4 % | 4 126 |
| D2, moyenne constante et GARCH | 0,00 % | 0,00 % | n/a | 0,00 % | 0 % | 0 |
| SA6 - vol control | +67,43 % | +65,50 % | 0,90 | -15,72 % | 85 % | 1 445 |
| ETF_WORLD détenu | +94,79 % | +94,34 % | 0,93 | -21,64 % | 100 % | 100 |

- **Statut de l'hypothèse `sa12_arima_garch` : `INSUFFICIENT_EVIDENCE`.** Les
  critères écrits avant le run demandaient 30 épisodes de position terminés ;
  il y en a 29. Le seuil n'a pas été modifié après lecture. L'écart de Sharpe
  mesuré contre D0 est de -0,987 (intervalle à 95 % [-2,101 ; +0,252]) aux
  coûts de base et de -1,241 ([-2,335 ; -0,032]) à coûts doublés.
- **La prévision ne franchit le seuil de 20 pb que 31 soirs sur 1 413**, tous à
  partir du 2025-04-10 : le livre reste en cash quatre ans, puis prend 29
  positions dont 22 ne durent qu'une valorisation. Les coûts (4 022 EUR)
  dépassent le gain brut (+2,30 %).
- **La moyenne prévue ne bat pas deux prévisions naïves** (erreur quadratique
  9,2497e-05 contre 9,2133e-05 pour zéro et 9,2002e-05 pour la moyenne de la
  fenêtre ; signe juste 56,1 % contre 56,7 % pour « toujours en hausse »).
- **GARCH et EWMA ne sont pas départagés** (écart de Sharpe contre D1 +0,061,
  intervalle [-0,037 ; +0,170]) ; D2 n'a jamais pris de position.

Cela ne dit rien des modèles ARIMA-GARCH en général, et aucun contrôle n'est
candidat : en adopter un serait une nouvelle hypothèse.

## SA13 : une étude à part, sur une période de test plus courte

[strategySA13_ResultsAndAnalysis_10102026.md](strategySA13_ResultsAndAnalysis_10102026.md)
vient de sa propre étude (`scripts/run_signature_study.py`, commit `2b7d147`,
même magasin). Un modèle par mois est calibré sur ce qui était connu au soir
de la dernière séance du mois précédent ; le premier mois calibrable est
janvier 2023, donc la **période de test est 2023-01-02 → 2026-10-09** (964
séances), avec un portefeuille continu. Toutes les stratégies comparables y
sont rejouées, avec huit contrôles sans code de catalogue (C0 à C7) : 19
essais. **Ces chiffres ne se comparent pas à ceux du tableau du haut**, mesurés
depuis 2021. Détail : [SA13_study_10102026.md](SA13_study_10102026.md).

| Livre | Net | Net, coûts ×2 | Sharpe | Perte max. | Exposition | Coûts (EUR) |
|---|---:|---:|---:|---:|---:|---:|
| **SA13 - Signatures Neurons** | -3,53 % | -5,11 % | -0,10 | -18,56 % | 23 % | 1 579 |
| C0, même risque sans filtre (identique à SA6 ici) | +62,09 % | +61,08 % | 1,25 | -15,70 % | 89 % | 924 |
| C1, Ridge sur les mêmes 13 coefficients | +11,25 % | +10,40 % | 0,57 | -10,72 % | 16 % | 914 |
| C2, réseau additif à l'ordre 2 | -3,75 % | -3,92 % | -0,29 | -9,02 % | 3 % | 172 |
| C3, réseau additif sans volume | -3,47 % | -5,07 % | -0,09 | -15,68 % | 31 % | 1 534 |
| C4, réseau additif sur indicateurs classiques | +14,05 % | +12,66 % | 0,48 | -22,98 % | 44 % | 1 291 |
| C5, Ridge sur la trajectoire brute | -1,19 % | -25,72 % | -0,02 | -10,56 % | 31 % | 29 410 |
| C6, réseau additif, World + S&P 500 | -2,49 % | -4,90 % | -0,09 | -15,06 % | 24 % | 2 449 |
| C7, Ridge, World + S&P 500 | +17,87 % | +16,56 % | 0,78 | -13,95 % | 19 % | 1 337 |
| SA11 - GARCH vol control | +65,53 % | +63,31 % | 1,27 | -16,52 % | 92 % | 1 896 |
| SA12 - ARIMA GARCH | -1,72 % | -5,70 % | -0,16 | -6,99 % | 6 % | 4 022 |
| ETF_WORLD détenu | +86,73 % | +86,63 % | 1,35 | -21,57 % | 99 % | 99 |

- **Statut de l'hypothèse `sa13_signatures_neurons` : `INSUFFICIENT_EVIDENCE`.**
  Les critères écrits avant le premier ajustement demandaient 30 épisodes de
  position terminés ; il y en a 8. Le seuil n'a pas été modifié après lecture.
  L'écart de Sharpe mesuré contre C0 est de -1,353, intervalle à 95 %
  [-1,999 ; -0,627] (blocs de 60 séances ; négatif aussi par blocs de 20 et de
  120), et de -1,401 ([-2,052 ; -0,678]) à coûts doublés.
- **Couverture complète** : 46 mois sur 46 ont un modèle, 964 décisions sur 964
  une prévision utilisable. L'échec n'est pas opérationnel.
- **Les prévisions sont moins bonnes que la moyenne d'apprentissage** (erreur
  quadratique 8,7648e-05 contre 8,5353e-05, écart dont l'intervalle exclut
  zéro) **et que la Ridge sur les mêmes coefficients**. Signe juste 52,4 %
  contre 57,1 % pour « toujours en hausse ».
- **Le livre est investi pendant les deux baisses** (août 2024, février à avril
  2025), où la prévision monte avec la baisse, et en cash pendant de longues
  hausses : le fonds gagne +3,0 pb par séance quand le livre est investi et
  +8,3 pb quand il est en cash.
- **Ni l'ordre 3, ni le volume, ni un second processus n'abaissent l'erreur**
  de prévision ; contre les indicateurs classiques et la trajectoire brute,
  l'erreur de SA13 est plus basse sans que l'écart soit distingué de zéro.
- 22 modèles sur 46 s'arrêtent au plafond de 300 époques, gelé avant le
  premier ajustement.

Cela ne dit rien des signatures de chemin en général. Les contrôles Ridge font
mieux que `SA13` ici, mais aucun contrôle n'est candidat : en adopter un
serait une nouvelle hypothèse.

## Hors classement

- **ML1** ([rapport](strategyML1_ResultsAndAnalysis_10102026.md)) : son
  information s'arrête au 2024-12-31. Il est mesuré sur 2025-01-02 →
  2026-10-09 (+13,4 % contre +24,5 % pour le fonds, Sharpe 0,76 contre 0,93).
  Son score, déflaté pour un seul essai, ne se compare pas à ceux du tableau.
  Le test d'origine (jusqu'au 2026-09-30) a déjà été lu le 2026-10-04 ; les
  graines 43 et 44 et les deux runs à coûts doublés (modèle figé, modèle
  recalibré) sont dans les diagnostics.

## SA7 et SA8 : non exécutées

| Stratégie | Statut | Ce qui manque | Conséquence |
|---|---|---|---|
| SA7 - factor blend | non exécutée, aucun résultat | les trois fonds de style ne sont pas dans `market_data/metadata/instruments.toml` | le budget de 30 % de `SA10` reste en cash |
| SA8 - monetary carry | non exécutée, aucun résultat | le fonds monétaire n'est pas enregistré (la règle lit son propre rendement passé) | `SA10` ne place pas son capital résiduel |

Aucune analyse de performance n'existe pour elles et aucune n'est inventée
ici. Pour les exécuter : enregistrer les instruments, archiver leur historique
(`update_market_data.py --archive`), écrire leur hypothèse avant le premier
run, puis les ajouter au comparateur. `SA10` reste une version partielle tant
que ce n'est pas fait.

## Diagnostics complémentaires

[diagnostics_10102026.md](diagnostics_10102026.md) mesure ce que les analyses
listaient comme restant à mesurer ; c'est sa version 2, recalculée après la
vérification. Tout y est **descriptif** : les témoins sont construits sur des
poids constatés après coup, et aucune variante n'est candidate. Ce qu'on y lit :

- **Aucune règle à exposition variable ne bat nettement son témoin à cible
  constante.** Ce témoin vise les poids moyens de la règle, avec la même bande
  de 3 points ; son exposition réalisée est de 0,7 à 2,4 points plus haute. La
  comparaison décrit donc deux règles exécutables et n'isole pas la valeur du
  timing à exposition identique. `SA3` (Sharpe 0,79) et `SA10` (0,86) font
  moins bien que le leur (0,93 chacun), y compris en perte maximale. `SA6`
  (0,90) et `SA11` (0,87) ont une perte maximale inférieure d'environ trois
  points à celle du leur, pour un Sharpe plus bas ; seule l'EWMA égale le sien
  (0,93 contre 0,92) avec quatre points de perte maximale en moins.
- **`SA2` et `SA5` contre le 50/50** : une attribution approchée, qui valorise
  les poids de la clôture précédente au rendement de clôture à clôture. Pour
  `SA2` la contribution de l'exposition y est négative (-0,140 en rendement
  logarithmique) et celle du choix entre fonds presque nulle (+0,004). Pour
  `SA5` le choix entre fonds pèse +0,003, les coûts -0,112 et le résidu -0,060.
  Ce résidu n'est pas une mesure de l'exécution : il contient aussi le
  rendement de la journée sur ce qui a été traité le matin même, donc une
  partie de l'effet du signal. L'apport de l'inclinaison de `SA5` n'est pas
  isolé ; les corrélations de son signal avec le rendement relatif qui suit
  sont proches de zéro (+0,03 à +0,06, sans intervalle).
- **L'écart de prix signé clôture → ouverture, à quantités données**, vaut
  -14 568 EUR pour `SA1`, du même ordre que ses coûts explicites, et -4 944 EUR
  pour `SA9`, plus du double des siens ; `SA4` est le seul livre où il est
  positif (+2 303 EUR). Ce n'est ni un coût payé ni le résultat d'un backtest
  exécuté à la clôture : le signal lit cette clôture.
- **Par séjour dans le marché** : `SA1` a 71 séjours clos, dont 39 % gagnants,
  et un séjour encore ouvert ; `SA4` a 66 % de séjours gagnants (gain net moyen
  de 0,06 %) ; `SA9` en a 9 sur 21, soit 4 groupes de séjours gagnants sur 7,
  des groupes formés par une convention de 20 valorisations et non sept
  paniques indépendantes.
- **`SA10`** : l'effet agrégé de son contrôle de risque est faible sur ce run,
  sans que sa fréquence soit exportée, et aucune de ses règles ne porte son
  Sharpe.
- **`SA6` contre l'EWMA** : différence de Sharpe de -0,036, intervalle
  [-0,104 ; +0,027] ; les deux témoins ne sont pas départagés.
- **`ML1`** fait moins bien que son témoin à cible constante (Sharpe 0,76
  contre 0,93) ; les graines 43 et 44 échouent comme la graine 42 (Sharpe 0,68
  à 0,71 contre 0,86 pour le fonds, score sous 50 %), et à coûts doublés le
  modèle figé (0,64) comme le modèle recalibré (0,69) restent sous le fonds.

## Ce que ces fichiers ne contiennent pas

Les rapports couvrent toutes les séances mais ne sont pas l'archive d'un run.
Les ordres, prix d'exécution, coûts par séance, rejets et courbes brutes sont
dans les exports de l'étude (`results/garch_study/`), et le détail des
diagnostics dans `results/review_diagnostics/` (séjours un par un, entrées de
`ML1`, tables des témoins). Ces dossiers ne sont pas commités : ils se
reproduisent. Restent non produits : une attribution exacte de `SA2` et `SA5`
aux quantités et aux prix d'ouverture ; un témoin à exposition ou à risque
réellement rapprochés ; la décomposition des cibles de `SA10` règle par règle
à chaque décision, et le facteur de réduction de son contrôle de risque ; une
analyse des entrées de `ML1`.

## Reproduire

```bash
uv sync --extra ml --extra stats
uv run python scripts/update_market_data.py
uv run python scripts/run_garch_study.py --output results/garch_study
# les diagnostics chargent d'abord le modèle de ML1 : il doit exister
uv run python scripts/run_neural_strategy.py --seed 42 --calibrate-only
uv run python scripts/run_review_diagnostics.py
uv run python scripts/write_strategy_reports.py \
    --study results/garch_study --output research/reports/2026-10-10

# SA12, son étude et son rapport (une heure environ, un seul fil de calcul)
OMP_NUM_THREADS=1 uv run python scripts/run_arima_garch_study.py \
    --output results/arima_garch_study
uv run python scripts/write_strategy_reports.py \
    --study results/arima_garch_study --output research/reports/2026-10-10 --only SA12

# SA13, ses calibrations mensuelles, son étude et son rapport (vingt minutes environ)
uv sync --extra ml --extra stats --extra signatures
OMP_NUM_THREADS=1 uv run python scripts/run_signature_study.py \
    --output results/signature_study
uv run python scripts/write_strategy_reports.py \
    --study results/signature_study --output research/reports/2026-10-10 --only SA13
```

Cette recette refait la procédure, pas forcément les mêmes nombres : relancer
`update_market_data.py` ne garantit pas de retrouver le magasin `750c23dfffc3`,
et une calibration refaite sur des données révisées n'est pas le modèle publié
(`d9bfd125bf69`). Les diagnostics refusent de mettre un run à côté des exports
d'une étude faite sur un autre magasin, un autre capital ou d'autres coûts.

Le commentaire rédigé est dans [commentary.toml](commentary.toml) ; les
tableaux et les faits mesurés sont recalculés à chaque exécution. Tout est une
évaluation rétrospective : l'historique d'`ETF_WORLD` a déjà été regardé, et la
vérification prospective de `SA11` commence à la première séance XPAR après le
2026-10-10.
