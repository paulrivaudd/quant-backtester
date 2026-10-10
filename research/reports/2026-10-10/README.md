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

## Hors classement

- **ML1** ([rapport](strategyML1_ResultsAndAnalysis_10102026.md)) : son
  information s'arrête au 2024-12-31. Il est mesuré sur 2025-01-02 →
  2026-10-09 (+13,4 % contre +24,5 % pour le fonds, Sharpe 0,76 contre 0,93).
  Son score, déflaté pour un seul essai, ne se compare pas à ceux du tableau.
  Le test d'origine (jusqu'au 2026-09-30) a déjà été lu le 2026-10-04 ; les
  graines 43 et 44 et le run à coûts doublés ne sont pas présentés ici.

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

## Ce que ces fichiers ne contiennent pas

Les rapports couvrent toutes les séances mais ne sont pas l'archive d'un run.
Les ordres, prix d'exécution, coûts par séance, rejets et courbes brutes sont
dans les exports de l'étude (`results/garch_study/`, non commité car
reproductible) : `fills.csv`, `equity.csv`, `forecast_diagnostics.csv`
(paramètres et diagnostics de chaque fit), `forecast_evaluation.csv` (pertes
appariées), `forecast_qlike_differences.csv`. Ne sont produits nulle part
aujourd'hui : la décomposition des cibles de `SA10` par règle, les
caractéristiques d'entrée de `ML1` séance par séance, et le résultat de chaque
épisode d'activité de `SA4` et `SA9`.

## Reproduire

```bash
uv sync --extra ml --extra stats
uv run python scripts/update_market_data.py
uv run python scripts/run_garch_study.py --output results/garch_study
uv run python scripts/write_strategy_reports.py \
    --study results/garch_study --output research/reports/2026-10-10
```

Le commentaire rédigé est dans [commentary.toml](commentary.toml) ; les
tableaux et les faits mesurés sont recalculés à chaque exécution. Tout est une
évaluation rétrospective : l'historique d'`ETF_WORLD` a déjà été regardé, et la
vérification prospective de `SA11` commence à la première séance XPAR après le
2026-10-10.
