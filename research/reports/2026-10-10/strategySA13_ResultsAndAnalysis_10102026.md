# SA13 - Signatures Neurons — résultats et analyse

Période de test 2023-01-02 → 2026-10-09 · capital 100 000 EUR · commission 5 pb (minimum 1 EUR), demi-spread 3 pb, slippage 2 pb · quantités fixées à la décision, exécution à l'ouverture suivante · cash non rémunéré · 252 séances par an.

Source : commit `2b7d147d63e5` (CLEAN), magasin `750c23dfffc3`, données à jour au 2026-10-09. Évaluation rétrospective : l'historique d'ETF_WORLD a déjà été regardé dans les exercices précédents, ce n'est pas un échantillon vierge.

Étude dédiée (`scripts/run_signature_study.py`) : un modèle par variante et par mois (46 mois, 8 variantes), calibré sur ce qui était connu au soir de la dernière séance du mois précédent - 1 008 origines d'apprentissage et 126 de validation candidates, purgées aux deux frontières - puis gelé pour le mois ; un modèle est supposé disponible 12 heures après sa date limite d'information. La période commence au premier mois que le magasin permet de calibrer (date limite 2022-12-30) et le portefeuille est continu d'un mois à l'autre. Toutes les stratégies comparables sont rejouées sur cette période : leurs chiffres ne se comparent pas à ceux des rapports mesurés depuis 2021. L'hypothèse `sa13_signatures_neurons`, ses huit contrôles (C0 à C7, sans code de catalogue) et ses statuts ont été écrits avant le premier ajustement. Un seul fil de calcul.

## 1. Indicateurs de résultat globaux

| Indicateur | Stratégie | Fonds détenu (buy & hold ETF_WORLD) |
|---|---:|---:|
| Période mesurée | 2023-01-02 → 2026-10-09 (964 séances) | idem |
| Rang au classement commun (QUALITY_V1) | 12 | n/a |
| Score de qualité QUALITY_V1 (0-100 %) | 0.0% | n/a |
| - bloc marché (IR et alpha contre le fonds détenu) | 0.00 | n/a |
| - bloc significativité (Sharpe déflaté) | 0.01 | n/a |
| - bloc risque (drawdown relatif) | 0.64 | n/a |
| - bloc robustesse (sous-périodes ; stress approché des coûts) | 0.00 | n/a |
| - bloc implémentation (poids des coûts) | 0.00 | n/a |
| Rendement net total | -3.53% | +86.73% |
| Rendement brut total (mêmes ordres, sans coûts) | -1.95% | +86.83% |
| Rendement net annualisé | -0.95% | +18.03% |
| Volatilité annualisée | 6.79% | 12.69% |
| Ratio de Sharpe net (taux sans risque 0) | -0.10 | +1.35 |
| Ratio de Sortino net (taux sans risque 0) | -0.13 | +1.94 |
| Perte maximale (max drawdown) | -18.56% | -21.57% |
| Alpha annualisé contre le fonds détenu | -6.89% | n/a |
| Bêta contre le fonds détenu | 0.36 | n/a |
| Ratio d'information contre le fonds détenu | -1.87 | n/a |
| Alpha annualisé contre SA1 (MA20) | -2.22% | +11.85% |
| Bêta contre SA1 (MA20) | 0.28 | 0.98 |
| Exposition moyenne (part investie) | 23.5% | 99.4% |
| Ordres exécutés | 60 | 1 |
| Coûts payés (EUR) | 1,579 | 99 |
| Rotation annuelle (multiple de l'actif moyen) | 4.24 | 0.19 |
| Rendement net, deux premiers tiers | -10.54% | +45.35% |
| Rendement net, dernier tiers | +7.84% | +28.47% |
| Rendement net, second run réel à coûts doublés | -5.11% | n/a |
| Sharpe net, second run réel à coûts doublés | -0.17 | n/a |

Le score QUALITY_V1 est une **moyenne géométrique pondérée** de cinq blocs bornés entre 0 et 1 (marché 30 %, significativité 25 %, risque 15 %, robustesse 20 %, implémentation 10 %) : un seul bloc à zéro donne un score nul. Un score nul n'est donc ni une probabilité de gain nulle, ni une égalité économique entre deux stratégies ; le bloc implémentation, par exemple, tombe à zéro dès que les coûts atteignent 30 % du gain brut. Le bloc robustesse contient un **stress approché** des coûts, `net - (brut - net)` sur les mêmes ordres ; les deux dernières lignes du tableau viennent d'un **second run réel** à coûts doublés, où les quantités et la trajectoire changent, et n'entrent pas dans le score. Le score est déflaté par les essais de cette étude seulement, pas par la recherche antérieure : le classement est exploratoire, et un écart de quelques points entre deux scores n'est pas un test de supériorité. Les alphas sont des estimations ponctuelles sans intervalle, avec un taux sans risque nul ; l'alpha contre SA1 compare à une règle active, ce n'est pas un alpha de marché. Le fonds détenu est l'étalon du score et n'est pas noté. « n/a » : la mesure n'existe pas ; elle n'est jamais remplacée par zéro.

### Classement de tous les livres de l'étude, sur la même période

| Livre | Rang | Score | Net | Net, coûts x2 | Sharpe | Perte max. | Alpha/an | Exposition | Coûts (EUR) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 50/50 rebalanced | 1 | 74.1% | +92.04% | +91.52% | +1.36 | -22.46% | +0.26% | 100% | 475 |
| SA10 - ensemble | 2 | 47.5% | +29.77% | +28.44% | +1.21 | -11.74% | -0.45% | 44% | 1,235 |
| C0 - same risk no filter | 3 | 47.4% | +62.09% | +61.08% | +1.25 | -15.70% | -0.49% | 89% | 924 |
| SA6 - vol control | 3 | 47.4% | +62.09% | +61.08% | +1.25 | -15.70% | -0.49% | 89% | 924 |
| SA11 - GARCH vol control | 4 | 47.1% | +65.53% | +63.31% | +1.27 | -16.52% | -0.40% | 92% | 1,896 |
| SA2 - dual momentum | 5 | 44.9% | +69.38% | +64.90% | +1.19 | -22.78% | -0.75% | 88% | 3,080 |
| SA9 - VIX relief | 6 | 39.9% | +6.05% | +5.41% | +0.77 | -3.23% | +0.91% | 2% | 616 |
| C7 - Ridge context SP500 | 7 | 37.6% | +17.87% | +16.56% | +0.78 | -13.95% | -0.63% | 19% | 1,337 |
| SA3 - smooth MA | 8 | 33.7% | +46.63% | +46.27% | +0.95 | -21.60% | -2.75% | 79% | 366 |
| C1 - Ridge logsig3 | 9 | 31.9% | +11.25% | +10.40% | +0.57 | -10.72% | -1.29% | 16% | 914 |
| SA5 - relative tilt | 10 | 29.8% | +72.61% | +54.52% | +1.15 | -22.87% | -2.54% | 100% | 14,635 |
| C4 - NAM classical | 11 | 18.9% | +14.05% | +12.66% | +0.48 | -22.98% | -3.74% | 44% | 1,291 |
| C2 - NAM logsig2 | 12 | 0.0% | -3.75% | -3.92% | -0.29 | -9.02% | -3.24% | 3% | 172 |
| C3 - NAM no volume | 12 | 0.0% | -3.47% | -5.07% | -0.09 | -15.68% | -7.84% | 31% | 1,534 |
| C5 - Ridge raw trajectory | 12 | 0.0% | -1.19% | -25.72% | -0.02 | -10.56% | -5.08% | 31% | 29,410 |
| C6 - NAM context SP500 | 12 | 0.0% | -2.49% | -4.90% | -0.09 | -15.06% | -4.93% | 24% | 2,449 |
| SA1 - std MA20 | 12 | 0.0% | +21.12% | +9.96% | +0.62 | -10.09% | -2.42% | 71% | 11,112 |
| SA12 - ARIMA GARCH | 12 | 0.0% | -1.72% | -5.70% | -0.16 | -6.99% | -1.21% | 6% | 4,022 |
| **SA13 - Signatures Neurons** | 12 | 0.0% | -3.53% | -5.11% | -0.10 | -18.56% | -6.89% | 23% | 1,579 |
| SA4 - pullback | 12 | 0.0% | +4.03% | +0.63% | +0.54 | -3.42% | +0.12% | 4% | 3,376 |
| buy & hold World | n/a | n/a | +86.73% | +86.63% | +1.35 | -21.57% | n/a | 99% | 99 |

Tous ces livres sont exécutés par le même moteur, sur la même période, avec les mêmes coûts. Les contrôles (noms commençant par D ou C) et les deux références ne sont pas des candidats. Ces chiffres ne se comparent pas à ceux d'une autre étude, mesurés depuis une autre date ; un rang n'est pas une probabilité de succès.

## 2. Analyse

### Faits mesurés

| Période | Du | Au | Valorisations | Rendements | Stratégie | ETF_WORLD (clôture) | Fonds détenu (net) | Écart relatif | Poids de clôture moyen | Poids de clôture min. | Poids de clôture max. |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Plus forte baisse (sommet → creux) | 2024-07-16 | 2025-04-09 | 189 | 188 | -18.56% | -11.77% | -11.72% | -7.75% | 32% | 0% | 100% |
| Plus forte hausse (creux → sommet ultérieur, durée libre) | 2025-04-09 | 2026-06-15 | 300 | 299 | +14.13% | +45.06% | +44.82% | -21.20% | 34% | 0% | 100% |
| Pires 63 rendements consécutifs | 2025-01-10 | 2025-04-09 | 64 | 63 | -14.26% | -18.17% | -18.09% | +4.68% | 58% | 0% | 100% |
| Meilleurs 63 rendements consécutifs | 2025-08-01 | 2025-10-29 | 64 | 63 | +8.86% | +9.57% | +9.53% | -0.61% | 95% | 77% | 100% |
| Plus fort retard relatif sur le fonds détenu | 2023-03-13 | 2026-10-06 | 911 | 910 | -4.04% | +87.82% | +87.27% | -48.76% | 24% | 0% | 100% |
| Plus forte avance relative sur le fonds détenu | 2025-01-31 | 2025-04-09 | 49 | 48 | -14.26% | -21.23% | -21.14% | +8.74% | 76% | 0% | 100% |
| Plus forte baisse du fonds détenu | 2025-02-19 | 2025-04-09 | 36 | 35 | -15.65% | -21.66% | -21.57% | +7.54% | 72% | 36% | 100% |
| Plus forte hausse du fonds détenu | 2023-01-03 | 2026-10-06 | 960 | 959 | -3.53% | +88.71% | +88.15% | -48.73% | 24% | 0% | 100% |

Chaque ligne va de la valeur de la séance « Du » à celle de la séance « Au » : N valorisations, donc N - 1 rendements. « Plus forte hausse » est la plus grande hausse d'un creux à un sommet ultérieur, de durée libre : ce n'est ni une position ni un trade. Les deux périodes relatives sont choisies sur le rapport de la stratégie au fonds détenu, dont l'« écart relatif » `(1 + stratégie) / (1 + fonds) - 1` est la variation. Le « poids de clôture » est la part de l'actif net détenue en fonds à la valorisation du soir, le reste étant du cash non rémunéré : il a pu dériver avec les cours, et le multiplier par le rendement du fonds ne reconstitue pas le résultat. Une décision prise le soir de t (signal et poids cible de la ligne t) est exécutée à l'ouverture de t + 1 et n'apparaît dans le poids détenu qu'à la ligne t + 1.

### Baisses sous un sommet et retour à ce sommet

| Rang | Sommet | Creux | Profondeur | Retour au sommet | Jours calendaires |
|---:|---|---|---:|---|---:|
| 1 | 2024-07-16 | 2025-04-09 | -18.56% | non récupéré au 2026-10-09 | 815 (en cours) |
| 2 | 2023-10-12 | 2023-10-27 | -5.58% | 2023-11-22 | 41 |
| 3 | 2023-02-03 | 2023-10-05 | -2.10% | 2023-10-10 | 249 |

Drawdown au 2026-10-09 : **-7.26%** sous le plus haut de la période.
Plus longue période sous un sommet : **815 jours calendaires**, du 2024-07-16 au 2026-10-09 (en cours, creux à -18.56%).

### Par année et par mois

| Année | Stratégie | Fonds détenu | 50/50 rebalancé | Séances |
|---|---:|---:|---:|---:|
| 2023 | +2.07% | +17.32% | +18.50% | 255 |
| 2024 | -3.20% | +26.95% | +30.26% | 256 |
| 2025 | -3.34% | +6.59% | +5.02% | 255 |
| 2026 (partielle, au 2026-10-09) | +1.02% | +17.62% | +18.47% | 198 |

Mois : **9 positifs, 9 négatifs, 28 sans variation** sur 46 (mois incomplets : 2026-10 s'arrête au 2026-10-09). Pire mois : **2025-03** (-6.47%, fonds détenu -7.90%). Meilleur mois : **2023-11** (+5.03%, fonds détenu +5.64%).

Activité : une position est détenue à la clôture de **269 valorisations sur 964** ; le poids total détenu y va de 29.0% à 99.9% (moyenne sur toutes les valorisations : 23.5%).

### Couverture, prévisions et composition (étude SA13)

- **Couverture.** 46 mois sur 46 ont un modèle calibré ; 964 décisions sur 964 ont un modèle autorisé et des features utilisables (100.00%). Motifs des décisions inutilisables : aucun. Les mois sans modèle et les séances sans signal restent dans la performance, en cash.
- **Calibrations.** 1004 exemples d'apprentissage et 124 de validation en moyenne par mois ; époque retenue moyenne 206 ; 22 modèle(s) sur 46 retenu(s) à la dernière époque autorisée, c'est-à-dire avec une perte de validation encore en baisse à l'arrêt. Ce plafond était gelé avant le premier ajustement.
- **Erreur de prévision, toutes prévisions valides.** 962 paires ; MSE 8.7648e-05, contre 8.5767e-05 pour la prévision nulle et 8.5353e-05 pour la moyenne d'apprentissage gelée avec chaque modèle ; R² hors apprentissage -0.0269 ; corrélation prévision/réalisation -0.035.
- **Signe.** Juste 52.4%, contre 57.1% pour « toujours en hausse » ; justesse équilibrée 49.1% ; 705 prévisions positives.
- **Prévisions suivies d'une position portée.** 269 paires ; MSE 1.9108e-04 ; signe juste 55.4% contre 55.4% pour « toujours en hausse ».
- **Épisodes de position.** 8 épisodes, dont 8 terminés ; 5 gagnants ; net moyen -0.35%.

### De quoi une prévision de SA13 est faite (contributions moyennes, en points de base)

| Décisions | Nombre | Prévision | Référence | Déplacements | Prix-volume | Prix-temps | Volume-temps | Ordre 3 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Toutes les décisions utilisables | 964 | +6.09 | -4.77 | +3.64 | -0.18 | +2.18 | -0.91 | +6.12 |
| Décisions qui ont ouvert une position | 8 | +23.28 | -3.60 | +0.33 | +0.91 | +0.49 | -0.68 | +25.83 |
| Décisions qui ont fermé une position | 8 | -2.73 | -4.51 | +3.38 | +0.14 | +2.70 | -0.44 | -4.00 |

Chaque prévision est exactement sa référence plus ses contributions. Une contribution à la prévision n'est pas une contribution au résultat : le poids économique d'un groupe se teste par la variante réentraînée sans lui (C2 pour l'ordre 3, C3 pour le volume). Le point `z = 0` est une référence statistique des features, pas un chemin de marché réalisable.

### Écarts d'erreur quadratique (premier moins second, négatif = premier meilleur)

| Comparaison | Paires | Écart moyen | Intervalle 95 % |
|---|---:|---:|---|
| SA13 - zero forecast | 962 | +1.881e-06 | [-4.360e-07 ; +5.886e-06] |
| SA13 - training mean | 962 | +2.294e-06 | [+1.800e-07 ; +5.913e-06] |
| SA13 - C1 (the neurons, against Ridge on the same log-signature) | 962 | +1.485e-06 | [+1.272e-07 ; +3.536e-06] |
| SA13 - C2 (order 3, against order 2) | 962 | +1.733e-06 | [-2.477e-07 ; +4.587e-06] |
| SA13 - C3 (the volume, against none) | 962 | +6.859e-07 | [-2.890e-07 ; +2.265e-06] |
| SA13 - C4 (the signature, against classical indicators) | 962 | -4.139e-07 | [-2.572e-06 ; +1.373e-06] |
| SA13 - C5 (the compression, against the raw trajectory) | 962 | -1.271e-06 | [-6.224e-06 ; +7.281e-06] |
| C6 - SA13 (a second process, against the fund alone) | 962 | +3.805e-06 | [+1.334e-06 ; +6.012e-06] |
| C6 - C7 (the neurons on two processes, against Ridge) | 962 | +5.323e-06 | [+2.863e-06 ; +7.651e-06] |

Bootstrap par blocs mobiles de 60 origines, 5000 tirages, graine 20261010. Les fenêtres se recouvrent fortement : mille lignes ne sont pas mille expériences indépendantes.

### SA13 contre ses contrôles et les références

| Coûts | Contrôle | Sharpe SA13 | Sharpe contrôle | Écart | Intervalle 95 % | Perte max. SA13 | Perte max. contrôle |
|---|---|---:|---:|---:|---|---:|---:|
| x1 | C0 - same risk no filter | -0.104 | +1.249 | -1.353 | [-1.999 ; -0.627] | -18.56% | -15.70% |
| x1 | C1 - Ridge logsig3 | -0.104 | +0.568 | n/a | [n/a ; n/a] | -18.56% | -10.72% |
| x1 | C2 - NAM logsig2 | -0.104 | -0.285 | n/a | [n/a ; n/a] | -18.56% | -9.02% |
| x1 | C3 - NAM no volume | -0.104 | -0.088 | -0.016 | [-0.525 ; +0.464] | -18.56% | -15.68% |
| x1 | C4 - NAM classical | -0.104 | +0.480 | -0.584 | [-1.532 ; +0.480] | -18.56% | -22.98% |
| x1 | C5 - Ridge raw trajectory | -0.104 | -0.017 | -0.088 | [-1.331 ; +1.155] | -18.56% | -10.56% |
| x1 | C6 - NAM context SP500 | -0.104 | -0.088 | -0.017 | [-0.524 ; +0.611] | -18.56% | -15.06% |
| x1 | C7 - Ridge context SP500 | -0.104 | +0.776 | -0.881 | [-2.338 ; +0.208] | -18.56% | -13.95% |
| x1 | SA6 - vol control | -0.104 | +1.249 | -1.353 | [-1.999 ; -0.627] | -18.56% | -15.70% |
| x1 | SA11 - GARCH vol control | -0.104 | +1.269 | -1.374 | [-2.042 ; -0.645] | -18.56% | -16.52% |
| x1 | SA12 - ARIMA GARCH | -0.104 | -0.164 | n/a | [n/a ; n/a] | -18.56% | -6.99% |
| x1 | buy & hold World | -0.104 | +1.352 | -1.456 | [-2.118 ; -0.788] | -18.56% | -21.57% |
| x1 | 50/50 rebalanced | -0.104 | +1.365 | -1.469 | [-2.173 ; -0.769] | -18.56% | -22.46% |
| x2 | C0 - same risk no filter | -0.168 | +1.233 | -1.401 | [-2.052 ; -0.678] | -18.98% | -15.77% |
| x2 | C1 - Ridge logsig3 | -0.168 | +0.528 | n/a | [n/a ; n/a] | -18.98% | -10.88% |
| x2 | C2 - NAM logsig2 | -0.168 | -0.298 | n/a | [n/a ; n/a] | -18.98% | -9.06% |
| x2 | C3 - NAM no volume | -0.168 | -0.147 | -0.021 | [-0.517 ; +0.456] | -18.98% | -15.78% |
| x2 | C4 - NAM classical | -0.168 | +0.438 | -0.606 | [-1.556 ; +0.463] | -18.98% | -23.49% |
| x2 | C5 - Ridge raw trajectory | -0.168 | -1.163 | +0.996 | [-0.376 ; +2.349] | -18.98% | -26.74% |
| x2 | C6 - NAM context SP500 | -0.168 | -0.202 | +0.034 | [-0.469 ; +0.665] | -18.98% | -15.64% |
| x2 | C7 - Ridge context SP500 | -0.168 | +0.725 | -0.892 | [-2.313 ; +0.183] | -18.98% | -13.99% |
| x2 | SA6 - vol control | -0.168 | +1.233 | -1.401 | [-2.052 ; -0.678] | -18.98% | -15.77% |
| x2 | SA11 - GARCH vol control | -0.168 | +1.237 | -1.405 | [-2.082 ; -0.672] | -18.98% | -16.59% |
| x2 | SA12 - ARIMA GARCH | -0.168 | -0.567 | n/a | [n/a ; n/a] | -18.98% | -9.46% |
| x2 | buy & hold World | -0.168 | +1.350 | -1.518 | [-2.185 ; -0.849] | -18.98% | -21.58% |
| x2 | 50/50 rebalanced | -0.168 | +1.359 | -1.527 | [-2.238 ; -0.825] | -18.98% | -22.47% |

C0 : mêmes modèles, même disponibilité, même dimensionnement, filtre de direction toujours actif. C1 : Ridge sur les 13 mêmes coefficients. C2 : réseau additif à l'ordre 2. C3 : réseau additif sans volume. C4 : réseau additif sur neuf indicateurs classiques. C5 : Ridge sur la trajectoire brute. C6 et C7 : réseau additif et Ridge sur World + S&P 500. Ce sont des contrôles de recherche, sans code de catalogue, et aucun n'est candidat. Bootstrap apparié par blocs de 60 séances, 5000 tirages, graine 20261010.

Écart principal, SA13 moins C0, aux trois longueurs de bloc annoncées :

| Coûts | Bloc | Écart de Sharpe | Intervalle 95 % |
|---|---:|---:|---|
| x1 | 20 | -1.353 | [-2.028 ; -0.543] |
| x1 | 60 | -1.353 | [-1.999 ; -0.627] |
| x1 | 120 | -1.353 | [-1.987 ; -0.673] |
| x2 | 20 | -1.401 | [-2.074 ; -0.602] |
| x2 | 60 | -1.401 | [-2.052 ; -0.678] |
| x2 | 120 | -1.401 | [-2.034 ; -0.714] |

### Statut de l'hypothèse préinscrite `sa13_signatures_neurons` : **INSUFFICIENT_EVIDENCE**

- 8 completed position episodes, under 30

Ce statut répond à une seule question, écrite avant le premier ajustement : le filtre de direction appris sur la log-signature améliore-t-il le même dimensionnement de risque sans lui (C0) ? Les intervalles sont conditionnels au chemin déjà produit ; ils ne portent ni l'incertitude des réestimations ni la sélection des idées. Conclusions séparées, sur les écarts d'erreur quadratique :

- Apport des neurones (SA13 contre Ridge sur les mêmes log-signatures) : erreur quadratique non plus faible : non soutenu sur ce chemin.
- Apport de l'ordre 3 (contre l'ordre 2) : erreur quadratique non plus faible : non soutenu sur ce chemin.
- Apport du volume (contre le canal de volume à zéro) : erreur quadratique non plus faible : non soutenu sur ce chemin.
- Apport des signatures (contre neuf indicateurs classiques) : erreur quadratique plus faible, intervalle contenant zéro : non établi.
- Apport de la compression (contre la trajectoire brute en Ridge) : erreur quadratique plus faible, intervalle contenant zéro : non établi.
- Apport d'un second processus (World + S&P 500 contre World seul) : erreur quadratique non plus faible : non soutenu sur ce chemin.

### En résumé

Détenir ETF_WORLD seulement quand un petit réseau additif (4 unités tanh par coefficient, 157 paramètres), réestimé chaque mois, prévoit plus de 20 pb pour le rendement de l'ouverture de t + 1 à l'ouverture de t + 2, à partir des 13 coefficients de la log-signature d'ordre 3 des 60 dernières séances du fonds (prix, activité, temps) ; la position est gardée tant que la prévision reste strictement positive, au poids de SA6, min(1, 12 % / max(σ20, σ60, 5 %)). Sur les 964 séances de test le livre prend 8 positions, est investi à 23,5 % en moyenne et perd 3,53 % net, quand le même dimensionnement sans filtre (C0, identique ici à SA6 puisque la couverture est de 100 %) gagne 62,09 %. Le statut préinscrit est INSUFFICIENT_EVIDENCE parce qu'il n'y a que 8 épisodes terminés pour 30 requis ; l'écart de Sharpe mesuré contre C0 est de -1,35, avec un intervalle entièrement négatif. Les prévisions ont une erreur quadratique plus élevée que la moyenne d'apprentissage et que la régression Ridge sur les mêmes coefficients. Cela ne dit rien des signatures de chemin en général.

### Points forts

- **Fait.** La chaîne fonctionne et se vérifie : 46 mois sur 46 ont un modèle calibré ; 964 décisions sur 964 ont un modèle autorisé et des features utilisables ; les prévisions exportées depuis les features de la calibration sont exactement celles que le signal du run a calculées ; chaque prévision est sa référence plus ses 13 contributions.
- **Fait.** Pendant la baisse du fonds du 2025-02-19 au 2025-04-09 (-21,57 %), le livre perd -15,65 % : le poids détenu passe de 100 % à 36 %. **Lecture.** Cette réduction vient de la règle de taille de SA6, pas de la prévision, qui est restée positive pendant toute la baisse.
- **Fait.** Sur ses 63 meilleurs rendements consécutifs (2025-08-01 au 2025-10-29) le livre fait +8,86 % contre +9,57 % pour le fonds, avec un poids de clôture moyen de 95 %.
- **Fait.** L'erreur quadratique de SA13 est un peu plus basse que celle du réseau sur indicateurs classiques (écart de -4,1e-07) et que celle de la Ridge sur trajectoire brute (-1,3e-06) ; les deux intervalles contiennent zéro.
- **Fait.** Les fonctions apprises changent peu de signe d'un mois à l'autre : à z = ±1 et ±2, la contribution d'un coefficient a le signe de sa moyenne dans 84 à 86 % des mois en moyenne, et dans 67 % des mois pour l'aire prix-volume à z = 2. C'est une mesure de stabilité, pas de justesse.

### Points faibles

- **Fait.** -3,53 % net sur la période, contre +62,09 % pour C0 et SA6 et +86,73 % pour le fonds ; Sharpe -0,10 ; -5,11 % dans le second run à coûts doublés. Brut de coûts le livre perd déjà 1,95 % : la perte ne vient pas d'abord des coûts (1 579 EUR).
- **Fait.** Perte maximale de -18,56 %, plus profonde que celle de C0 (-15,70 %), et non récupérée au 2026-10-09, 815 jours après le sommet du 2024-07-16.
- **Fait.** Les séances investies sont moins bonnes que les séances en cash : le fonds gagne en moyenne +3,0 pb par séance sur les 269 valorisations où le livre est investi (+6,6 % composé), contre +8,3 pb sur les 694 autres (+75,0 % composé).
- **Fait.** Les prévisions sont moins bonnes que deux prévisions naïves : erreur quadratique moyenne de 8,7648e-05, contre 8,5767e-05 pour la prévision nulle et 8,5353e-05 pour la moyenne d'apprentissage gelée avec chaque modèle (écart de +2,3e-06, intervalle à 95 % [+1,8e-07 ; +5,9e-06], au-dessus de zéro) ; R² hors apprentissage -0,027 ; corrélation prévision/réalisation -0,035 ; signe juste 52,4 % contre 57,1 % pour « toujours en hausse ».
- **Fait.** Le réseau fait moins bien que la Ridge sur les mêmes 13 coefficients : écart d'erreur quadratique de +1,5e-06, intervalle [+1,3e-07 ; +3,5e-06] ; le livre de la Ridge (C1) fait +11,25 % net.
- **Fait.** 22 modèles sur 46 sont retenus à la dernière époque autorisée (300) : leur perte de validation baissait encore à l'arrêt.
- **Fait.** Seulement 8 entrées en 964 séances : 88 soirs ont une prévision au-dessus de 20 pb, mais 80 d'entre eux tombent quand le livre est déjà investi, et 438 soirs en cash ont une prévision entre 0 et 20 pb.

### Ce qui s'est passé pendant la période où la stratégie a le plus perdu

**Fait.** La plus forte baisse va du sommet du 2024-07-16 (104 024,9 EUR) au creux du 2025-04-09 (84 714,7 EUR) : -18,56 %, contre -11,77 % pour le fonds. Elle contient deux épisodes longs. Le premier : le soir du 2024-07-01 la prévision vaut +20,1 pb (dont +23,5 pb pour le groupe d'ordre 3) et la cible 100 % ; l'achat est exécuté à l'ouverture du 2024-07-02 (518,15). Le 2024-08-02 le fonds clôture à 496,61 après 517,22 la veille ; la prévision monte à +47,1 pb, puis +58,1 pb le 5 août, et reste positive : la position est gardée et seul le dimensionnement la réduit, de 100 % à 58 % le 8 août. La prévision devient négative le soir du 2024-08-20 (-1,0 pb) et la vente est exécutée à l'ouverture du 2024-08-21 (515,76) : -3,15 % sur le livre pour cet épisode, quand le fonds perd 0,53 % de clôture à clôture. Le second : le soir du 2025-01-31 la prévision vaut +22,6 pb (ordre 3 : +29,3 pb) et la cible 97 % ; l'achat est exécuté à l'ouverture du 2025-02-03 (584,79). Du 2025-02-19 au 2025-04-09 le fonds perd 21,57 % ; la prévision reste positive aux 36 décisions de cette baisse (entre +3,5 et +75,5 pb, +33,4 pb en moyenne), portée par le groupe des déplacements (+20,5 pb en moyenne) et par l'aire prix-temps (+11,4 pb), tandis que le groupe d'ordre 3 devient négatif. Le poids détenu descend de 100 % à 36 % par le seul effet de la volatilité. La prévision ne devient négative que le soir du 2025-05-19 (-9,1 pb) et la vente est exécutée à l'ouverture du 2025-05-20 (548,69) : -9,46 % sur le livre pour cet épisode de 73 valorisations. **Lecture.** Dans ces deux baisses le modèle prévoit d'autant plus de hausse que le fonds a déjà baissé : la contribution des déplacements se comporte comme un pari de retour à la moyenne, qui n'a pas été payé à l'horizon d'une séance. Ce n'est pas démontré au-delà de ces deux épisodes.

### Ce qui s'est passé pendant la période où la stratégie a le plus gagné

**Fait.** La plus forte hausse d'un creux à un sommet ultérieur va du 2025-04-09 au 2026-06-15 : +14,13 % contre +45,06 % pour le fonds, avec un poids de clôture moyen de 34 %. Elle tient d'abord à la fin de l'épisode précédent - le livre, encore investi à 36 % au creux, n'est vendu que le 2025-05-20 - puis à l'épisode le plus long : le soir du 2025-07-17 la prévision vaut +26,3 pb (ordre 3 : +33,3 pb) et la cible 94 % ; l'achat est exécuté à l'ouverture du 2025-07-18 (560,77) ; la prévision reste positive pendant 93 valorisations, passe à -1,1 pb le soir du 2025-11-25, et la vente est exécutée à l'ouverture du 2025-11-26 (603,70) : +6,75 % sur le livre, quand le fonds gagne 8,24 % de clôture à clôture. Le livre est ensuite en cash du 2025-11-26 au 2026-06-09, pendant que le fonds gagne 8,57 %. **Lecture.** Quand le livre gagne, il gagne à peu près ce que le fonds gagne sur les mêmes séances, moins les coûts : rien ici ne montre un choix de séances meilleur que la détention.

### Situations de marché les plus risquées pour cette stratégie

- **Observé.** Baisse prolongée du fonds (août 2024, février à avril 2025) : la prévision monte avec la baisse et le filtre ne vend pas ; seule la règle de volatilité réduit le poids.
- **Observé.** Hausse régulière et calme (du 2023-11-24 au 2024-07-02, fonds +20,18 % ; du 2025-11-26 au 2026-06-09, +8,57 %) : la prévision reste positive mais sous 20 pb et le livre reste en cash.
- **Observé.** Sortie après la baisse, retour tardif : vendu à l'ouverture du 2025-05-20 (548,69), le livre ne revient qu'à celle du 2025-07-18 (560,77).
- **Plausible.** Coefficients d'ordre 3 hors du domaine d'apprentissage : aux décisions de test, 1,5 % et 2,3 % des valeurs normalisées de deux coefficients d'ordre 3 dépassent +5 et sont écrêtées, alors que les entrées reposent surtout sur ce groupe (+25,8 pb pour une prévision moyenne de +23,3 pb aux 8 décisions d'entrée).
- **Plausible.** Un modèle changé chaque mois peut déplacer la prévision au changement de mois sans que le marché ait bougé : la référence passe de -3,95 pb à -0,89 pb entre le soir du 2025-01-31 et celui du 2025-02-03. L'effet sur les décisions n'est pas mesuré.

### Mesures complémentaires (voir SA13_study_10102026.md)

- **Fait.** SA13 contre C0 : écart de Sharpe de -1,353, intervalle bootstrap à 95 % [-1,999 ; -0,627] par blocs de 60 séances, [-2,028 ; -0,543] par blocs de 20 et [-1,987 ; -0,673] par blocs de 120. À coûts doublés : -1,401, intervalle [-2,052 ; -0,678].
- **Fait.** Les livres des contrôles, nets : C7 (Ridge, deux processus) +17,87 % ; C4 (réseau, indicateurs classiques) +14,05 % ; C1 (Ridge) +11,25 % ; C5 (Ridge, trajectoire brute) -1,19 %, et -25,72 % à coûts doublés avec 75 rotations de l'actif par an ; C6 (réseau, deux processus) -2,49 % ; C3 (sans volume) -3,47 % ; C2 (ordre 2) -3,75 %. Aucun n'approche C0.
- **Fait.** Quatre écarts d'erreur quadratique ont un intervalle qui exclut zéro : SA13 moins la moyenne d'apprentissage (+2,3e-06), SA13 moins Ridge (+1,5e-06), deux processus moins un seul (+3,8e-06), réseau moins Ridge sur deux processus (+5,3e-06). Dans les quatre cas le modèle le plus riche a l'erreur la plus élevée.
- **Fait.** Ordre 3 contre ordre 2 (+1,7e-06) et avec volume contre sans (+6,9e-07) : SA13 n'a pas l'erreur la plus basse, et les deux intervalles contiennent zéro.
- **Fait.** Trois comparaisons de Sharpe (contre C1, C2 et SA12) sont refusées par le bootstrap : ces livres restent si longtemps en cash que certains rééchantillonnages n'ont aucune variation. Elles sont notées n/a, jamais zéro.
- **Lecture.** Sur ce chemin le filtre appris a retiré de l'exposition pendant les hausses et l'a gardée pendant les deux baisses : l'inverse de ce que l'hypothèse attendait.

### Ce que ces résultats n'établissent pas, et ce qui reste à mesurer

- Le statut INSUFFICIENT_EVIDENCE est celui des critères écrits avant le premier ajustement : 8 épisodes terminés pour 30 requis. Le seuil n'a pas été modifié après lecture. L'écart mesuré contre C0 est négatif, avec un intervalle sous zéro aux trois longueurs de bloc ; ces intervalles sont conditionnels au chemin produit et ne portent ni l'incertitude des réestimations ni la sélection des idées.
- Le plafond de 300 époques, le pas d'apprentissage et le seuil d'entrée de 20 pb étaient gelés. Les modifier après lecture - par exemple parce que 22 modèles sur 46 s'arrêtent au plafond - serait une nouvelle variante, à préinscrire.
- Les contrôles Ridge (C1, C7) font mieux que SA13 ici. En adopter un serait une nouvelle hypothèse : aucun ne remplace le résultat de SA13.
- Le délai de 12 heures entre la date limite d'un modèle et sa disponibilité est une hypothèse du run historique.
- Les fonctions de composante et leur domaine observé sont exportés (`component_functions.csv`, `feature_domain.csv`) mais ne sont pas tracés ici.
- Une contribution à la prévision n'est pas une contribution au résultat : le poids économique d'un groupe ne se lit que sur la variante réentraînée sans lui (C2 pour l'ordre 3, C3 pour le volume).
- La vérification prospective commence à la première séance XPAR où les artefacts existent réellement, configuration figée ; elle n'existe pas encore.

## 3. Historique : sous-jacent, indicateurs utilisés et valeur de la stratégie

Une ligne par séance. Les indicateurs sont ceux que la stratégie a lus à sa décision du soir (23:00 Paris), recalculés par ses propres signaux sur le magasin tel que le run l'a lu. Le poids cible de la ligne t est décidé ce soir-là et exécuté à l'ouverture de t + 1 ; le poids détenu de la ligne t est celui du portefeuille à la valorisation de t. Une case vide est un indicateur sans valeur ce jour-là. Les ordres, les prix d'exécution et les coûts de chaque séance ne sont pas dans ce tableau : ils sont dans `fills.csv` de l'étude.

Colonnes propres à SA13 : le mois du modèle utilisé, dont l'information s'arrête au soir de la dernière séance du mois précédent ; la prévision en points de base et sa décomposition exacte - référence, déplacements de prix et d'activité, aires prix-volume, prix-temps et volume-temps, groupe d'ordre 3 - dont la somme est la prévision ; le filtre, lu sur le poids détenu ce soir-là ; le poids avant la bande de 3 points ; les deux volatilités réalisées de la règle de taille. Une contribution à la prévision n'est pas une contribution au résultat. L'identifiant complet de chaque modèle est dans `sa13_history.csv` de l'étude.

| Séance | Clôture ETF_WORLD | Ouverture ETF_WORLD | Modèle du mois (AAAAMM) | Prévision (pb) | Référence (pb) | Déplacements (pb) | Prix-volume (pb) | Prix-temps (pb) | Volume-temps (pb) | Ordre 3 (pb) | Filtre (1 = ouvert) | Poids avant bande | `volatility_20r[ETF_WORLD]` | `volatility_60r[ETF_WORLD]` | Poids cible ETF_WORLD | Poids détenu ETF_WORLD | Valeur nette (EUR) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2023-01-02 | 383.75 | 385.28 | 202301 | -2.63 | -5.07 | +7.53 | -3.56 | +2.05 | +0.12 | -3.71 | 0 | 0.0% | 0.2010 | 0.1507 | 0.0% | 0.0% | 100,000.00 |
| 2023-01-03 | 380.01 | 381.83 | 202301 | -5.52 | -5.07 | +7.42 | -4.80 | +3.15 | -0.00 | -6.21 | 0 | 0.0% | 0.2014 | 0.1517 | 0.0% | 0.0% | 100,000.00 |
| 2023-01-04 | 383.49 | 381.05 | 202301 | +0.53 | -5.07 | +8.02 | -4.50 | +2.95 | -0.22 | -0.65 | 0 | 0.0% | 0.2006 | 0.1522 | 0.0% | 0.0% | 100,000.00 |
| 2023-01-05 | 381.18 | 381.42 | 202301 | +0.46 | -5.07 | +7.86 | -5.32 | +3.74 | -0.08 | -0.66 | 0 | 0.0% | 0.2004 | 0.1526 | 0.0% | 0.0% | 100,000.00 |
| 2023-01-06 | 384.86 | 381.66 | 202301 | +9.58 | -5.07 | +8.24 | -4.36 | +2.90 | -0.16 | +8.04 | 0 | 0.0% | 0.2037 | 0.1538 | 0.0% | 0.0% | 100,000.00 |
| 2023-01-09 | 387.15 | 385.07 | 202301 | +15.48 | -5.07 | +8.25 | -3.73 | +2.31 | -0.25 | +13.97 | 0 | 0.0% | 0.2042 | 0.1542 | 0.0% | 0.0% | 100,000.00 |
| 2023-01-10 | 382.92 | 382.80 | 202301 | +4.70 | -5.07 | +7.98 | -3.79 | +2.42 | +0.02 | +3.15 | 0 | 0.0% | 0.2072 | 0.1546 | 0.0% | 0.0% | 100,000.00 |
| 2023-01-11 | 386.85 | 384.89 | 202301 | +12.00 | -5.07 | +8.11 | -2.75 | +1.49 | -0.40 | +10.63 | 0 | 0.0% | 0.2039 | 0.1559 | 0.0% | 0.0% | 100,000.00 |
| 2023-01-12 | 387.70 | 388.88 | 202301 | +12.75 | -5.07 | +7.91 | -2.36 | +1.13 | -0.54 | +11.68 | 0 | 0.0% | 0.2042 | 0.1558 | 0.0% | 0.0% | 100,000.00 |
| 2023-01-13 | 388.78 | 388.11 | 202301 | +15.11 | -5.07 | +7.67 | -2.04 | +0.86 | -0.78 | +14.46 | 0 | 0.0% | 0.1585 | 0.1558 | 0.0% | 0.0% | 100,000.00 |
| 2023-01-16 | 390.84 | 390.60 | 202301 | +21.88 | -5.07 | +7.81 | -1.99 | +0.84 | -1.24 | +21.53 | 1 | 77.0% | 0.1559 | 0.1559 | 77.0% | 0.0% | 100,000.00 |
| 2023-01-17 | 391.90 | 390.12 | 202301 | +18.26 | -5.07 | +7.35 | -0.85 | +0.02 | -1.21 | +18.02 | 1 | 77.7% | 0.1544 | 0.1543 | 76.6% | 76.6% | 100,272.57 |
| 2023-01-18 | 389.60 | 391.53 | 202301 | +8.57 | -5.07 | +6.98 | -0.51 | -0.19 | -1.71 | +9.07 | 1 | 77.1% | 0.1557 | 0.1534 | 76.5% | 76.5% | 99,823.01 |
| 2023-01-19 | 383.95 | 386.94 | 202301 | +0.39 | -5.07 | +6.95 | -1.60 | +0.53 | -1.72 | +1.31 | 1 | 76.8% | 0.1544 | 0.1562 | 76.2% | 76.2% | 98,714.98 |
| 2023-01-20 | 386.80 | 384.83 | 202301 | +4.81 | -5.07 | +6.73 | -1.18 | +0.22 | -2.04 | +6.15 | 1 | 76.5% | 0.1452 | 0.1569 | 76.4% | 76.4% | 99,273.32 |
| 2023-01-23 | 392.68 | 387.67 | 202301 | +8.86 | -5.07 | +6.82 | +0.84 | -0.97 | -2.17 | +9.41 | 1 | 75.4% | 0.1533 | 0.1592 | 76.6% | 76.6% | 100,426.16 |
| 2023-01-24 | 391.72 | 392.10 | 202301 | +3.30 | -5.07 | +6.87 | +1.19 | -1.17 | -1.84 | +3.31 | 1 | 75.6% | 0.1540 | 0.1587 | 76.6% | 76.6% | 100,237.04 |
| 2023-01-25 | 388.71 | 391.22 | 202301 | -1.15 | -5.07 | +6.94 | +0.84 | -0.98 | -1.74 | -1.13 | 0 | 0.0% | 0.1556 | 0.1593 | 0.0% | 76.5% | 99,648.35 |
| 2023-01-26 | 393.32 | 392.23 | 202301 | +3.97 | -5.07 | +6.53 | +1.42 | -1.24 | -2.26 | +4.59 | 0 | 0.0% | 0.1583 | 0.1607 | 0.0% | 0.0% | 100,260.55 |
| 2023-01-27 | 396.75 | 394.50 | 202301 | +14.52 | -5.07 | +7.36 | +1.14 | -1.15 | -2.36 | +14.60 | 0 | 0.0% | 0.1535 | 0.1601 | 0.0% | 0.0% | 100,260.55 |
| 2023-01-30 | 394.93 | 394.66 | 202301 | +17.23 | -5.07 | +7.78 | -0.07 | -0.49 | -1.95 | +17.04 | 0 | 0.0% | 0.1365 | 0.1594 | 0.0% | 0.0% | 100,260.55 |
| 2023-01-31 | 394.63 | 393.99 | 202301 | +15.61 | -5.07 | +7.48 | +0.16 | -0.65 | -0.97 | +14.66 | 0 | 0.0% | 0.1302 | 0.1592 | 0.0% | 0.0% | 100,260.55 |
| 2023-02-01 | 393.93 | 395.84 | 202302 | +8.62 | -5.57 | +7.28 | +0.74 | -0.48 | -1.06 | +7.71 | 0 | 0.0% | 0.1280 | 0.1580 | 0.0% | 0.0% | 100,260.55 |
| 2023-02-02 | 403.47 | 397.22 | 202302 | +28.46 | -5.57 | +8.84 | +1.62 | -0.61 | -0.90 | +25.08 | 1 | 73.3% | 0.1477 | 0.1637 | 73.3% | 0.0% | 100,260.55 |
| 2023-02-03 | 405.81 | 401.45 | 202302 | +15.36 | -5.57 | +8.31 | +3.70 | -0.38 | -1.10 | +10.40 | 1 | 76.1% | 0.1460 | 0.1577 | 73.1% | 73.1% | 100,980.94 |
| 2023-02-06 | 403.61 | 402.30 | 202302 | +10.47 | -5.57 | +8.06 | +3.13 | -0.53 | -1.38 | +6.76 | 1 | 75.9% | 0.1482 | 0.1580 | 73.0% | 73.0% | 100,581.92 |
| 2023-02-07 | 404.46 | 403.58 | 202302 | +6.64 | -5.57 | +8.22 | +3.45 | -0.45 | -1.52 | +2.51 | 1 | 76.0% | 0.1400 | 0.1579 | 73.1% | 73.1% | 100,736.88 |
| 2023-02-08 | 403.79 | 406.92 | 202302 | +1.40 | -5.57 | +8.21 | +3.62 | -0.37 | -1.65 | -2.83 | 1 | 76.2% | 0.1379 | 0.1576 | 76.2% | 73.0% | 100,614.24 |
| 2023-02-09 | 404.51 | 406.50 | 202302 | +5.67 | -5.57 | +8.75 | +2.71 | -0.57 | -2.13 | +2.48 | 1 | 77.5% | 0.1379 | 0.1549 | 75.9% | 75.9% | 100,729.12 |
| 2023-02-10 | 402.25 | 400.92 | 202302 | +4.35 | -5.57 | +8.62 | +1.90 | -0.62 | -2.01 | +2.03 | 1 | 77.4% | 0.1405 | 0.1550 | 75.8% | 75.8% | 100,301.78 |
| 2023-02-13 | 405.17 | 402.56 | 202302 | +2.14 | -5.57 | +8.31 | +3.04 | -0.54 | -2.60 | -0.50 | 1 | 77.4% | 0.1414 | 0.1550 | 75.9% | 75.9% | 100,852.50 |
| 2023-02-14 | 403.23 | 405.66 | 202302 | -0.24 | -5.57 | +7.79 | +2.97 | -0.56 | -2.85 | -2.02 | 0 | 0.0% | 0.1432 | 0.1553 | 0.0% | 75.8% | 100,486.40 |
| 2023-02-15 | 406.83 | 403.86 | 202302 | -0.72 | -5.57 | +7.74 | +4.18 | -0.28 | -3.06 | -3.73 | 0 | 0.0% | 0.1428 | 0.1556 | 0.0% | 0.0% | 100,529.85 |
| 2023-02-16 | 406.70 | 408.83 | 202302 | -0.20 | -5.57 | +7.66 | +4.36 | -0.23 | -3.38 | -3.04 | 0 | 0.0% | 0.1289 | 0.1555 | 0.0% | 0.0% | 100,529.85 |
| 2023-02-17 | 401.82 | 403.14 | 202302 | +5.87 | -5.57 | +7.10 | +3.53 | -0.46 | -3.12 | +4.39 | 0 | 0.0% | 0.1381 | 0.1575 | 0.0% | 0.0% | 100,529.85 |
| 2023-02-20 | 402.19 | 402.73 | 202302 | +6.56 | -5.57 | +7.57 | +3.43 | -0.47 | -2.88 | +4.48 | 0 | 0.0% | 0.1290 | 0.1575 | 0.0% | 0.0% | 100,529.85 |
| 2023-02-21 | 398.51 | 401.77 | 202302 | +9.77 | -5.57 | +7.45 | +2.13 | -0.62 | -2.31 | +8.68 | 0 | 0.0% | 0.1336 | 0.1579 | 0.0% | 0.0% | 100,529.85 |
| 2023-02-22 | 398.38 | 397.81 | 202302 | +9.48 | -5.57 | +7.95 | +1.55 | -0.61 | -2.29 | +8.44 | 0 | 0.0% | 0.1299 | 0.1574 | 0.0% | 0.0% | 100,529.85 |
| 2023-02-23 | 398.28 | 399.56 | 202302 | +10.98 | -5.57 | +7.76 | +2.01 | -0.62 | -2.93 | +10.34 | 0 | 0.0% | 0.1238 | 0.1568 | 0.0% | 0.0% | 100,529.85 |
| 2023-02-24 | 396.07 | 400.42 | 202302 | +13.60 | -5.57 | +7.51 | +2.33 | -0.61 | -3.28 | +13.23 | 0 | 0.0% | 0.1218 | 0.1560 | 0.0% | 0.0% | 100,529.85 |
| 2023-02-27 | 398.14 | 399.11 | 202302 | +14.18 | -5.57 | +7.72 | +2.43 | -0.60 | -2.79 | +12.99 | 0 | 0.0% | 0.1220 | 0.1562 | 0.0% | 0.0% | 100,529.85 |
| 2023-02-28 | 397.06 | 396.58 | 202302 | +14.45 | -5.57 | +7.88 | +1.58 | -0.61 | -2.62 | +13.79 | 0 | 0.0% | 0.1224 | 0.1553 | 0.0% | 0.0% | 100,529.85 |
| 2023-03-01 | 392.76 | 396.69 | 202303 | +10.44 | -5.89 | +6.12 | -0.38 | -0.25 | -2.45 | +13.28 | 0 | 0.0% | 0.1286 | 0.1543 | 0.0% | 0.0% | 100,529.85 |
| 2023-03-02 | 394.72 | 391.58 | 202303 | +9.02 | -5.89 | +6.84 | -0.51 | -0.17 | -1.84 | +10.59 | 0 | 0.0% | 0.0946 | 0.1541 | 0.0% | 0.0% | 100,529.85 |
| 2023-03-03 | 401.16 | 397.71 | 202303 | +7.12 | -5.89 | +7.51 | +0.86 | -0.91 | -1.97 | +7.53 | 0 | 0.0% | 0.1105 | 0.1575 | 0.0% | 0.0% | 100,529.85 |
| 2023-03-06 | 402.78 | 402.68 | 202303 | +7.57 | -5.89 | +7.35 | +1.50 | -1.12 | -2.32 | +8.06 | 0 | 0.0% | 0.1101 | 0.1574 | 0.0% | 0.0% | 100,529.85 |
| 2023-03-07 | 400.39 | 401.45 | 202303 | +8.63 | -5.89 | +7.14 | +0.71 | -0.83 | -2.36 | +9.86 | 0 | 0.0% | 0.1117 | 0.1577 | 0.0% | 0.0% | 100,529.85 |
| 2023-03-08 | 399.48 | 400.02 | 202303 | +10.33 | -5.89 | +6.49 | +1.56 | -1.14 | -2.23 | +11.54 | 0 | 0.0% | 0.1118 | 0.1552 | 0.0% | 0.0% | 100,529.85 |
| 2023-03-09 | 399.92 | 400.00 | 202303 | +10.06 | -5.89 | +6.68 | +1.49 | -1.12 | -2.44 | +11.33 | 0 | 0.0% | 0.1116 | 0.1551 | 0.0% | 0.0% | 100,529.85 |
| 2023-03-10 | 391.28 | 390.00 | 202303 | +9.41 | -5.89 | +7.36 | -3.07 | +2.08 | -0.72 | +9.64 | 0 | 0.0% | 0.1340 | 0.1438 | 0.0% | 0.0% | 100,529.85 |
| 2023-03-13 | 381.81 | 387.24 | 202303 | +9.24 | -5.89 | +6.32 | -5.83 | +5.38 | +0.73 | +8.54 | 0 | 0.0% | 0.1529 | 0.1517 | 0.0% | 0.0% | 100,529.85 |
| 2023-03-14 | 387.55 | 382.90 | 202303 | +7.48 | -5.89 | +7.18 | -4.99 | +4.28 | +0.90 | +6.00 | 0 | 0.0% | 0.1653 | 0.1544 | 0.0% | 0.0% | 100,529.85 |
| 2023-03-15 | 384.32 | 385.85 | 202303 | +5.87 | -5.89 | +6.82 | -6.11 | +5.68 | +1.20 | +4.16 | 0 | 0.0% | 0.1616 | 0.1553 | 0.0% | 0.0% | 100,529.85 |
| 2023-03-16 | 389.30 | 387.42 | 202303 | +9.45 | -5.89 | +6.54 | -3.54 | +2.58 | +1.38 | +8.37 | 0 | 0.0% | 0.1709 | 0.1534 | 0.0% | 0.0% | 100,529.85 |
| 2023-03-17 | 386.23 | 391.55 | 202303 | +3.32 | -5.89 | +6.81 | -5.65 | +5.02 | +1.19 | +1.84 | 0 | 0.0% | 0.1683 | 0.1509 | 0.0% | 0.0% | 100,529.85 |
| 2023-03-20 | 386.00 | 384.57 | 202303 | +2.12 | -5.89 | +6.65 | -5.61 | +4.98 | +1.03 | +0.95 | 0 | 0.0% | 0.1680 | 0.1509 | 0.0% | 0.0% | 100,529.85 |
| 2023-03-21 | 389.63 | 388.88 | 202303 | +0.73 | -5.89 | +7.00 | -4.77 | +3.95 | +0.72 | -0.29 | 0 | 0.0% | 0.1704 | 0.1521 | 0.0% | 0.0% | 100,529.85 |
| 2023-03-22 | 390.27 | 390.45 | 202303 | +0.35 | -5.89 | +7.11 | -5.27 | +4.48 | +0.76 | -0.84 | 0 | 0.0% | 0.1707 | 0.1515 | 0.0% | 0.0% | 100,529.85 |
| 2023-03-23 | 387.22 | 384.94 | 202303 | -1.26 | -5.89 | +6.40 | -5.35 | +4.60 | +0.46 | -1.48 | 0 | 0.0% | 0.1724 | 0.1518 | 0.0% | 0.0% | 100,529.85 |
| 2023-03-24 | 386.12 | 386.30 | 202303 | -2.08 | -5.89 | +6.83 | -6.57 | +6.16 | +0.78 | -3.39 | 0 | 0.0% | 0.1718 | 0.1504 | 0.0% | 0.0% | 100,529.85 |
| 2023-03-27 | 389.20 | 390.61 | 202303 | +0.99 | -5.89 | +5.98 | -3.85 | +2.96 | +0.85 | +0.93 | 0 | 0.0% | 0.1734 | 0.1441 | 0.0% | 0.0% | 100,529.85 |
| 2023-03-28 | 387.16 | 389.97 | 202303 | -0.74 | -5.89 | +6.29 | -5.22 | +4.55 | +0.59 | -1.06 | 0 | 0.0% | 0.1739 | 0.1430 | 0.0% | 0.0% | 100,529.85 |
| 2023-03-29 | 391.18 | 390.50 | 202303 | +2.14 | -5.89 | +6.22 | -3.52 | +2.66 | +0.19 | +2.48 | 0 | 0.0% | 0.1747 | 0.1434 | 0.0% | 0.0% | 100,529.85 |
| 2023-03-30 | 393.05 | 393.39 | 202303 | +7.62 | -5.89 | +6.82 | -3.70 | +2.85 | +0.39 | +7.14 | 0 | 0.0% | 0.1746 | 0.1430 | 0.0% | 0.0% | 100,529.85 |
| 2023-03-31 | 397.34 | 394.17 | 202303 | +11.14 | -5.89 | +6.74 | -1.96 | +1.20 | +0.24 | +10.81 | 0 | 0.0% | 0.1689 | 0.1434 | 0.0% | 0.0% | 100,529.85 |
| 2023-04-03 | 398.57 | 400.23 | 202304 | +7.07 | -5.49 | +5.26 | -1.18 | +0.58 | +0.14 | +7.76 | 0 | 0.0% | 0.1686 | 0.1430 | 0.0% | 0.0% | 100,529.85 |
| 2023-04-04 | 396.21 | 399.73 | 202304 | +8.97 | -5.49 | +5.46 | -2.81 | +2.07 | +0.41 | +9.32 | 0 | 0.0% | 0.1686 | 0.1417 | 0.0% | 0.0% | 100,529.85 |
| 2023-04-05 | 395.23 | 396.29 | 202304 | +4.72 | -5.49 | +4.69 | -2.17 | +1.45 | +0.17 | +6.07 | 0 | 0.0% | 0.1686 | 0.1404 | 0.0% | 0.0% | 100,529.85 |
| 2023-04-06 | 395.59 | 396.03 | 202304 | +4.65 | -5.49 | +4.60 | -1.94 | +1.25 | -0.01 | +6.24 | 0 | 0.0% | 0.1686 | 0.1403 | 0.0% | 0.0% | 100,529.85 |
| 2023-04-11 | 398.27 | 399.41 | 202304 | +6.90 | -5.49 | +4.92 | -1.15 | +0.58 | -0.11 | +8.15 | 0 | 0.0% | 0.1502 | 0.1409 | 0.0% | 0.0% | 100,529.85 |
| 2023-04-12 | 396.65 | 398.11 | 202304 | +3.02 | -5.49 | +4.37 | -1.08 | +0.54 | -0.48 | +5.16 | 0 | 0.0% | 0.1186 | 0.1408 | 0.0% | 0.0% | 100,529.85 |
| 2023-04-13 | 395.95 | 396.43 | 202304 | +1.72 | -5.49 | +4.14 | -1.03 | +0.51 | -0.44 | +4.05 | 0 | 0.0% | 0.1087 | 0.1408 | 0.0% | 0.0% | 100,529.85 |
| 2023-04-14 | 398.74 | 397.64 | 202304 | +6.58 | -5.49 | +4.94 | -0.97 | +0.47 | -0.57 | +8.20 | 0 | 0.0% | 0.1046 | 0.1409 | 0.0% | 0.0% | 100,529.85 |
| 2023-04-17 | 400.68 | 400.25 | 202304 | +14.53 | -5.49 | +5.91 | -1.91 | +1.29 | -0.76 | +15.50 | 0 | 0.0% | 0.0969 | 0.1376 | 0.0% | 0.0% | 100,529.85 |
| 2023-04-18 | 401.21 | 402.32 | 202304 | +13.01 | -5.49 | +5.57 | -1.27 | +0.71 | -0.67 | +14.16 | 0 | 0.0% | 0.0905 | 0.1369 | 0.0% | 0.0% | 100,529.85 |
| 2023-04-19 | 400.61 | 400.84 | 202304 | +5.88 | -5.49 | +4.65 | -0.12 | -0.10 | -1.15 | +8.09 | 0 | 0.0% | 0.0908 | 0.1336 | 0.0% | 0.0% | 100,529.85 |
| 2023-04-20 | 399.43 | 400.52 | 202304 | +5.44 | -5.49 | +4.63 | -0.65 | +0.26 | -1.18 | +7.86 | 0 | 0.0% | 0.0878 | 0.1337 | 0.0% | 0.0% | 100,529.85 |
| 2023-04-21 | 399.35 | 399.91 | 202304 | +8.37 | -5.49 | +5.10 | -1.40 | +0.86 | -1.40 | +10.70 | 0 | 0.0% | 0.0879 | 0.1326 | 0.0% | 0.0% | 100,529.85 |
| 2023-04-24 | 397.69 | 398.37 | 202304 | +1.88 | -5.49 | +4.08 | -0.76 | +0.37 | -1.87 | +5.55 | 0 | 0.0% | 0.0838 | 0.1308 | 0.0% | 0.0% | 100,529.85 |
| 2023-04-25 | 396.91 | 396.74 | 202304 | -1.46 | -5.49 | +3.45 | -0.19 | -0.03 | -2.17 | +2.98 | 0 | 0.0% | 0.0833 | 0.1297 | 0.0% | 0.0% | 100,529.85 |
| 2023-04-26 | 392.95 | 395.01 | 202304 | -2.99 | -5.49 | +3.24 | -1.46 | +0.94 | -2.20 | +1.98 | 0 | 0.0% | 0.0888 | 0.1310 | 0.0% | 0.0% | 100,529.85 |
| 2023-04-27 | 394.94 | 392.72 | 202304 | -1.28 | -5.49 | +3.69 | -1.08 | +0.62 | -1.74 | +2.72 | 0 | 0.0% | 0.0875 | 0.1314 | 0.0% | 0.0% | 100,529.85 |
| 2023-04-28 | 398.59 | 397.32 | 202304 | +2.79 | -5.49 | +4.33 | -0.47 | +0.14 | -1.70 | +5.98 | 0 | 0.0% | 0.0860 | 0.1327 | 0.0% | 0.0% | 100,529.85 |
| 2023-05-02 | 394.73 | 400.92 | 202305 | -0.61 | -5.63 | +3.92 | +0.77 | -0.42 | -1.47 | +2.24 | 0 | 0.0% | 0.0925 | 0.1246 | 0.0% | 0.0% | 100,529.85 |
| 2023-05-03 | 395.10 | 396.49 | 202305 | +0.14 | -5.63 | +4.14 | +1.35 | -0.58 | -1.81 | +2.67 | 0 | 0.0% | 0.0837 | 0.1240 | 0.0% | 0.0% | 100,529.85 |
| 2023-05-04 | 392.24 | 392.86 | 202305 | +0.84 | -5.63 | +4.13 | +0.41 | -0.30 | -1.69 | +3.93 | 0 | 0.0% | 0.0862 | 0.1244 | 0.0% | 0.0% | 100,529.85 |
| 2023-05-05 | 397.43 | 393.22 | 202305 | -0.98 | -5.63 | +3.76 | +1.69 | -0.63 | -2.01 | +1.84 | 0 | 0.0% | 0.0971 | 0.1274 | 0.0% | 0.0% | 100,529.85 |
| 2023-05-08 | 399.08 | 397.83 | 202305 | -1.67 | -5.63 | +3.76 | +1.92 | -0.65 | -2.44 | +1.37 | 0 | 0.0% | 0.0975 | 0.1277 | 0.0% | 0.0% | 100,529.85 |
| 2023-05-09 | 400.35 | 399.48 | 202305 | -2.03 | -5.63 | +3.79 | +2.33 | -0.67 | -2.95 | +1.10 | 0 | 0.0% | 0.0980 | 0.1278 | 0.0% | 0.0% | 100,529.85 |
| 2023-05-10 | 399.62 | 399.80 | 202305 | -2.01 | -5.63 | +3.91 | +1.76 | -0.64 | -2.93 | +1.52 | 0 | 0.0% | 0.0955 | 0.1273 | 0.0% | 0.0% | 100,529.85 |
| 2023-05-11 | 400.76 | 402.64 | 202305 | -1.61 | -5.63 | +3.85 | +2.57 | -0.66 | -3.22 | +1.47 | 0 | 0.0% | 0.0946 | 0.1266 | 0.0% | 0.0% | 100,529.85 |
| 2023-05-12 | 402.15 | 402.06 | 202305 | -1.90 | -5.63 | +3.99 | +2.48 | -0.66 | -3.21 | +1.14 | 0 | 0.0% | 0.0948 | 0.1264 | 0.0% | 0.0% | 100,529.85 |
| 2023-05-15 | 403.29 | 403.89 | 202305 | -0.82 | -5.63 | +3.91 | +3.38 | -0.52 | -3.16 | +1.21 | 0 | 0.0% | 0.0922 | 0.1252 | 0.0% | 0.0% | 100,529.85 |
| 2023-05-16 | 402.71 | 402.76 | 202305 | -0.17 | -5.63 | +3.91 | +3.28 | -0.55 | -3.81 | +2.64 | 0 | 0.0% | 0.0910 | 0.1252 | 0.0% | 0.0% | 100,529.85 |
| 2023-05-17 | 403.73 | 401.86 | 202305 | -1.56 | -5.63 | +4.44 | +2.55 | -0.66 | -3.93 | +1.67 | 0 | 0.0% | 0.0913 | 0.1228 | 0.0% | 0.0% | 100,529.85 |
| 2023-05-18 | 409.46 | 406.25 | 202305 | -1.97 | -5.63 | +4.92 | +3.67 | -0.44 | -4.01 | -0.48 | 0 | 0.0% | 0.1032 | 0.1261 | 0.0% | 0.0% | 100,529.85 |
| 2023-05-19 | 409.29 | 410.91 | 202305 | -1.20 | -5.63 | +5.48 | +2.89 | -0.62 | -3.98 | +0.67 | 0 | 0.0% | 0.1023 | 0.1246 | 0.0% | 0.0% | 100,529.85 |
| 2023-05-22 | 410.80 | 409.72 | 202305 | -1.25 | -5.63 | +5.67 | +3.09 | -0.59 | -4.31 | +0.52 | 0 | 0.0% | 0.1025 | 0.1248 | 0.0% | 0.0% | 100,529.85 |
| 2023-05-23 | 409.86 | 409.61 | 202305 | -1.39 | -5.63 | +5.55 | +2.85 | -0.63 | -4.81 | +1.29 | 0 | 0.0% | 0.1013 | 0.1249 | 0.0% | 0.0% | 100,529.85 |
| 2023-05-24 | 403.39 | 405.68 | 202305 | -0.07 | -5.63 | +4.99 | +1.14 | -0.51 | -4.98 | +4.93 | 0 | 0.0% | 0.1183 | 0.1288 | 0.0% | 0.0% | 100,529.85 |
| 2023-05-25 | 405.22 | 405.81 | 202305 | +0.65 | -5.63 | +5.00 | +1.84 | -0.64 | -4.55 | +4.63 | 0 | 0.0% | 0.1117 | 0.1286 | 0.0% | 0.0% | 100,529.85 |
| 2023-05-26 | 410.83 | 406.57 | 202305 | +0.90 | -5.63 | +5.60 | +2.57 | -0.66 | -3.27 | +2.29 | 0 | 0.0% | 0.1193 | 0.1314 | 0.0% | 0.0% | 100,529.85 |
| 2023-05-29 | 412.36 | 412.43 | 202305 | +1.39 | -5.63 | +6.14 | +1.92 | -0.65 | -3.59 | +3.21 | 0 | 0.0% | 0.1165 | 0.1293 | 0.0% | 0.0% | 100,529.85 |
| 2023-05-30 | 410.20 | 412.70 | 202305 | +1.07 | -5.63 | +5.77 | +1.80 | -0.64 | -3.81 | +3.57 | 0 | 0.0% | 0.1117 | 0.1296 | 0.0% | 0.0% | 100,529.85 |
| 2023-05-31 | 407.88 | 409.46 | 202305 | +4.26 | -5.63 | +4.70 | +2.56 | -0.66 | -3.75 | +7.04 | 0 | 0.0% | 0.1149 | 0.1261 | 0.0% | 0.0% | 100,529.85 |
| 2023-06-01 | 408.12 | 409.97 | 202306 | +10.93 | -6.27 | +4.99 | +2.90 | -0.43 | -2.95 | +12.69 | 0 | 0.0% | 0.1101 | 0.1259 | 0.0% | 0.0% | 100,529.85 |
| 2023-06-02 | 417.46 | 412.00 | 202306 | +5.83 | -6.27 | +5.43 | +4.17 | -0.10 | -2.81 | +5.41 | 0 | 0.0% | 0.1268 | 0.1333 | 0.0% | 0.0% | 100,529.85 |
| 2023-06-05 | 418.70 | 418.71 | 202306 | +5.99 | -6.27 | +5.42 | +4.17 | -0.13 | -3.04 | +5.84 | 0 | 0.0% | 0.1266 | 0.1333 | 0.0% | 0.0% | 100,529.85 |
| 2023-06-06 | 419.21 | 417.40 | 202306 | +6.57 | -6.27 | +5.41 | +4.30 | -0.11 | -3.71 | +6.95 | 0 | 0.0% | 0.1267 | 0.1333 | 0.0% | 0.0% | 100,529.85 |
| 2023-06-07 | 418.45 | 419.21 | 202306 | +5.64 | -6.27 | +5.64 | +2.10 | -0.49 | -3.27 | +7.94 | 0 | 0.0% | 0.1267 | 0.1248 | 0.0% | 0.0% | 100,529.85 |
| 2023-06-08 | 416.24 | 416.70 | 202306 | +6.07 | -6.27 | +5.37 | -0.85 | +0.14 | -2.14 | +9.83 | 0 | 0.0% | 0.1295 | 0.1137 | 0.0% | 0.0% | 100,529.85 |
| 2023-06-09 | 418.32 | 417.08 | 202306 | +5.61 | -6.27 | +5.82 | +0.60 | -0.34 | -2.15 | +7.96 | 0 | 0.0% | 0.1298 | 0.1104 | 0.0% | 0.0% | 100,529.85 |
| 2023-06-12 | 419.49 | 419.95 | 202306 | +6.43 | -6.27 | +5.52 | -0.19 | -0.15 | -1.65 | +9.18 | 0 | 0.0% | 0.1298 | 0.1086 | 0.0% | 0.0% | 100,529.85 |
| 2023-06-13 | 423.37 | 421.34 | 202306 | +6.98 | -6.27 | +5.58 | +1.18 | -0.47 | -0.73 | +7.70 | 0 | 0.0% | 0.1316 | 0.1072 | 0.0% | 0.0% | 100,529.85 |
| 2023-06-14 | 423.40 | 423.58 | 202306 | +8.06 | -6.27 | +5.06 | +0.17 | -0.34 | -0.28 | +9.73 | 0 | 0.0% | 0.1319 | 0.1055 | 0.0% | 0.0% | 100,529.85 |
| 2023-06-15 | 421.95 | 422.40 | 202306 | +7.30 | -6.27 | +5.25 | -0.45 | -0.19 | -0.24 | +9.21 | 0 | 0.0% | 0.1258 | 0.1059 | 0.0% | 0.0% | 100,529.85 |
| 2023-06-16 | 423.83 | 422.82 | 202306 | +6.79 | -6.27 | +5.45 | +0.57 | -0.41 | -0.64 | +8.08 | 0 | 0.0% | 0.1260 | 0.1048 | 0.0% | 0.0% | 100,529.85 |
| 2023-06-19 | 421.31 | 422.18 | 202306 | +7.02 | -6.27 | +5.79 | -0.07 | -0.28 | -0.45 | +8.30 | 0 | 0.0% | 0.1286 | 0.1058 | 0.0% | 0.0% | 100,529.85 |
| 2023-06-20 | 419.36 | 420.55 | 202306 | +5.77 | -6.27 | +5.70 | -1.29 | +0.18 | -0.70 | +8.14 | 0 | 0.0% | 0.1297 | 0.1049 | 0.0% | 0.0% | 100,529.85 |
| 2023-06-21 | 417.26 | 419.37 | 202306 | +5.03 | -6.27 | +5.82 | -2.23 | +0.64 | -0.52 | +7.60 | 0 | 0.0% | 0.1158 | 0.1053 | 0.0% | 0.0% | 100,529.85 |
| 2023-06-22 | 416.35 | 414.46 | 202306 | +6.83 | -6.27 | +6.04 | -2.07 | +0.48 | +0.05 | +8.60 | 0 | 0.0% | 0.1161 | 0.1046 | 0.0% | 0.0% | 100,529.85 |
| 2023-06-23 | 415.81 | 415.93 | 202306 | +5.04 | -6.27 | +5.97 | -2.79 | +0.93 | -0.15 | +7.35 | 0 | 0.0% | 0.1067 | 0.1039 | 0.0% | 0.0% | 100,529.85 |
| 2023-06-26 | 414.91 | 415.55 | 202306 | +7.07 | -6.27 | +6.12 | -2.25 | +0.62 | -0.21 | +9.06 | 0 | 0.0% | 0.1064 | 0.1024 | 0.0% | 0.0% | 100,529.85 |
| 2023-06-27 | 414.42 | 414.71 | 202306 | +7.79 | -6.27 | +6.13 | -2.10 | +0.53 | -0.23 | +9.72 | 0 | 0.0% | 0.1046 | 0.1022 | 0.0% | 0.0% | 100,529.85 |
| 2023-06-28 | 418.51 | 416.84 | 202306 | +9.09 | -6.27 | +6.34 | -0.52 | -0.17 | -0.28 | +10.00 | 0 | 0.0% | 0.1069 | 0.1018 | 0.0% | 0.0% | 100,529.85 |
| 2023-06-29 | 420.05 | 418.59 | 202306 | +9.24 | -6.27 | +6.33 | -0.12 | -0.29 | -0.29 | +9.89 | 0 | 0.0% | 0.1071 | 0.1018 | 0.0% | 0.0% | 100,529.85 |
| 2023-06-30 | 423.63 | 421.46 | 202306 | +7.35 | -6.27 | +6.37 | -0.13 | -0.31 | +0.04 | +7.65 | 0 | 0.0% | 0.0778 | 0.1020 | 0.0% | 0.0% | 100,529.85 |
| 2023-07-03 | 424.61 | 425.49 | 202307 | +6.30 | -6.19 | +7.10 | -0.39 | -0.50 | +0.34 | +5.94 | 0 | 0.0% | 0.0776 | 0.1017 | 0.0% | 0.0% | 100,529.85 |
| 2023-07-04 | 425.23 | 425.01 | 202307 | +6.58 | -6.19 | +7.02 | -0.45 | -0.50 | +0.58 | +6.13 | 0 | 0.0% | 0.0776 | 0.1017 | 0.0% | 0.0% | 100,529.85 |
| 2023-07-05 | 424.96 | 424.13 | 202307 | +7.30 | -6.19 | +6.89 | -0.13 | -0.69 | +0.61 | +6.81 | 0 | 0.0% | 0.0772 | 0.1012 | 0.0% | 0.0% | 100,529.85 |
| 2023-07-06 | 417.90 | 422.83 | 202307 | +7.98 | -6.19 | +6.58 | -2.03 | +0.64 | +0.41 | +8.58 | 0 | 0.0% | 0.0972 | 0.1071 | 0.0% | 0.0% | 100,529.85 |
| 2023-07-07 | 417.80 | 418.12 | 202307 | +7.31 | -6.19 | +6.61 | -2.36 | +0.91 | +0.44 | +7.92 | 0 | 0.0% | 0.0956 | 0.1069 | 0.0% | 0.0% | 100,529.85 |
| 2023-07-10 | 416.21 | 415.03 | 202307 | +8.94 | -6.19 | +6.25 | -2.23 | +0.79 | +0.57 | +9.75 | 0 | 0.0% | 0.0958 | 0.1066 | 0.0% | 0.0% | 100,529.85 |
| 2023-07-11 | 417.91 | 416.86 | 202307 | +8.85 | -6.19 | +6.25 | -1.54 | +0.28 | +0.31 | +9.75 | 0 | 0.0% | 0.0906 | 0.1065 | 0.0% | 0.0% | 100,529.85 |
| 2023-07-12 | 419.85 | 418.87 | 202307 | +8.51 | -6.19 | +6.57 | -1.16 | +0.00 | +0.33 | +8.96 | 0 | 0.0% | 0.0925 | 0.1068 | 0.0% | 0.0% | 100,529.85 |
| 2023-07-13 | 420.00 | 419.84 | 202307 | +7.66 | -6.19 | +6.62 | -1.33 | +0.17 | -0.07 | +8.47 | 0 | 0.0% | 0.0919 | 0.1067 | 0.0% | 0.0% | 100,529.85 |
| 2023-07-14 | 419.96 | 420.11 | 202307 | +6.79 | -6.19 | +6.75 | -1.70 | +0.47 | -0.20 | +7.66 | 0 | 0.0% | 0.0902 | 0.1064 | 0.0% | 0.0% | 100,529.85 |
| 2023-07-17 | 419.40 | 418.19 | 202307 | +6.59 | -6.19 | +6.68 | -1.96 | +0.69 | -0.24 | +7.60 | 0 | 0.0% | 0.0879 | 0.1065 | 0.0% | 0.0% | 100,529.85 |
| 2023-07-18 | 421.86 | 419.01 | 202307 | +5.01 | -6.19 | +6.92 | -1.95 | +0.70 | -0.35 | +5.88 | 0 | 0.0% | 0.0888 | 0.1065 | 0.0% | 0.0% | 100,529.85 |
| 2023-07-19 | 425.60 | 424.12 | 202307 | +4.52 | -6.19 | +6.95 | -1.57 | +0.38 | -0.24 | +5.19 | 0 | 0.0% | 0.0914 | 0.1075 | 0.0% | 0.0% | 100,529.85 |
| 2023-07-20 | 425.76 | 423.42 | 202307 | +3.96 | -6.19 | +6.73 | -2.58 | +1.25 | -0.47 | +5.23 | 0 | 0.0% | 0.0906 | 0.1049 | 0.0% | 0.0% | 100,529.85 |
| 2023-07-21 | 426.19 | 425.08 | 202307 | +3.71 | -6.19 | +6.68 | -2.25 | +0.98 | -0.67 | +5.16 | 0 | 0.0% | 0.0902 | 0.1046 | 0.0% | 0.0% | 100,529.85 |
| 2023-07-24 | 428.03 | 424.64 | 202307 | +4.12 | -6.19 | +6.74 | -1.29 | +0.22 | -0.62 | +5.25 | 0 | 0.0% | 0.0899 | 0.1035 | 0.0% | 0.0% | 100,529.85 |
| 2023-07-25 | 430.14 | 428.63 | 202307 | +6.01 | -6.19 | +6.41 | -2.01 | +0.72 | -0.33 | +7.41 | 0 | 0.0% | 0.0900 | 0.1013 | 0.0% | 0.0% | 100,529.85 |
| 2023-07-26 | 428.55 | 430.10 | 202307 | +4.64 | -6.19 | +6.54 | -2.41 | +1.13 | -0.71 | +6.28 | 0 | 0.0% | 0.0869 | 0.1018 | 0.0% | 0.0% | 100,529.85 |
| 2023-07-27 | 434.76 | 430.49 | 202307 | +12.23 | -6.19 | +5.66 | -2.14 | +0.83 | -0.31 | +14.38 | 0 | 0.0% | 0.0986 | 0.1036 | 0.0% | 0.0% | 100,529.85 |
| 2023-07-28 | 433.39 | 432.32 | 202307 | +7.38 | -6.19 | +6.47 | -1.48 | +0.36 | -0.55 | +8.77 | 0 | 0.0% | 0.0966 | 0.1013 | 0.0% | 0.0% | 100,529.85 |
| 2023-07-31 | 433.30 | 433.01 | 202307 | +6.42 | -6.19 | +6.50 | -1.40 | +0.29 | -0.48 | +7.71 | 0 | 0.0% | 0.0966 | 0.1012 | 0.0% | 0.0% | 100,529.85 |
| 2023-08-01 | 433.32 | 434.96 | 202308 | +5.62 | -6.50 | +6.39 | -1.28 | +0.24 | -0.55 | +7.33 | 0 | 0.0% | 0.0967 | 0.1012 | 0.0% | 0.0% | 100,529.85 |
| 2023-08-02 | 428.63 | 429.67 | 202308 | +3.74 | -6.50 | +6.31 | -2.83 | +1.90 | -0.49 | +5.34 | 0 | 0.0% | 0.1053 | 0.1041 | 0.0% | 0.0% | 100,529.85 |
| 2023-08-03 | 426.36 | 427.33 | 202308 | +3.30 | -6.50 | +6.11 | -3.39 | +2.44 | -0.13 | +4.77 | 0 | 0.0% | 0.0868 | 0.1048 | 0.0% | 0.0% | 100,529.85 |
| 2023-08-04 | 425.74 | 427.55 | 202308 | +3.11 | -6.50 | +6.07 | -3.35 | +2.44 | -0.23 | +4.69 | 0 | 0.0% | 0.0871 | 0.1048 | 0.0% | 0.0% | 100,529.85 |
| 2023-08-07 | 424.95 | 425.39 | 202308 | +2.81 | -6.50 | +5.92 | -3.42 | +2.54 | -0.36 | +4.63 | 0 | 0.0% | 0.0860 | 0.1049 | 0.0% | 0.0% | 100,529.85 |
| 2023-08-08 | 424.01 | 425.16 | 202308 | +1.93 | -6.50 | +5.81 | -3.92 | +3.19 | -0.70 | +4.05 | 0 | 0.0% | 0.0859 | 0.1050 | 0.0% | 0.0% | 100,529.85 |
| 2023-08-09 | 423.71 | 427.21 | 202308 | +1.29 | -6.50 | +5.43 | -3.95 | +3.17 | -0.98 | +4.11 | 0 | 0.0% | 0.0848 | 0.1050 | 0.0% | 0.0% | 100,529.85 |
| 2023-08-10 | 425.61 | 424.66 | 202308 | +2.89 | -6.50 | +5.21 | -2.06 | +1.18 | -0.92 | +5.99 | 0 | 0.0% | 0.0860 | 0.1016 | 0.0% | 0.0% | 100,529.85 |
| 2023-08-11 | 422.83 | 423.85 | 202308 | +2.03 | -6.50 | +4.69 | -2.93 | +2.10 | -1.39 | +6.06 | 0 | 0.0% | 0.0897 | 0.1026 | 0.0% | 0.0% | 100,529.85 |
| 2023-08-14 | 425.31 | 423.66 | 202308 | +1.66 | -6.50 | +4.79 | -1.97 | +1.15 | -1.85 | +6.06 | 0 | 0.0% | 0.0916 | 0.1030 | 0.0% | 0.0% | 100,529.85 |
| 2023-08-15 | 422.28 | 425.87 | 202308 | +0.76 | -6.50 | +4.56 | -3.06 | +2.35 | -2.46 | +5.88 | 0 | 0.0% | 0.0935 | 0.1041 | 0.0% | 0.0% | 100,529.85 |
| 2023-08-16 | 421.69 | 421.17 | 202308 | -1.31 | -6.50 | +5.50 | -4.94 | +4.65 | -2.78 | +2.77 | 0 | 0.0% | 0.0876 | 0.0984 | 0.0% | 0.0% | 100,529.85 |
| 2023-08-17 | 418.95 | 420.17 | 202308 | -2.33 | -6.50 | +4.97 | -5.28 | +5.08 | -2.99 | +2.39 | 0 | 0.0% | 0.0901 | 0.0992 | 0.0% | 0.0% | 100,529.85 |
| 2023-08-18 | 415.57 | 416.49 | 202308 | +0.91 | -6.50 | +4.05 | -4.84 | +4.44 | -1.50 | +5.26 | 0 | 0.0% | 0.0934 | 0.0969 | 0.0% | 0.0% | 100,529.85 |
| 2023-08-21 | 415.88 | 416.36 | 202308 | +0.52 | -6.50 | +3.76 | -4.50 | +3.91 | -1.88 | +5.72 | 0 | 0.0% | 0.0914 | 0.0966 | 0.0% | 0.0% | 100,529.85 |
| 2023-08-22 | 419.83 | 417.87 | 202308 | -1.06 | -6.50 | +4.54 | -4.00 | +3.45 | -2.16 | +3.61 | 0 | 0.0% | 0.0969 | 0.0978 | 0.0% | 0.0% | 100,529.85 |
| 2023-08-23 | 422.53 | 420.31 | 202308 | +0.32 | -6.50 | +5.33 | -3.96 | +3.48 | -2.30 | +4.27 | 0 | 0.0% | 0.1000 | 0.0977 | 0.0% | 0.0% | 100,529.85 |
| 2023-08-24 | 420.70 | 426.04 | 202308 | -0.32 | -6.50 | +5.29 | -4.44 | +4.09 | -1.91 | +3.15 | 0 | 0.0% | 0.0832 | 0.0982 | 0.0% | 0.0% | 100,529.85 |
| 2023-08-25 | 420.82 | 420.29 | 202308 | +0.22 | -6.50 | +4.41 | -2.27 | +1.42 | -2.06 | +5.22 | 0 | 0.0% | 0.0832 | 0.0867 | 0.0% | 0.0% | 100,529.85 |
| 2023-08-28 | 424.20 | 422.64 | 202308 | -0.13 | -6.50 | +4.68 | -1.25 | +0.28 | -2.25 | +4.91 | 0 | 0.0% | 0.0897 | 0.0880 | 0.0% | 0.0% | 100,529.85 |
| 2023-08-29 | 427.73 | 425.56 | 202308 | -0.19 | -6.50 | +4.92 | -0.42 | -0.62 | -2.49 | +4.92 | 0 | 0.0% | 0.0957 | 0.0896 | 0.0% | 0.0% | 100,529.85 |
| 2023-08-30 | 427.60 | 428.54 | 202308 | -0.31 | -6.50 | +4.85 | -0.66 | -0.34 | -2.90 | +5.24 | 0 | 0.0% | 0.0877 | 0.0895 | 0.0% | 0.0% | 100,529.85 |
| 2023-08-31 | 430.82 | 429.31 | 202308 | +1.55 | -6.50 | +5.37 | -0.50 | -0.47 | -3.42 | +7.07 | 0 | 0.0% | 0.0894 | 0.0898 | 0.0% | 0.0% | 100,529.85 |
| 2023-09-01 | 432.80 | 430.68 | 202309 | -6.36 | -0.60 | -0.75 | +0.18 | -1.12 | -6.22 | +2.15 | 0 | 0.0% | 0.0902 | 0.0898 | 0.0% | 0.0% | 100,529.85 |
| 2023-09-04 | 432.96 | 434.16 | 202309 | -5.37 | -0.60 | -0.36 | +0.30 | -1.30 | -6.09 | +2.67 | 0 | 0.0% | 0.0897 | 0.0897 | 0.0% | 0.0% | 100,529.85 |
| 2023-09-05 | 434.50 | 432.56 | 202309 | -4.94 | -0.60 | +0.69 | +1.00 | -2.22 | -5.15 | +1.35 | 0 | 0.0% | 0.0894 | 0.0881 | 0.0% | 0.0% | 100,529.85 |
| 2023-09-06 | 430.96 | 432.50 | 202309 | +1.37 | -0.60 | +2.29 | +0.43 | -1.54 | -4.34 | +5.13 | 0 | 0.0% | 0.0952 | 0.0898 | 0.0% | 0.0% | 100,529.85 |
| 2023-09-07 | 430.10 | 430.05 | 202309 | +5.14 | -0.60 | +1.94 | +0.04 | -1.04 | -2.70 | +7.49 | 0 | 0.0% | 0.0947 | 0.0896 | 0.0% | 0.0% | 100,529.85 |
| 2023-09-08 | 431.12 | 430.58 | 202309 | +6.33 | -0.60 | +2.27 | +0.42 | -1.55 | -3.24 | +9.03 | 0 | 0.0% | 0.0911 | 0.0893 | 0.0% | 0.0% | 100,529.85 |
| 2023-09-11 | 430.88 | 431.36 | 202309 | +4.87 | -0.60 | +1.34 | -0.01 | -0.95 | -2.84 | +7.95 | 0 | 0.0% | 0.0894 | 0.0884 | 0.0% | 0.0% | 100,529.85 |
| 2023-09-12 | 431.16 | 432.42 | 202309 | +1.93 | -0.60 | +0.44 | -0.29 | -0.52 | -3.47 | +6.37 | 0 | 0.0% | 0.0845 | 0.0877 | 0.0% | 0.0% | 100,529.85 |
| 2023-09-13 | 431.05 | 429.95 | 202309 | -0.37 | -0.60 | -0.35 | -0.66 | +0.06 | -3.85 | +5.04 | 0 | 0.0% | 0.0842 | 0.0870 | 0.0% | 0.0% | 100,529.85 |
| 2023-09-14 | 436.46 | 432.00 | 202309 | -4.60 | -0.60 | -2.79 | -0.14 | -0.76 | -3.33 | +3.03 | 0 | 0.0% | 0.0883 | 0.0902 | 0.0% | 0.0% | 100,529.85 |
| 2023-09-15 | 434.67 | 439.02 | 202309 | -3.44 | -0.60 | -2.34 | -0.56 | -0.13 | -3.37 | +3.56 | 0 | 0.0% | 0.0832 | 0.0906 | 0.0% | 0.0% | 100,529.85 |
| 2023-09-18 | 432.62 | 434.42 | 202309 | -2.42 | -0.60 | -1.82 | -1.05 | +0.68 | -3.38 | +3.74 | 0 | 0.0% | 0.0867 | 0.0911 | 0.0% | 0.0% | 100,529.85 |
| 2023-09-19 | 430.71 | 432.55 | 202309 | -1.96 | -0.60 | -1.38 | -1.48 | +1.41 | -3.70 | +3.79 | 0 | 0.0% | 0.0848 | 0.0917 | 0.0% | 0.0% | 100,529.85 |
| 2023-09-20 | 431.88 | 431.97 | 202309 | -0.31 | -0.60 | -0.30 | -0.77 | +0.24 | -4.32 | +5.44 | 0 | 0.0% | 0.0828 | 0.0898 | 0.0% | 0.0% | 100,529.85 |
| 2023-09-21 | 424.99 | 429.11 | 202309 | +12.65 | -0.60 | +3.00 | -1.62 | +1.60 | -3.82 | +14.09 | 0 | 0.0% | 0.1014 | 0.0957 | 0.0% | 0.0% | 100,529.85 |
| 2023-09-22 | 424.81 | 423.33 | 202309 | +20.10 | -0.60 | +4.52 | -1.12 | +0.77 | -3.58 | +20.10 | 1 | 100.0% | 0.1015 | 0.0942 | 100.0% | 0.0% | 100,529.85 |
| 2023-09-25 | 424.75 | 423.41 | 202309 | +22.68 | -0.60 | +4.96 | -0.98 | +0.56 | -2.52 | +21.25 | 1 | 100.0% | 0.0975 | 0.0940 | 99.5% | 99.5% | 100,744.89 |
| 2023-09-26 | 421.42 | 423.51 | 202309 | +30.37 | -0.60 | +6.73 | -1.36 | +1.21 | -2.18 | +26.57 | 1 | 100.0% | 0.0963 | 0.0954 | 99.5% | 99.5% | 99,958.68 |
| 2023-09-27 | 422.47 | 421.92 | 202309 | +27.09 | -0.60 | +6.34 | -1.20 | +0.99 | -1.73 | +23.29 | 1 | 100.0% | 0.0970 | 0.0955 | 99.5% | 99.5% | 100,206.72 |
| 2023-09-28 | 422.93 | 423.19 | 202309 | +11.69 | -0.60 | +3.26 | -2.11 | +2.72 | -0.77 | +9.19 | 1 | 100.0% | 0.0924 | 0.0890 | 99.5% | 99.5% | 100,316.79 |
| 2023-09-29 | 423.77 | 423.44 | 202309 | +11.50 | -0.60 | +2.80 | -2.04 | +2.57 | +0.60 | +8.16 | 1 | 100.0% | 0.0908 | 0.0891 | 99.5% | 99.5% | 100,513.49 |
| 2023-10-02 | 423.67 | 423.38 | 202310 | +7.33 | -0.10 | +0.98 | -2.22 | +3.28 | +1.61 | +3.78 | 1 | 100.0% | 0.0907 | 0.0887 | 99.5% | 99.5% | 100,491.29 |
| 2023-10-03 | 417.94 | 423.17 | 202310 | +16.73 | -0.10 | +4.26 | -2.80 | +4.58 | +1.70 | +9.09 | 1 | 100.0% | 0.0991 | 0.0928 | 99.5% | 99.5% | 99,138.80 |
| 2023-10-04 | 416.94 | 415.61 | 202310 | +21.61 | -0.10 | +5.44 | -2.72 | +4.26 | +2.30 | +12.43 | 1 | 100.0% | 0.0964 | 0.0924 | 99.5% | 99.5% | 98,902.28 |
| 2023-10-05 | 416.76 | 418.90 | 202310 | +19.72 | -0.10 | +5.57 | -2.72 | +4.24 | +2.17 | +10.56 | 1 | 100.0% | 0.0965 | 0.0924 | 99.5% | 99.5% | 98,859.20 |
| 2023-10-06 | 419.23 | 418.34 | 202310 | +12.99 | -0.10 | +4.21 | -2.45 | +3.46 | +1.99 | +5.89 | 1 | 100.0% | 0.0992 | 0.0932 | 99.5% | 99.5% | 99,442.08 |
| 2023-10-09 | 422.10 | 420.30 | 202310 | +7.76 | -0.10 | +2.83 | -1.99 | +2.77 | +1.38 | +2.87 | 1 | 100.0% | 0.1034 | 0.0942 | 99.5% | 99.5% | 100,120.32 |
| 2023-10-10 | 427.87 | 425.46 | 202310 | +6.33 | -0.10 | +1.49 | -0.77 | +0.56 | +1.20 | +3.95 | 1 | 100.0% | 0.1157 | 0.0975 | 99.5% | 99.5% | 101,483.10 |
| 2023-10-11 | 426.18 | 426.44 | 202310 | +11.20 | -0.10 | +4.01 | -0.49 | +0.08 | +1.44 | +6.26 | 1 | 100.0% | 0.1164 | 0.0962 | 99.5% | 99.5% | 101,082.40 |
| 2023-10-12 | 429.45 | 429.14 | 202310 | +6.74 | -0.10 | +2.63 | -0.03 | -0.70 | +0.72 | +4.23 | 1 | 100.0% | 0.1103 | 0.0975 | 99.5% | 99.5% | 101,855.96 |
| 2023-10-13 | 426.89 | 428.30 | 202310 | +9.08 | -0.10 | +3.98 | -0.33 | -0.19 | +0.31 | +5.41 | 1 | 100.0% | 0.1113 | 0.0983 | 99.5% | 99.5% | 101,251.28 |
| 2023-10-16 | 428.77 | 426.63 | 202310 | +8.13 | -0.10 | +3.97 | +0.17 | -1.03 | -0.01 | +5.14 | 1 | 100.0% | 0.1118 | 0.0983 | 99.5% | 99.5% | 101,694.18 |
| 2023-10-17 | 427.69 | 428.27 | 202310 | +12.03 | -0.10 | +5.44 | +0.31 | -1.25 | -0.13 | +7.76 | 1 | 100.0% | 0.1111 | 0.0979 | 99.5% | 99.5% | 101,439.84 |
| 2023-10-18 | 425.47 | 426.44 | 202310 | +13.79 | -0.10 | +5.71 | -0.19 | -0.43 | -0.42 | +9.22 | 1 | 100.0% | 0.1118 | 0.0982 | 99.5% | 99.5% | 100,915.19 |
| 2023-10-19 | 420.80 | 422.14 | 202310 | +39.06 | -0.10 | +10.90 | +0.06 | -0.82 | +0.09 | +28.94 | 1 | 100.0% | 0.1037 | 0.0959 | 99.5% | 99.5% | 99,814.46 |
| 2023-10-20 | 413.24 | 416.35 | 202310 | +56.16 | -0.10 | +14.15 | -1.09 | +1.24 | +0.38 | +41.58 | 1 | 99.1% | 0.1211 | 0.1024 | 99.5% | 99.5% | 98,029.95 |
| 2023-10-23 | 411.75 | 413.08 | 202310 | +59.52 | -0.10 | +14.93 | -1.17 | +1.49 | +1.28 | +43.08 | 1 | 98.9% | 0.1213 | 0.1025 | 99.5% | 99.5% | 97,677.60 |
| 2023-10-24 | 414.21 | 410.59 | 202310 | +53.98 | -0.10 | +13.56 | -0.66 | +0.65 | +2.25 | +38.28 | 1 | 98.6% | 0.1217 | 0.1034 | 99.5% | 99.5% | 98,257.74 |
| 2023-10-25 | 412.31 | 413.04 | 202310 | +44.42 | -0.10 | +12.19 | -1.49 | +2.25 | +2.40 | +29.15 | 1 | 98.6% | 0.1217 | 0.1016 | 99.5% | 99.5% | 97,809.36 |
| 2023-10-26 | 409.03 | 407.97 | 202310 | +45.38 | -0.10 | +12.77 | -2.12 | +3.75 | +3.98 | +27.10 | 1 | 97.1% | 0.1236 | 0.1023 | 99.5% | 99.5% | 97,035.80 |
| 2023-10-27 | 405.38 | 408.14 | 202310 | +53.59 | -0.10 | +14.29 | -2.55 | +4.95 | +5.94 | +31.05 | 1 | 95.7% | 0.1254 | 0.1037 | 95.7% | 99.5% | 96,174.38 |
| 2023-10-30 | 405.86 | 407.32 | 202310 | +46.20 | -0.10 | +13.57 | -2.49 | +4.83 | +5.96 | +24.43 | 1 | 95.4% | 0.1258 | 0.1037 | 95.7% | 95.7% | 96,297.11 |
| 2023-10-31 | 409.76 | 406.11 | 202310 | +31.66 | -0.10 | +10.97 | -1.93 | +3.66 | +5.97 | +13.08 | 1 | 96.2% | 0.1247 | 0.1058 | 95.7% | 95.7% | 97,181.59 |
| 2023-11-01 | 414.12 | 411.01 | 202311 | +8.14 | -6.45 | +3.56 | -2.43 | +3.19 | +2.52 | +7.76 | 1 | 91.5% | 0.1311 | 0.1082 | 91.5% | 95.8% | 98,172.02 |
| 2023-11-02 | 420.29 | 415.98 | 202311 | +8.19 | -6.45 | +2.79 | -0.18 | +0.20 | +2.50 | +9.33 | 1 | 84.7% | 0.1417 | 0.1122 | 84.7% | 91.6% | 99,525.62 |
| 2023-11-03 | 422.35 | 421.40 | 202311 | +9.63 | -6.45 | +2.58 | -0.35 | +0.40 | +2.40 | +11.04 | 1 | 85.0% | 0.1412 | 0.1119 | 84.9% | 84.9% | 99,950.80 |
| 2023-11-06 | 421.22 | 421.95 | 202311 | +7.33 | -6.45 | +2.65 | +0.03 | -0.07 | +2.25 | +8.93 | 1 | 86.0% | 0.1395 | 0.1114 | 84.9% | 84.9% | 99,723.61 |
| 2023-11-07 | 423.82 | 421.21 | 202311 | +9.39 | -6.45 | +2.62 | -0.08 | +0.06 | +1.91 | +11.33 | 1 | 90.9% | 0.1321 | 0.1111 | 90.9% | 85.0% | 100,245.18 |
| 2023-11-08 | 422.35 | 422.79 | 202311 | +7.93 | -6.45 | +2.56 | -0.65 | +0.77 | +1.59 | +10.11 | 1 | 91.0% | 0.1319 | 0.1113 | 90.4% | 90.4% | 99,939.94 |
| 2023-11-09 | 424.29 | 423.27 | 202311 | +11.50 | -6.45 | +2.85 | -0.89 | +1.08 | +1.33 | +13.58 | 1 | 92.4% | 0.1298 | 0.1109 | 90.5% | 90.5% | 100,355.42 |
| 2023-11-10 | 423.27 | 422.70 | 202311 | +13.93 | -6.45 | +3.16 | -2.19 | +2.76 | +1.42 | +15.25 | 1 | 93.4% | 0.1285 | 0.1096 | 90.5% | 90.5% | 100,136.99 |
| 2023-11-13 | 425.86 | 424.78 | 202311 | +17.07 | -6.45 | +3.36 | -1.47 | +1.81 | +1.48 | +18.35 | 1 | 92.7% | 0.1295 | 0.1103 | 90.5% | 90.5% | 100,690.75 |
| 2023-11-14 | 428.88 | 426.02 | 202311 | +15.91 | -6.45 | +3.18 | +0.40 | -0.47 | +1.22 | +18.03 | 1 | 91.1% | 0.1318 | 0.1095 | 90.6% | 90.6% | 101,336.20 |
| 2023-11-15 | 430.05 | 429.23 | 202311 | +13.25 | -6.45 | +2.97 | +1.42 | -1.60 | +0.94 | +15.98 | 1 | 92.0% | 0.1305 | 0.1089 | 90.6% | 90.6% | 101,586.69 |
| 2023-11-16 | 427.81 | 429.64 | 202311 | +12.14 | -6.45 | +2.88 | +0.27 | -0.24 | +0.49 | +15.20 | 1 | 95.9% | 0.1252 | 0.1091 | 95.9% | 90.5% | 101,108.19 |
| 2023-11-17 | 429.37 | 430.74 | 202311 | +12.71 | -6.45 | +3.00 | +0.69 | -0.70 | +0.03 | +16.13 | 1 | 100.0% | 0.1034 | 0.1093 | 100.0% | 95.7% | 101,419.14 |
| 2023-11-20 | 429.58 | 428.51 | 202311 | +8.48 | -6.45 | +2.59 | +1.66 | -1.75 | -0.20 | +12.64 | 1 | 100.0% | 0.1015 | 0.1082 | 99.9% | 99.9% | 101,474.48 |
| 2023-11-21 | 429.89 | 430.09 | 202311 | +3.80 | -6.45 | +2.40 | +2.68 | -2.83 | -0.63 | +8.63 | 1 | 100.0% | 0.1006 | 0.1068 | 99.9% | 99.9% | 101,546.76 |
| 2023-11-22 | 433.53 | 430.76 | 202311 | +5.08 | -6.45 | +2.67 | +3.59 | -3.73 | -0.87 | +9.88 | 1 | 100.0% | 0.1001 | 0.1082 | 99.9% | 99.9% | 102,404.93 |
| 2023-11-23 | 433.03 | 432.67 | 202311 | -0.61 | -6.45 | +2.39 | +4.30 | -4.38 | -1.65 | +5.19 | 0 | 0.0% | 0.0933 | 0.1072 | 0.0% | 99.9% | 102,288.13 |
| 2023-11-24 | 432.22 | 432.52 | 202311 | -3.69 | -6.45 | +2.31 | +4.60 | -4.65 | -2.07 | +2.59 | 0 | 0.0% | 0.0844 | 0.1068 | 0.0% | 0.0% | 102,066.69 |
| 2023-11-27 | 431.76 | 431.24 | 202311 | -4.41 | -6.45 | +2.31 | +4.52 | -4.59 | -2.24 | +2.03 | 0 | 0.0% | 0.0855 | 0.1068 | 0.0% | 0.0% | 102,066.69 |
| 2023-11-28 | 430.83 | 430.68 | 202311 | -5.28 | -6.45 | +2.36 | +4.70 | -4.75 | -2.78 | +1.64 | 0 | 0.0% | 0.0838 | 0.1067 | 0.0% | 0.0% | 102,066.69 |
| 2023-11-29 | 431.37 | 430.49 | 202311 | -4.81 | -6.45 | +2.26 | +3.94 | -4.04 | -3.25 | +2.73 | 0 | 0.0% | 0.0783 | 0.1054 | 0.0% | 0.0% | 102,066.69 |
| 2023-11-30 | 432.99 | 432.57 | 202311 | -4.23 | -6.45 | +2.50 | +4.12 | -4.22 | -2.57 | +2.40 | 0 | 0.0% | 0.0627 | 0.1055 | 0.0% | 0.0% | 102,066.69 |
| 2023-12-01 | 438.07 | 435.37 | 202312 | -4.27 | -6.80 | +3.53 | +5.36 | -4.32 | -2.51 | +0.48 | 0 | 0.0% | 0.0715 | 0.1081 | 0.0% | 0.0% | 102,066.69 |
| 2023-12-04 | 437.29 | 438.04 | 202312 | -3.58 | -6.80 | +3.33 | +5.01 | -4.12 | -1.52 | +0.52 | 0 | 0.0% | 0.0708 | 0.1081 | 0.0% | 0.0% | 102,066.69 |
| 2023-12-05 | 439.49 | 437.38 | 202312 | -4.54 | -6.80 | +3.48 | +5.59 | -4.48 | -1.87 | -0.45 | 0 | 0.0% | 0.0700 | 0.1086 | 0.0% | 0.0% | 102,066.69 |
| 2023-12-06 | 440.33 | 441.20 | 202312 | -5.10 | -6.80 | +3.54 | +5.72 | -4.54 | -2.30 | -0.71 | 0 | 0.0% | 0.0672 | 0.1086 | 0.0% | 0.0% | 102,066.69 |
| 2023-12-07 | 440.66 | 439.45 | 202312 | -6.73 | -6.80 | +3.06 | +7.11 | -5.30 | -2.67 | -2.14 | 0 | 0.0% | 0.0667 | 0.1057 | 0.0% | 0.0% | 102,066.69 |
| 2023-12-08 | 443.27 | 441.20 | 202312 | -7.28 | -6.80 | +3.50 | +7.22 | -5.37 | -2.86 | -2.97 | 0 | 0.0% | 0.0661 | 0.1059 | 0.0% | 0.0% | 102,066.69 |
| 2023-12-11 | 445.15 | 444.27 | 202312 | -7.07 | -6.80 | +3.91 | +7.09 | -5.30 | -3.09 | -2.88 | 0 | 0.0% | 0.0650 | 0.1057 | 0.0% | 0.0% | 102,066.69 |
| 2023-12-12 | 444.87 | 445.73 | 202312 | -5.86 | -6.80 | +4.11 | +6.45 | -4.96 | -3.57 | -1.10 | 0 | 0.0% | 0.0631 | 0.1052 | 0.0% | 0.0% | 102,066.69 |
| 2023-12-13 | 446.76 | 446.87 | 202312 | -6.79 | -6.80 | +4.17 | +7.14 | -5.29 | -4.30 | -1.71 | 0 | 0.0% | 0.0636 | 0.1054 | 0.0% | 0.0% | 102,066.69 |
| 2023-12-14 | 446.57 | 450.67 | 202312 | -3.69 | -6.80 | +4.68 | +5.14 | -4.17 | -3.76 | +1.23 | 0 | 0.0% | 0.0586 | 0.0996 | 0.0% | 0.0% | 102,066.69 |
| 2023-12-15 | 449.70 | 448.12 | 202312 | -4.58 | -6.80 | +4.81 | +5.70 | -4.50 | -4.09 | +0.29 | 0 | 0.0% | 0.0609 | 0.1003 | 0.0% | 0.0% | 102,066.69 |
| 2023-12-18 | 449.78 | 449.17 | 202312 | -4.10 | -6.80 | +4.82 | +5.49 | -4.37 | -3.99 | +0.75 | 0 | 0.0% | 0.0610 | 0.1003 | 0.0% | 0.0% | 102,066.69 |
| 2023-12-19 | 450.26 | 450.46 | 202312 | -2.94 | -6.80 | +4.69 | +4.52 | -3.73 | -4.10 | +2.47 | 0 | 0.0% | 0.0609 | 0.0986 | 0.0% | 0.0% | 102,066.69 |
| 2023-12-20 | 451.81 | 451.58 | 202312 | -3.66 | -6.80 | +4.73 | +4.99 | -4.01 | -4.45 | +1.88 | 0 | 0.0% | 0.0567 | 0.0987 | 0.0% | 0.0% | 102,066.69 |
| 2023-12-21 | 448.19 | 448.79 | 202312 | -1.06 | -6.80 | +4.87 | +3.91 | -3.30 | -3.89 | +4.15 | 0 | 0.0% | 0.0664 | 0.1005 | 0.0% | 0.0% | 102,066.69 |
| 2023-12-22 | 449.72 | 448.52 | 202312 | -0.69 | -6.80 | +4.99 | +4.16 | -3.58 | -3.00 | +3.53 | 0 | 0.0% | 0.0652 | 0.1006 | 0.0% | 0.0% | 102,066.69 |
| 2023-12-27 | 448.33 | 450.31 | 202312 | +1.11 | -6.80 | +5.01 | +3.52 | -3.15 | -2.50 | +5.03 | 0 | 0.0% | 0.0669 | 0.1009 | 0.0% | 0.0% | 102,066.69 |
| 2023-12-28 | 450.13 | 449.94 | 202312 | +0.48 | -6.80 | +4.85 | +2.15 | -2.08 | -2.21 | +4.56 | 0 | 0.0% | 0.0655 | 0.0964 | 0.0% | 0.0% | 102,066.69 |
| 2023-12-29 | 448.84 | 451.18 | 202312 | +1.50 | -6.80 | +4.97 | +1.17 | -1.30 | -1.62 | +5.09 | 0 | 0.0% | 0.0679 | 0.0965 | 0.0% | 0.0% | 102,066.69 |
| 2024-01-02 | 451.01 | 452.22 | 202401 | +1.69 | -6.88 | +5.01 | +1.39 | -1.67 | -1.19 | +5.03 | 0 | 0.0% | 0.0683 | 0.0967 | 0.0% | 0.0% | 102,066.69 |
| 2024-01-03 | 449.04 | 450.74 | 202401 | +3.33 | -6.88 | +5.34 | +1.21 | -1.57 | -1.04 | +6.26 | 0 | 0.0% | 0.0618 | 0.0969 | 0.0% | 0.0% | 102,066.69 |
| 2024-01-04 | 448.80 | 448.85 | 202401 | +4.83 | -6.88 | +5.08 | +1.62 | -2.02 | -0.50 | +7.54 | 0 | 0.0% | 0.0611 | 0.0962 | 0.0% | 0.0% | 102,066.69 |
| 2024-01-05 | 447.83 | 446.85 | 202401 | +5.87 | -6.88 | +4.79 | +2.76 | -3.01 | -0.63 | +8.85 | 0 | 0.0% | 0.0607 | 0.0928 | 0.0% | 0.0% | 102,066.69 |
| 2024-01-08 | 448.72 | 447.28 | 202401 | +7.88 | -6.88 | +4.65 | +2.10 | -2.65 | +0.70 | +9.96 | 0 | 0.0% | 0.0607 | 0.0923 | 0.0% | 0.0% | 102,066.69 |
| 2024-01-09 | 452.00 | 451.68 | 202401 | +6.97 | -6.88 | +4.52 | +3.72 | -3.92 | +0.59 | +8.93 | 0 | 0.0% | 0.0647 | 0.0922 | 0.0% | 0.0% | 102,066.69 |
| 2024-01-10 | 452.09 | 452.39 | 202401 | +7.04 | -6.88 | +4.61 | +2.88 | -3.21 | +0.21 | +9.44 | 0 | 0.0% | 0.0624 | 0.0911 | 0.0% | 0.0% | 102,066.69 |
| 2024-01-11 | 450.25 | 454.73 | 202401 | +7.52 | -6.88 | +4.37 | +2.77 | -3.07 | -0.04 | +10.37 | 0 | 0.0% | 0.0636 | 0.0914 | 0.0% | 0.0% | 102,066.69 |
| 2024-01-12 | 453.65 | 452.45 | 202401 | +6.56 | -6.88 | +4.48 | +3.25 | -3.38 | -0.46 | +9.55 | 0 | 0.0% | 0.0680 | 0.0921 | 0.0% | 0.0% | 102,066.69 |
| 2024-01-15 | 453.83 | 454.28 | 202401 | +6.69 | -6.88 | +4.50 | +2.43 | -2.70 | -0.69 | +10.03 | 0 | 0.0% | 0.0669 | 0.0912 | 0.0% | 0.0% | 102,066.69 |
| 2024-01-16 | 454.94 | 452.00 | 202401 | +6.57 | -6.88 | +4.10 | +0.88 | -1.54 | -0.04 | +10.06 | 0 | 0.0% | 0.0670 | 0.0877 | 0.0% | 0.0% | 102,066.69 |
| 2024-01-17 | 451.87 | 451.13 | 202401 | +4.68 | -6.88 | +3.68 | -2.84 | +1.87 | +0.21 | +8.64 | 0 | 0.0% | 0.0683 | 0.0797 | 0.0% | 0.0% | 102,066.69 |
| 2024-01-18 | 453.79 | 450.98 | 202401 | +3.34 | -6.88 | +3.16 | -3.28 | +2.20 | +0.51 | +7.63 | 0 | 0.0% | 0.0698 | 0.0792 | 0.0% | 0.0% | 102,066.69 |
| 2024-01-19 | 455.44 | 455.53 | 202401 | +3.96 | -6.88 | +3.43 | -2.50 | +1.35 | +0.65 | +7.91 | 0 | 0.0% | 0.0707 | 0.0788 | 0.0% | 0.0% | 102,066.69 |
| 2024-01-22 | 460.55 | 459.77 | 202401 | +3.04 | -6.88 | +2.07 | -2.09 | +0.95 | +0.66 | +8.33 | 0 | 0.0% | 0.0796 | 0.0801 | 0.0% | 0.0% | 102,066.69 |
| 2024-01-23 | 461.10 | 460.13 | 202401 | +3.84 | -6.88 | +1.29 | -3.69 | +2.35 | +1.06 | +9.72 | 0 | 0.0% | 0.0722 | 0.0774 | 0.0% | 0.0% | 102,066.69 |
| 2024-01-24 | 463.46 | 463.40 | 202401 | +9.53 | -6.88 | +0.36 | -5.23 | +3.47 | +1.88 | +15.93 | 0 | 0.0% | 0.0730 | 0.0742 | 0.0% | 0.0% | 102,066.69 |
| 2024-01-25 | 465.71 | 462.09 | 202401 | +12.63 | -6.88 | +0.23 | -4.90 | +3.26 | +1.80 | +19.12 | 0 | 0.0% | 0.0718 | 0.0744 | 0.0% | 0.0% | 102,066.69 |
| 2024-01-26 | 466.03 | 465.09 | 202401 | +11.18 | -6.88 | +1.17 | -4.32 | +2.46 | +1.92 | +16.82 | 0 | 0.0% | 0.0715 | 0.0729 | 0.0% | 0.0% | 102,066.69 |
| 2024-01-29 | 468.08 | 466.58 | 202401 | +10.69 | -6.88 | +1.40 | -3.33 | +1.03 | +2.23 | +16.25 | 0 | 0.0% | 0.0699 | 0.0709 | 0.0% | 0.0% | 102,066.69 |
| 2024-01-30 | 469.16 | 469.77 | 202401 | +8.70 | -6.88 | +2.74 | -1.85 | -0.61 | +2.36 | +12.94 | 0 | 0.0% | 0.0692 | 0.0658 | 0.0% | 0.0% | 102,066.69 |
| 2024-01-31 | 466.39 | 469.54 | 202401 | +7.52 | -6.88 | +3.75 | -2.35 | -0.07 | +2.31 | +10.76 | 0 | 0.0% | 0.0713 | 0.0673 | 0.0% | 0.0% | 102,066.69 |
| 2024-02-01 | 464.23 | 466.12 | 202402 | +7.38 | -7.20 | +3.97 | -3.84 | +1.17 | +2.11 | +11.17 | 0 | 0.0% | 0.0745 | 0.0680 | 0.0% | 0.0% | 102,066.69 |
| 2024-02-02 | 472.01 | 468.45 | 202402 | +8.85 | -7.20 | +3.03 | -1.39 | -0.90 | +2.05 | +13.26 | 0 | 0.0% | 0.0899 | 0.0741 | 0.0% | 0.0% | 102,066.69 |
| 2024-02-05 | 472.52 | 472.36 | 202402 | +9.03 | -7.20 | +2.48 | -2.16 | -0.28 | +2.07 | +14.12 | 0 | 0.0% | 0.0900 | 0.0733 | 0.0% | 0.0% | 102,066.69 |
| 2024-02-06 | 473.77 | 473.74 | 202402 | +8.59 | -7.20 | +2.55 | -1.72 | -0.64 | +2.07 | +13.54 | 0 | 0.0% | 0.0883 | 0.0731 | 0.0% | 0.0% | 102,066.69 |
| 2024-02-07 | 475.79 | 473.86 | 202402 | +9.54 | -7.20 | +1.70 | -1.99 | -0.44 | +2.10 | +15.38 | 0 | 0.0% | 0.0882 | 0.0727 | 0.0% | 0.0% | 102,066.69 |
| 2024-02-08 | 475.87 | 476.38 | 202402 | +8.76 | -7.20 | +2.33 | -1.83 | -0.70 | +2.19 | +13.96 | 0 | 0.0% | 0.0851 | 0.0723 | 0.0% | 0.0% | 102,066.69 |
| 2024-02-09 | 476.64 | 476.56 | 202402 | +8.03 | -7.20 | +2.83 | -1.16 | -1.20 | +2.17 | +12.60 | 0 | 0.0% | 0.0833 | 0.0715 | 0.0% | 0.0% | 102,066.69 |
| 2024-02-12 | 480.52 | 477.87 | 202402 | +8.36 | -7.20 | +2.22 | -0.32 | -1.89 | +2.22 | +13.33 | 0 | 0.0% | 0.0852 | 0.0726 | 0.0% | 0.0% | 102,066.69 |
| 2024-02-13 | 475.72 | 479.11 | 202402 | +7.08 | -7.20 | +2.48 | -2.90 | -0.01 | +2.28 | +12.43 | 0 | 0.0% | 0.0968 | 0.0752 | 0.0% | 0.0% | 102,066.69 |
| 2024-02-14 | 476.61 | 476.18 | 202402 | +6.86 | -7.20 | +2.58 | -2.51 | -0.22 | +2.20 | +12.01 | 0 | 0.0% | 0.0908 | 0.0751 | 0.0% | 0.0% | 102,066.69 |
| 2024-02-15 | 479.06 | 479.86 | 202402 | +7.15 | -7.20 | +2.41 | -2.15 | -0.43 | +2.13 | +12.40 | 0 | 0.0% | 0.0910 | 0.0754 | 0.0% | 0.0% | 102,066.69 |
| 2024-02-16 | 480.99 | 481.73 | 202402 | +7.15 | -7.20 | +1.92 | -2.06 | -0.54 | +2.16 | +12.87 | 0 | 0.0% | 0.0911 | 0.0755 | 0.0% | 0.0% | 102,066.69 |
| 2024-02-19 | 479.99 | 479.04 | 202402 | +6.73 | -7.20 | +2.98 | -1.64 | -0.83 | +2.11 | +11.31 | 0 | 0.0% | 0.0868 | 0.0747 | 0.0% | 0.0% | 102,066.69 |
| 2024-02-20 | 475.32 | 478.89 | 202402 | +6.04 | -7.20 | +3.50 | -3.42 | +0.67 | +2.00 | +10.49 | 0 | 0.0% | 0.0965 | 0.0781 | 0.0% | 0.0% | 102,066.69 |
| 2024-02-21 | 474.77 | 475.43 | 202402 | +5.02 | -7.20 | +3.38 | -4.16 | +1.36 | +1.89 | +9.75 | 0 | 0.0% | 0.0960 | 0.0780 | 0.0% | 0.0% | 102,066.69 |
| 2024-02-22 | 482.96 | 479.43 | 202402 | +5.96 | -7.20 | +1.59 | -2.46 | -0.03 | +1.94 | +12.12 | 0 | 0.0% | 0.1108 | 0.0840 | 0.0% | 0.0% | 102,066.69 |
| 2024-02-23 | 484.61 | 483.96 | 202402 | +6.31 | -7.20 | +1.00 | -2.67 | +0.25 | +1.79 | +13.14 | 0 | 0.0% | 0.1109 | 0.0836 | 0.0% | 0.0% | 102,066.69 |
| 2024-02-26 | 482.89 | 483.65 | 202402 | +4.95 | -7.20 | +1.58 | -3.42 | +0.92 | +1.67 | +11.40 | 0 | 0.0% | 0.1122 | 0.0844 | 0.0% | 0.0% | 102,066.69 |
| 2024-02-27 | 482.20 | 482.24 | 202402 | +4.15 | -7.20 | +1.90 | -3.48 | +1.07 | +1.49 | +10.38 | 0 | 0.0% | 0.1126 | 0.0846 | 0.0% | 0.0% | 102,066.69 |
| 2024-02-28 | 482.50 | 483.19 | 202402 | +4.77 | -7.20 | +2.90 | -2.10 | +0.10 | +1.34 | +9.73 | 0 | 0.0% | 0.1093 | 0.0821 | 0.0% | 0.0% | 102,066.69 |
| 2024-02-29 | 483.56 | 482.25 | 202402 | +5.42 | -7.20 | +2.63 | -2.78 | +0.41 | +1.72 | +10.65 | 0 | 0.0% | 0.1067 | 0.0818 | 0.0% | 0.0% | 102,066.69 |
| 2024-03-01 | 487.10 | 486.53 | 202403 | +6.65 | -7.31 | +2.84 | -1.37 | -0.53 | +2.37 | +10.64 | 0 | 0.0% | 0.0943 | 0.0823 | 0.0% | 0.0% | 102,066.69 |
| 2024-03-04 | 486.97 | 487.50 | 202403 | +6.33 | -7.31 | +2.87 | -1.69 | -0.37 | +2.52 | +10.31 | 0 | 0.0% | 0.0945 | 0.0824 | 0.0% | 0.0% | 102,066.69 |
| 2024-03-05 | 483.56 | 486.49 | 202403 | +5.45 | -7.31 | +3.34 | -2.97 | +0.51 | +2.42 | +9.46 | 0 | 0.0% | 0.0991 | 0.0843 | 0.0% | 0.0% | 102,066.69 |
| 2024-03-06 | 485.09 | 484.00 | 202403 | +5.83 | -7.31 | +3.41 | -2.04 | -0.05 | +2.25 | +9.57 | 0 | 0.0% | 0.0987 | 0.0839 | 0.0% | 0.0% | 102,066.69 |
| 2024-03-07 | 487.16 | 483.62 | 202403 | +5.91 | -7.31 | +3.38 | -1.20 | -0.55 | +2.10 | +9.48 | 0 | 0.0% | 0.0993 | 0.0839 | 0.0% | 0.0% | 102,066.69 |
| 2024-03-08 | 487.35 | 488.41 | 202403 | +5.15 | -7.31 | +3.20 | -1.58 | -0.26 | +1.92 | +9.17 | 0 | 0.0% | 0.0993 | 0.0838 | 0.0% | 0.0% | 102,066.69 |
| 2024-03-11 | 484.22 | 483.91 | 202403 | +5.42 | -7.31 | +3.58 | -2.33 | +0.21 | +1.95 | +9.32 | 0 | 0.0% | 0.0992 | 0.0852 | 0.0% | 0.0% | 102,066.69 |
| 2024-03-12 | 488.23 | 486.25 | 202403 | +4.98 | -7.31 | +3.18 | -1.54 | -0.25 | +1.79 | +9.11 | 0 | 0.0% | 0.0949 | 0.0862 | 0.0% | 0.0% | 102,066.69 |
| 2024-03-13 | 488.37 | 489.32 | 202403 | +5.33 | -7.31 | +3.41 | -0.80 | -0.65 | +1.53 | +9.15 | 0 | 0.0% | 0.0949 | 0.0855 | 0.0% | 0.0% | 102,066.69 |
| 2024-03-14 | 488.48 | 489.82 | 202403 | +5.06 | -7.31 | +3.28 | -1.16 | -0.44 | +1.59 | +9.10 | 0 | 0.0% | 0.0938 | 0.0855 | 0.0% | 0.0% | 102,066.69 |
| 2024-03-15 | 485.49 | 488.90 | 202403 | +5.31 | -7.31 | +3.62 | -2.23 | +0.27 | +1.35 | +9.60 | 0 | 0.0% | 0.0963 | 0.0869 | 0.0% | 0.0% | 102,066.69 |
| 2024-03-18 | 489.80 | 487.65 | 202403 | +4.51 | -7.31 | +3.28 | -0.66 | -0.61 | +0.93 | +8.88 | 0 | 0.0% | 0.1002 | 0.0881 | 0.0% | 0.0% | 102,066.69 |
| 2024-03-19 | 490.82 | 489.50 | 202403 | +2.54 | -7.31 | +2.73 | -1.83 | +0.19 | +0.47 | +8.30 | 0 | 0.0% | 0.0918 | 0.0860 | 0.0% | 0.0% | 102,066.69 |
| 2024-03-20 | 491.86 | 491.34 | 202403 | +2.49 | -7.31 | +2.80 | -1.31 | -0.04 | +0.02 | +8.33 | 0 | 0.0% | 0.0912 | 0.0859 | 0.0% | 0.0% | 102,066.69 |
| 2024-03-21 | 498.91 | 496.39 | 202403 | +2.24 | -7.31 | +1.49 | -0.01 | -0.75 | -0.39 | +9.21 | 0 | 0.0% | 0.0852 | 0.0892 | 0.0% | 0.0% | 102,066.69 |
| 2024-03-22 | 498.76 | 499.06 | 202403 | +1.54 | -7.31 | +1.83 | +0.14 | -0.77 | -0.79 | +8.43 | 0 | 0.0% | 0.0852 | 0.0892 | 0.0% | 0.0% | 102,066.69 |
| 2024-03-25 | 497.05 | 498.26 | 202403 | +0.43 | -7.31 | +1.70 | -1.41 | +0.11 | -0.48 | +7.83 | 0 | 0.0% | 0.0851 | 0.0893 | 0.0% | 0.0% | 102,066.69 |
| 2024-03-26 | 498.27 | 497.41 | 202403 | +0.92 | -7.31 | +1.95 | -0.75 | -0.25 | -0.69 | +7.96 | 0 | 0.0% | 0.0844 | 0.0891 | 0.0% | 0.0% | 102,066.69 |
| 2024-03-27 | 497.83 | 497.97 | 202403 | +0.18 | -7.31 | +1.66 | -2.09 | +0.56 | -0.63 | +7.98 | 0 | 0.0% | 0.0848 | 0.0884 | 0.0% | 0.0% | 102,066.69 |
| 2024-03-28 | 501.00 | 500.77 | 202403 | +1.63 | -7.31 | +1.21 | -1.89 | +0.34 | -0.17 | +9.44 | 0 | 0.0% | 0.0865 | 0.0887 | 0.0% | 0.0% | 102,066.69 |
| 2024-04-02 | 496.87 | 502.60 | 202404 | -1.49 | -7.30 | +1.30 | -4.13 | +1.54 | +0.63 | +6.46 | 0 | 0.0% | 0.0909 | 0.0908 | 0.0% | 0.0% | 102,066.69 |
| 2024-04-03 | 497.37 | 497.39 | 202404 | +1.17 | -7.30 | +1.54 | -4.63 | +1.58 | +1.86 | +8.11 | 0 | 0.0% | 0.0908 | 0.0908 | 0.0% | 0.0% | 102,066.69 |
| 2024-04-04 | 497.81 | 497.19 | 202404 | +2.36 | -7.30 | +2.23 | -3.77 | +1.13 | +1.65 | +8.42 | 0 | 0.0% | 0.0856 | 0.0901 | 0.0% | 0.0% | 102,066.69 |
| 2024-04-05 | 494.22 | 491.54 | 202404 | +0.41 | -7.30 | +2.42 | -5.57 | +2.09 | +2.28 | +6.48 | 0 | 0.0% | 0.0907 | 0.0918 | 0.0% | 0.0% | 102,066.69 |
| 2024-04-08 | 495.40 | 494.60 | 202404 | -1.12 | -7.30 | +1.93 | -6.33 | +2.57 | +2.43 | +5.59 | 0 | 0.0% | 0.0900 | 0.0911 | 0.0% | 0.0% | 102,066.69 |
| 2024-04-09 | 492.47 | 495.25 | 202404 | -1.07 | -7.30 | +2.70 | -6.45 | +2.70 | +2.15 | +5.13 | 0 | 0.0% | 0.0932 | 0.0915 | 0.0% | 0.0% | 102,066.69 |
| 2024-04-10 | 494.97 | 496.11 | 202404 | -1.56 | -7.30 | +2.44 | -5.81 | +2.44 | +1.48 | +5.20 | 0 | 0.0% | 0.0907 | 0.0918 | 0.0% | 0.0% | 102,066.69 |
| 2024-04-11 | 495.50 | 495.91 | 202404 | -0.54 | -7.30 | +2.65 | -5.67 | +2.37 | +1.35 | +6.07 | 0 | 0.0% | 0.0866 | 0.0918 | 0.0% | 0.0% | 102,066.69 |
| 2024-04-12 | 498.14 | 500.87 | 202404 | -0.36 | -7.30 | +1.85 | -6.24 | +2.83 | +0.86 | +7.64 | 0 | 0.0% | 0.0881 | 0.0905 | 0.0% | 0.0% | 102,066.69 |
| 2024-04-15 | 496.93 | 497.85 | 202404 | -0.91 | -7.30 | +2.38 | -6.31 | +2.96 | +0.41 | +6.96 | 0 | 0.0% | 0.0889 | 0.0907 | 0.0% | 0.0% | 102,066.69 |
| 2024-04-16 | 489.20 | 489.78 | 202404 | -5.66 | -7.30 | +3.09 | -8.73 | +4.52 | +0.35 | +2.42 | 0 | 0.0% | 0.1040 | 0.0972 | 0.0% | 0.0% | 102,066.69 |
| 2024-04-17 | 486.37 | 488.24 | 202404 | -3.78 | -7.30 | +3.29 | -8.05 | +4.17 | -0.20 | +4.32 | 0 | 0.0% | 0.1012 | 0.0960 | 0.0% | 0.0% | 102,066.69 |
| 2024-04-18 | 487.57 | 486.52 | 202404 | -4.47 | -7.30 | +3.31 | -7.64 | +3.97 | -0.88 | +4.07 | 0 | 0.0% | 0.1013 | 0.0960 | 0.0% | 0.0% | 102,066.69 |
| 2024-04-19 | 483.15 | 482.50 | 202404 | -5.63 | -7.30 | +2.90 | -8.50 | +4.58 | -1.40 | +4.09 | 0 | 0.0% | 0.1055 | 0.0978 | 0.0% | 0.0% | 102,066.69 |
| 2024-04-22 | 483.89 | 484.04 | 202404 | -5.60 | -7.30 | +2.70 | -7.60 | +4.04 | -2.29 | +4.86 | 0 | 0.0% | 0.0898 | 0.0974 | 0.0% | 0.0% | 102,066.69 |
| 2024-04-23 | 489.26 | 487.08 | 202404 | -5.02 | -7.30 | +3.09 | -5.86 | +2.96 | -2.80 | +4.88 | 0 | 0.0% | 0.1003 | 0.0997 | 0.0% | 0.0% | 102,066.69 |
| 2024-04-24 | 489.57 | 491.75 | 202404 | -3.73 | -7.30 | +3.17 | -5.29 | +2.61 | -2.74 | +5.82 | 0 | 0.0% | 0.1000 | 0.0994 | 0.0% | 0.0% | 102,066.69 |
| 2024-04-25 | 483.50 | 486.74 | 202404 | -4.90 | -7.30 | +2.57 | -7.12 | +3.79 | -2.57 | +5.73 | 0 | 0.0% | 0.1074 | 0.1030 | 0.0% | 0.0% | 102,066.69 |
| 2024-04-26 | 492.37 | 489.76 | 202404 | -3.62 | -7.30 | +3.58 | -5.28 | +2.67 | -3.26 | +5.98 | 0 | 0.0% | 0.1281 | 0.1083 | 0.0% | 0.0% | 102,066.69 |
| 2024-04-29 | 492.11 | 493.15 | 202404 | -2.82 | -7.30 | +3.85 | -6.37 | +3.39 | -2.77 | +6.38 | 0 | 0.0% | 0.1255 | 0.1077 | 0.0% | 0.0% | 102,066.69 |
| 2024-04-30 | 490.90 | 493.41 | 202404 | -2.59 | -7.30 | +3.74 | -4.28 | +2.12 | -3.24 | +6.37 | 0 | 0.0% | 0.1226 | 0.1029 | 0.0% | 0.0% | 102,066.69 |
| 2024-05-02 | 486.30 | 487.35 | 202405 | +3.90 | -1.19 | -0.95 | -3.64 | +3.22 | -3.80 | +10.27 | 0 | 0.0% | 0.1263 | 0.1049 | 0.0% | 0.0% | 102,066.69 |
| 2024-05-03 | 491.23 | 489.56 | 202405 | -0.91 | -1.19 | -2.09 | -2.56 | +1.98 | -4.09 | +7.04 | 0 | 0.0% | 0.1323 | 0.1067 | 0.0% | 0.0% | 102,066.69 |
| 2024-05-06 | 494.79 | 493.40 | 202405 | -2.49 | -1.19 | -2.53 | -1.61 | +0.97 | -4.51 | +6.39 | 0 | 0.0% | 0.1328 | 0.1073 | 0.0% | 0.0% | 102,066.69 |
| 2024-05-07 | 498.43 | 497.57 | 202405 | -5.04 | -1.19 | -3.63 | -1.06 | +0.41 | -4.69 | +5.12 | 0 | 0.0% | 0.1351 | 0.1081 | 0.0% | 0.0% | 102,066.69 |
| 2024-05-08 | 498.45 | 498.93 | 202405 | -5.66 | -1.19 | -3.33 | -1.00 | +0.39 | -5.65 | +5.11 | 0 | 0.0% | 0.1331 | 0.1081 | 0.0% | 0.0% | 102,066.69 |
| 2024-05-09 | 499.40 | 498.49 | 202405 | -5.50 | -1.19 | -2.28 | -0.24 | -0.35 | -6.37 | +4.93 | 0 | 0.0% | 0.1321 | 0.1071 | 0.0% | 0.0% | 102,066.69 |
| 2024-05-10 | 501.09 | 501.29 | 202405 | -8.55 | -1.19 | -4.32 | -0.93 | +0.35 | -6.19 | +3.72 | 0 | 0.0% | 0.1325 | 0.1049 | 0.0% | 0.0% | 102,066.69 |
| 2024-05-13 | 500.35 | 501.73 | 202405 | -8.06 | -1.19 | -3.76 | -1.00 | +0.47 | -6.75 | +4.17 | 0 | 0.0% | 0.1315 | 0.1049 | 0.0% | 0.0% | 102,066.69 |
| 2024-05-14 | 500.03 | 500.65 | 202405 | -7.09 | -1.19 | -2.78 | -0.73 | +0.21 | -7.23 | +4.64 | 0 | 0.0% | 0.1312 | 0.1046 | 0.0% | 0.0% | 102,066.69 |
| 2024-05-15 | 503.55 | 501.67 | 202405 | -8.82 | -1.19 | -3.11 | +0.01 | -0.60 | -7.05 | +3.12 | 0 | 0.0% | 0.1186 | 0.1052 | 0.0% | 0.0% | 102,066.69 |
| 2024-05-16 | 505.86 | 505.60 | 202405 | -9.94 | -1.19 | -3.98 | +0.08 | -0.67 | -7.52 | +3.33 | 0 | 0.0% | 0.1159 | 0.1053 | 0.0% | 0.0% | 102,066.69 |
| 2024-05-17 | 504.15 | 504.48 | 202405 | -9.05 | -1.19 | -4.83 | -0.96 | +0.62 | -8.03 | +5.34 | 0 | 0.0% | 0.1174 | 0.1033 | 0.0% | 0.0% | 102,066.69 |
| 2024-05-20 | 507.00 | 505.24 | 202405 | -7.94 | -1.19 | -5.85 | -0.75 | +0.40 | -8.65 | +8.10 | 0 | 0.0% | 0.1109 | 0.1037 | 0.0% | 0.0% | 102,066.69 |
| 2024-05-21 | 505.96 | 505.44 | 202405 | -9.45 | -1.19 | -2.60 | +0.11 | -0.72 | -8.24 | +3.18 | 0 | 0.0% | 0.1120 | 0.0983 | 0.0% | 0.0% | 102,066.69 |
| 2024-05-22 | 506.12 | 505.87 | 202405 | -9.00 | -1.19 | -1.96 | +0.26 | -0.89 | -8.74 | +3.52 | 0 | 0.0% | 0.1072 | 0.0982 | 0.0% | 0.0% | 102,066.69 |
| 2024-05-23 | 506.23 | 508.10 | 202405 | -8.16 | -1.19 | -2.48 | -0.05 | -0.50 | -8.60 | +4.66 | 0 | 0.0% | 0.1073 | 0.0978 | 0.0% | 0.0% | 102,066.69 |
| 2024-05-24 | 504.47 | 502.85 | 202405 | -6.47 | -1.19 | -2.17 | -0.43 | +0.04 | -9.09 | +6.37 | 0 | 0.0% | 0.0957 | 0.0981 | 0.0% | 0.0% | 102,066.69 |
| 2024-05-27 | 505.62 | 504.67 | 202405 | -6.52 | -1.19 | -2.42 | -0.32 | -0.08 | -9.68 | +7.16 | 0 | 0.0% | 0.0746 | 0.0981 | 0.0% | 0.0% | 102,066.69 |
| 2024-05-28 | 503.44 | 505.19 | 202405 | -4.06 | -1.19 | -1.38 | -0.56 | +0.23 | -9.07 | +7.91 | 0 | 0.0% | 0.0771 | 0.0986 | 0.0% | 0.0% | 102,066.69 |
| 2024-05-29 | 501.66 | 502.60 | 202405 | +1.25 | -1.19 | +0.37 | -0.41 | +0.01 | -8.73 | +11.20 | 0 | 0.0% | 0.0778 | 0.0980 | 0.0% | 0.0% | 102,066.69 |
| 2024-05-30 | 500.18 | 500.09 | 202405 | +3.24 | -1.19 | +0.90 | -0.67 | +0.37 | -7.91 | +11.74 | 0 | 0.0% | 0.0692 | 0.0983 | 0.0% | 0.0% | 102,066.69 |
| 2024-05-31 | 497.00 | 499.71 | 202405 | +3.45 | -1.19 | +0.87 | -1.51 | +1.73 | -7.47 | +11.02 | 0 | 0.0% | 0.0664 | 0.0981 | 0.0% | 0.0% | 102,066.69 |
| 2024-06-03 | 500.55 | 504.27 | 202406 | +2.38 | -1.29 | +0.18 | -0.95 | +0.79 | -7.14 | +10.80 | 0 | 0.0% | 0.0662 | 0.0989 | 0.0% | 0.0% | 102,066.69 |
| 2024-06-04 | 499.63 | 500.37 | 202406 | +5.33 | -1.29 | +1.15 | -0.86 | +0.65 | -7.22 | +12.89 | 0 | 0.0% | 0.0617 | 0.0987 | 0.0% | 0.0% | 102,066.69 |
| 2024-06-05 | 505.37 | 502.64 | 202406 | -0.22 | -1.29 | -0.47 | -0.24 | -0.27 | -7.44 | +9.48 | 0 | 0.0% | 0.0736 | 0.1012 | 0.0% | 0.0% | 102,066.69 |
| 2024-06-06 | 507.38 | 507.56 | 202406 | -1.95 | -1.29 | -1.96 | -0.47 | +0.05 | -6.86 | +8.58 | 0 | 0.0% | 0.0744 | 0.1003 | 0.0% | 0.0% | 102,066.69 |
| 2024-06-07 | 510.08 | 507.81 | 202406 | -1.84 | -1.29 | -1.58 | +0.20 | -0.91 | -7.03 | +8.77 | 0 | 0.0% | 0.0756 | 0.0996 | 0.0% | 0.0% | 102,066.69 |
| 2024-06-10 | 512.14 | 510.11 | 202406 | -1.75 | -1.29 | -2.10 | +0.33 | -1.12 | -6.70 | +9.12 | 0 | 0.0% | 0.0758 | 0.0998 | 0.0% | 0.0% | 102,066.69 |
| 2024-06-11 | 511.34 | 511.77 | 202406 | -1.01 | -1.29 | -1.71 | +0.14 | -0.90 | -6.15 | +8.89 | 0 | 0.0% | 0.0762 | 0.0999 | 0.0% | 0.0% | 102,066.69 |
| 2024-06-12 | 513.98 | 512.90 | 202406 | -0.65 | -1.29 | -3.47 | +0.01 | -0.70 | -6.37 | +11.17 | 0 | 0.0% | 0.0745 | 0.0993 | 0.0% | 0.0% | 102,066.69 |
| 2024-06-13 | 514.05 | 514.67 | 202406 | -0.81 | -1.29 | -2.06 | +0.38 | -1.24 | -6.20 | +9.61 | 0 | 0.0% | 0.0734 | 0.0979 | 0.0% | 0.0% | 102,066.69 |
| 2024-06-14 | 515.54 | 516.41 | 202406 | -0.33 | -1.29 | -2.23 | +0.55 | -1.47 | -6.17 | +10.28 | 0 | 0.0% | 0.0720 | 0.0980 | 0.0% | 0.0% | 102,066.69 |
| 2024-06-17 | 515.31 | 516.60 | 202406 | +2.52 | -1.29 | -1.91 | +0.52 | -1.48 | -5.36 | +12.04 | 0 | 0.0% | 0.0701 | 0.0980 | 0.0% | 0.0% | 102,066.69 |
| 2024-06-18 | 518.34 | 518.29 | 202406 | +3.23 | -1.29 | -0.63 | +1.51 | -2.65 | -5.50 | +11.80 | 0 | 0.0% | 0.0715 | 0.0945 | 0.0% | 0.0% | 102,066.69 |
| 2024-06-19 | 519.13 | 519.78 | 202406 | +3.26 | -1.29 | -0.90 | +1.52 | -2.65 | -5.97 | +12.54 | 0 | 0.0% | 0.0714 | 0.0945 | 0.0% | 0.0% | 102,066.69 |
| 2024-06-20 | 521.32 | 520.77 | 202406 | +1.66 | -1.29 | -1.97 | +1.43 | -2.61 | -4.94 | +11.03 | 0 | 0.0% | 0.0720 | 0.0944 | 0.0% | 0.0% | 102,066.69 |
| 2024-06-21 | 519.28 | 519.75 | 202406 | +7.25 | -1.29 | -1.05 | +1.30 | -2.44 | -5.14 | +15.86 | 0 | 0.0% | 0.0724 | 0.0948 | 0.0% | 0.0% | 102,066.69 |
| 2024-06-24 | 520.15 | 519.02 | 202406 | +8.78 | -1.29 | -1.42 | +1.22 | -2.40 | -4.21 | +16.88 | 0 | 0.0% | 0.0724 | 0.0948 | 0.0% | 0.0% | 102,066.69 |
| 2024-06-25 | 519.90 | 518.31 | 202406 | +14.96 | -1.29 | -0.35 | +1.44 | -2.66 | -3.83 | +21.65 | 0 | 0.0% | 0.0696 | 0.0941 | 0.0% | 0.0% | 102,066.69 |
| 2024-06-26 | 519.98 | 521.85 | 202406 | +13.63 | -1.29 | -1.53 | +0.88 | -2.10 | -2.21 | +19.88 | 0 | 0.0% | 0.0671 | 0.0922 | 0.0% | 0.0% | 102,066.69 |
| 2024-06-27 | 519.67 | 520.52 | 202406 | +16.51 | -1.29 | -1.24 | +0.80 | -2.03 | -1.69 | +21.96 | 0 | 0.0% | 0.0654 | 0.0923 | 0.0% | 0.0% | 102,066.69 |
| 2024-06-28 | 521.62 | 522.60 | 202406 | +15.40 | -1.29 | -1.68 | +0.96 | -2.22 | -1.79 | +21.42 | 0 | 0.0% | 0.0578 | 0.0925 | 0.0% | 0.0% | 102,066.69 |
| 2024-07-01 | 518.64 | 519.07 | 202407 | +20.12 | -1.29 | -2.11 | -0.01 | -1.14 | +1.14 | +23.54 | 1 | 100.0% | 0.0618 | 0.0919 | 100.0% | 0.0% | 102,066.69 |
| 2024-07-02 | 519.46 | 518.15 | 202407 | +21.96 | -1.29 | -1.87 | +0.03 | -1.30 | +2.31 | +24.08 | 1 | 100.0% | 0.0603 | 0.0919 | 99.6% | 99.6% | 102,222.81 |
| 2024-07-03 | 521.09 | 521.35 | 202407 | +16.20 | -1.29 | -3.19 | -0.21 | -0.99 | +2.47 | +19.41 | 1 | 100.0% | 0.0493 | 0.0909 | 99.6% | 99.6% | 102,542.55 |
| 2024-07-04 | 522.27 | 522.89 | 202407 | +17.88 | -1.29 | -2.77 | +0.06 | -1.37 | +2.17 | +21.07 | 1 | 100.0% | 0.0485 | 0.0906 | 99.6% | 99.6% | 102,773.72 |
| 2024-07-05 | 522.52 | 522.85 | 202407 | +19.22 | -1.29 | -2.78 | +0.07 | -1.35 | +2.09 | +22.47 | 1 | 100.0% | 0.0464 | 0.0906 | 99.6% | 99.6% | 102,821.99 |
| 2024-07-08 | 523.43 | 522.72 | 202407 | +22.58 | -1.29 | -2.25 | +0.33 | -1.70 | +2.08 | +25.41 | 1 | 100.0% | 0.0452 | 0.0901 | 99.6% | 99.6% | 103,001.47 |
| 2024-07-09 | 524.06 | 524.38 | 202407 | +21.33 | -1.29 | -2.84 | +0.20 | -1.51 | +1.97 | +24.80 | 1 | 100.0% | 0.0442 | 0.0899 | 99.6% | 99.6% | 103,124.40 |
| 2024-07-10 | 526.27 | 524.27 | 202407 | +9.14 | -1.29 | -5.85 | -0.50 | -0.55 | +2.40 | +14.93 | 1 | 100.0% | 0.0432 | 0.0832 | 99.6% | 99.6% | 103,556.89 |
| 2024-07-11 | 525.44 | 528.64 | 202407 | +6.93 | -1.29 | -6.54 | -0.95 | +0.24 | +2.19 | +13.27 | 1 | 100.0% | 0.0441 | 0.0821 | 99.6% | 99.6% | 103,394.24 |
| 2024-07-12 | 527.95 | 525.74 | 202407 | +5.69 | -1.29 | -6.92 | -0.72 | -0.14 | +2.07 | +12.68 | 1 | 100.0% | 0.0456 | 0.0824 | 99.6% | 99.6% | 103,887.15 |
| 2024-07-15 | 527.99 | 527.89 | 202407 | +3.42 | -1.29 | -8.40 | -1.33 | +0.86 | +2.52 | +11.05 | 1 | 100.0% | 0.0454 | 0.0796 | 99.6% | 99.6% | 103,893.64 |
| 2024-07-16 | 528.66 | 526.94 | 202407 | +2.97 | -1.29 | -8.37 | -1.32 | +0.87 | +2.32 | +10.75 | 1 | 100.0% | 0.0420 | 0.0796 | 99.6% | 99.6% | 104,024.94 |
| 2024-07-17 | 523.14 | 527.26 | 202407 | +10.85 | -1.29 | -4.98 | -1.42 | +1.06 | +2.33 | +15.15 | 1 | 100.0% | 0.0584 | 0.0807 | 99.6% | 99.6% | 102,943.32 |
| 2024-07-18 | 520.00 | 524.09 | 202407 | +13.36 | -1.29 | -4.02 | -1.80 | +1.76 | +2.20 | +16.51 | 1 | 100.0% | 0.0608 | 0.0820 | 99.6% | 99.6% | 102,328.46 |
| 2024-07-19 | 517.14 | 520.00 | 202407 | +4.78 | -1.29 | -5.20 | -2.88 | +3.86 | +2.35 | +7.93 | 1 | 100.0% | 0.0623 | 0.0783 | 99.6% | 99.6% | 101,766.98 |
| 2024-07-22 | 519.27 | 518.14 | 202407 | +14.51 | -1.29 | -3.00 | -1.81 | +1.75 | +2.20 | +16.66 | 1 | 100.0% | 0.0639 | 0.0701 | 99.6% | 99.6% | 102,186.26 |
| 2024-07-23 | 524.16 | 520.85 | 202407 | +8.55 | -1.29 | -4.59 | -1.48 | +1.10 | +2.63 | +12.18 | 1 | 100.0% | 0.0721 | 0.0722 | 99.6% | 99.6% | 103,143.17 |
| 2024-07-24 | 515.06 | 519.04 | 202407 | +14.43 | -1.29 | -2.24 | -2.62 | +3.27 | +2.49 | +14.81 | 1 | 100.0% | 0.0962 | 0.0813 | 99.6% | 99.6% | 101,359.63 |
| 2024-07-25 | 512.44 | 512.18 | 202407 | +5.76 | -1.29 | -2.87 | -3.55 | +5.12 | +3.86 | +4.49 | 1 | 100.0% | 0.0976 | 0.0794 | 99.6% | 99.6% | 100,846.45 |
| 2024-07-26 | 513.30 | 511.33 | 202407 | +10.62 | -1.29 | -1.60 | -3.04 | +3.94 | +3.93 | +8.67 | 1 | 100.0% | 0.0966 | 0.0771 | 99.6% | 99.6% | 101,014.32 |
| 2024-07-29 | 514.43 | 516.79 | 202407 | +12.48 | -1.29 | -0.85 | -2.62 | +3.06 | +3.74 | +10.44 | 1 | 100.0% | 0.0953 | 0.0760 | 99.6% | 99.6% | 101,236.03 |
| 2024-07-30 | 514.74 | 516.09 | 202407 | +15.37 | -1.29 | +0.17 | -2.26 | +2.36 | +3.44 | +12.94 | 1 | 100.0% | 0.0951 | 0.0747 | 99.6% | 99.6% | 101,297.48 |
| 2024-07-31 | 522.54 | 519.46 | 202407 | +6.23 | -1.29 | -2.26 | -1.52 | +1.03 | +3.23 | +7.03 | 1 | 100.0% | 0.1094 | 0.0804 | 99.6% | 99.6% | 102,827.02 |
| 2024-08-01 | 517.22 | 523.00 | 202408 | +13.88 | -0.10 | -2.81 | -1.91 | +2.49 | +3.14 | +13.07 | 1 | 100.0% | 0.1151 | 0.0835 | 99.6% | 99.6% | 101,782.80 |
| 2024-08-02 | 496.61 | 509.50 | 202408 | +47.12 | -0.10 | +5.31 | -3.95 | +7.72 | +3.84 | +34.29 | 1 | 65.6% | 0.1830 | 0.1186 | 65.6% | 99.6% | 97,744.04 |
| 2024-08-05 | 485.47 | 484.08 | 202408 | +58.13 | -0.10 | +9.45 | -5.20 | +11.53 | +6.33 | +36.12 | 1 | 61.4% | 0.1956 | 0.1272 | 61.4% | 66.1% | 95,436.24 |
| 2024-08-06 | 489.76 | 489.57 | 202408 | +49.29 | -0.10 | +7.43 | -4.71 | +10.03 | +7.02 | +29.62 | 1 | 60.0% | 0.1999 | 0.1287 | 61.7% | 61.7% | 95,988.12 |
| 2024-08-07 | 496.77 | 492.41 | 202408 | +43.48 | -0.10 | +5.91 | -3.47 | +6.62 | +7.04 | +27.49 | 1 | 57.7% | 0.2080 | 0.1312 | 57.7% | 62.1% | 96,836.36 |
| 2024-08-08 | 496.49 | 487.49 | 202408 | +45.47 | -0.10 | +6.87 | -3.24 | +5.95 | +6.87 | +29.11 | 1 | 57.7% | 0.2081 | 0.1309 | 58.0% | 58.0% | 96,727.03 |
| 2024-08-09 | 498.75 | 497.63 | 202408 | +32.24 | -0.10 | +5.26 | -3.20 | +5.72 | +6.27 | +18.29 | 1 | 57.7% | 0.2080 | 0.1311 | 58.1% | 58.1% | 96,982.17 |
| 2024-08-12 | 499.47 | 500.61 | 202408 | +33.67 | -0.10 | +6.06 | -2.75 | +4.66 | +5.79 | +20.01 | 1 | 57.6% | 0.2083 | 0.1306 | 58.1% | 58.1% | 97,063.73 |
| 2024-08-13 | 504.48 | 502.06 | 202408 | +19.36 | -0.10 | +3.68 | -2.26 | +3.56 | +5.34 | +9.14 | 1 | 56.4% | 0.2128 | 0.1322 | 58.4% | 58.4% | 97,629.46 |
| 2024-08-14 | 505.70 | 505.67 | 202408 | +14.90 | -0.10 | +3.24 | -2.12 | +3.20 | +4.63 | +6.04 | 1 | 56.8% | 0.2112 | 0.1323 | 58.4% | 58.4% | 97,767.30 |
| 2024-08-15 | 514.47 | 507.50 | 202408 | +5.01 | -0.10 | +0.06 | -0.94 | +1.14 | +4.11 | +0.74 | 1 | 54.4% | 0.2207 | 0.1369 | 54.4% | 58.9% | 98,757.88 |
| 2024-08-16 | 515.18 | 517.03 | 202408 | +1.91 | -0.10 | -0.81 | -1.09 | +1.45 | +3.27 | -0.80 | 1 | 54.5% | 0.2200 | 0.1367 | 54.7% | 54.7% | 98,849.05 |
| 2024-08-19 | 516.53 | 514.56 | 202408 | +0.67 | -0.10 | -0.89 | -0.80 | +0.98 | +2.46 | -0.98 | 1 | 54.6% | 0.2197 | 0.1367 | 54.8% | 54.8% | 98,991.09 |
| 2024-08-20 | 515.33 | 518.22 | 202408 | -0.97 | -0.10 | -1.25 | -1.28 | +1.82 | +1.98 | -2.14 | 0 | 0.0% | 0.2168 | 0.1365 | 0.0% | 54.7% | 98,865.34 |
| 2024-08-21 | 515.88 | 515.76 | 202408 | -2.75 | -0.10 | -2.09 | -1.48 | +2.22 | +1.22 | -2.53 | 0 | 0.0% | 0.2077 | 0.1362 | 0.0% | 0.0% | 98,856.42 |
| 2024-08-22 | 516.93 | 516.86 | 202408 | -3.04 | -0.10 | -3.00 | -1.59 | +2.45 | +0.67 | -1.47 | 0 | 0.0% | 0.2069 | 0.1361 | 0.0% | 0.0% | 98,856.42 |
| 2024-08-23 | 516.96 | 516.04 | 202408 | -3.21 | -0.10 | -4.18 | -2.07 | +3.40 | +0.11 | -0.38 | 0 | 0.0% | 0.2068 | 0.1353 | 0.0% | 0.0% | 98,856.42 |
| 2024-08-26 | 516.77 | 517.16 | 202408 | -2.97 | -0.10 | -2.80 | -1.71 | +2.70 | +0.23 | -1.29 | 0 | 0.0% | 0.2067 | 0.1347 | 0.0% | 0.0% | 98,856.42 |
| 2024-08-27 | 516.89 | 517.45 | 202408 | -3.48 | -0.10 | -3.22 | -1.90 | +3.04 | -0.68 | -0.62 | 0 | 0.0% | 0.2067 | 0.1346 | 0.0% | 0.0% | 98,856.42 |
| 2024-08-28 | 516.95 | 518.80 | 202408 | -3.49 | -0.10 | -1.15 | -1.18 | +1.75 | -1.41 | -1.40 | 0 | 0.0% | 0.1991 | 0.1327 | 0.0% | 0.0% | 98,856.42 |
| 2024-08-29 | 523.04 | 517.47 | 202408 | -3.79 | -0.10 | -2.58 | -0.15 | +0.11 | -2.50 | +1.43 | 0 | 0.0% | 0.2002 | 0.1345 | 0.0% | 0.0% | 98,856.42 |
| 2024-08-30 | 521.02 | 521.43 | 202408 | -3.64 | -0.10 | -0.89 | -0.12 | +0.05 | -2.09 | -0.50 | 0 | 0.0% | 0.1300 | 0.1344 | 0.0% | 0.0% | 98,856.42 |
| 2024-09-02 | 524.20 | 523.56 | 202409 | -6.53 | -0.10 | +0.05 | -0.40 | -0.57 | -2.60 | -2.91 | 0 | 0.0% | 0.0905 | 0.1347 | 0.0% | 0.0% | 98,856.42 |
| 2024-09-03 | 519.02 | 524.83 | 202409 | -5.38 | -0.10 | +1.81 | -1.39 | +0.93 | -3.02 | -3.60 | 0 | 0.0% | 0.1007 | 0.1363 | 0.0% | 0.0% | 98,856.42 |
| 2024-09-04 | 512.73 | 511.69 | 202409 | -0.28 | -0.10 | +5.57 | -2.00 | +1.91 | -3.28 | -2.38 | 0 | 0.0% | 0.1049 | 0.1383 | 0.0% | 0.0% | 98,856.42 |
| 2024-09-05 | 509.46 | 511.37 | 202409 | +3.34 | -0.10 | +7.04 | -2.51 | +2.79 | -3.32 | -0.55 | 0 | 0.0% | 0.1085 | 0.1389 | 0.0% | 0.0% | 98,856.42 |
| 2024-09-06 | 502.54 | 507.60 | 202409 | +15.89 | -0.10 | +10.95 | -3.36 | +4.35 | -3.00 | +7.05 | 0 | 0.0% | 0.1199 | 0.1415 | 0.0% | 0.0% | 98,856.42 |
| 2024-09-09 | 508.67 | 506.09 | 202409 | +4.88 | -0.10 | +8.01 | -2.29 | +2.48 | -1.93 | -1.28 | 0 | 0.0% | 0.1270 | 0.1438 | 0.0% | 0.0% | 98,856.42 |
| 2024-09-10 | 509.54 | 508.09 | 202409 | +6.44 | -0.10 | +9.04 | -1.66 | +1.35 | -2.41 | +0.22 | 0 | 0.0% | 0.1224 | 0.1433 | 0.0% | 0.0% | 98,856.42 |
| 2024-09-11 | 507.14 | 509.45 | 202409 | +10.14 | -0.10 | +10.48 | -1.88 | +1.69 | -3.72 | +3.67 | 0 | 0.0% | 0.1236 | 0.1435 | 0.0% | 0.0% | 98,856.42 |
| 2024-09-12 | 516.61 | 518.15 | 202409 | -2.56 | -0.10 | +7.13 | -0.08 | -1.19 | -4.54 | -3.78 | 0 | 0.0% | 0.1260 | 0.1484 | 0.0% | 0.0% | 98,856.42 |
| 2024-09-13 | 520.37 | 518.30 | 202409 | -7.12 | -0.10 | +4.71 | +0.11 | -1.56 | -4.98 | -5.30 | 0 | 0.0% | 0.1285 | 0.1489 | 0.0% | 0.0% | 98,856.42 |
| 2024-09-16 | 518.10 | 518.71 | 202409 | -4.86 | -0.10 | +6.07 | -0.09 | -1.27 | -4.82 | -4.65 | 0 | 0.0% | 0.1293 | 0.1492 | 0.0% | 0.0% | 98,856.42 |
| 2024-09-17 | 521.13 | 519.84 | 202409 | -8.27 | -0.10 | +4.69 | +0.30 | -1.84 | -5.30 | -6.02 | 0 | 0.0% | 0.1305 | 0.1496 | 0.0% | 0.0% | 98,856.42 |
| 2024-09-18 | 518.63 | 520.16 | 202409 | -6.09 | -0.10 | +5.81 | -0.03 | -1.35 | -5.72 | -4.70 | 0 | 0.0% | 0.1318 | 0.1500 | 0.0% | 0.0% | 98,856.42 |
| 2024-09-19 | 525.76 | 523.22 | 202409 | -12.84 | -0.10 | +2.72 | +0.88 | -2.65 | -6.09 | -7.60 | 0 | 0.0% | 0.1401 | 0.1526 | 0.0% | 0.0% | 98,856.42 |
| 2024-09-20 | 522.58 | 524.01 | 202409 | -9.05 | -0.10 | +4.82 | +0.73 | -2.41 | -6.68 | -5.41 | 0 | 0.0% | 0.1422 | 0.1529 | 0.0% | 0.0% | 98,856.42 |
| 2024-09-23 | 526.03 | 523.71 | 202409 | -13.04 | -0.10 | +2.20 | +0.77 | -2.46 | -6.23 | -7.20 | 0 | 0.0% | 0.1438 | 0.1530 | 0.0% | 0.0% | 98,856.42 |
| 2024-09-24 | 525.81 | 527.88 | 202409 | -12.48 | -0.10 | +2.64 | +0.82 | -2.53 | -6.08 | -7.23 | 0 | 0.0% | 0.1438 | 0.1530 | 0.0% | 0.0% | 98,856.42 |
| 2024-09-25 | 526.13 | 523.38 | 202409 | -11.80 | -0.10 | +3.19 | +1.05 | -2.84 | -6.52 | -6.57 | 0 | 0.0% | 0.1438 | 0.1529 | 0.0% | 0.0% | 98,856.42 |
| 2024-09-26 | 527.29 | 530.00 | 202409 | -11.24 | -0.10 | +3.19 | +1.34 | -3.20 | -6.69 | -5.77 | 0 | 0.0% | 0.1382 | 0.1529 | 0.0% | 0.0% | 98,856.42 |
| 2024-09-27 | 529.33 | 529.43 | 202409 | -12.29 | -0.10 | +2.49 | +1.57 | -3.53 | -6.61 | -6.10 | 0 | 0.0% | 0.1377 | 0.1531 | 0.0% | 0.0% | 98,856.42 |
| 2024-09-30 | 528.02 | 527.92 | 202409 | -6.49 | -0.10 | +3.42 | +1.45 | -3.44 | -6.16 | -1.66 | 0 | 0.0% | 0.1367 | 0.1531 | 0.0% | 0.0% | 98,856.42 |
| 2024-10-01 | 529.18 | 530.74 | 202410 | -15.56 | -1.19 | +5.58 | +2.11 | -4.77 | -5.90 | -11.38 | 0 | 0.0% | 0.1313 | 0.1532 | 0.0% | 0.0% | 98,856.42 |
| 2024-10-02 | 531.22 | 529.06 | 202410 | -15.02 | -1.19 | +5.58 | +2.61 | -5.53 | -5.98 | -10.51 | 0 | 0.0% | 0.1219 | 0.1531 | 0.0% | 0.0% | 98,856.42 |
| 2024-10-03 | 529.87 | 529.80 | 202410 | -7.88 | -1.19 | +5.81 | +2.32 | -5.10 | -6.22 | -3.49 | 0 | 0.0% | 0.1193 | 0.1532 | 0.0% | 0.0% | 98,856.42 |
| 2024-10-04 | 533.28 | 529.17 | 202410 | -8.90 | -1.19 | +5.45 | +2.97 | -6.12 | -5.76 | -4.26 | 0 | 0.0% | 0.1048 | 0.1534 | 0.0% | 0.0% | 98,856.42 |
| 2024-10-07 | 534.82 | 535.49 | 202410 | -6.53 | -1.19 | +4.90 | +3.12 | -6.34 | -4.93 | -2.09 | 0 | 0.0% | 0.0990 | 0.1535 | 0.0% | 0.0% | 98,856.42 |
| 2024-10-08 | 534.63 | 529.97 | 202410 | +1.71 | -1.19 | +5.24 | +3.13 | -6.38 | -4.98 | +5.90 | 0 | 0.0% | 0.0995 | 0.1535 | 0.0% | 0.0% | 98,856.42 |
| 2024-10-09 | 537.91 | 534.27 | 202410 | -0.83 | -1.19 | +1.76 | +2.72 | -5.95 | -0.59 | +2.43 | 0 | 0.0% | 0.0966 | 0.1524 | 0.0% | 0.0% | 98,856.42 |
| 2024-10-10 | 539.43 | 539.38 | 202410 | -4.88 | -1.19 | +0.11 | +2.44 | -5.55 | -1.20 | +0.53 | 0 | 0.0% | 0.0772 | 0.1518 | 0.0% | 0.0% | 98,856.42 |
| 2024-10-11 | 541.46 | 538.53 | 202410 | -8.73 | -1.19 | -1.69 | +2.24 | -5.25 | -1.30 | -1.53 | 0 | 0.0% | 0.0751 | 0.1514 | 0.0% | 0.0% | 98,856.42 |
| 2024-10-14 | 545.74 | 542.36 | 202410 | -13.20 | -1.19 | -2.38 | +2.88 | -6.21 | -1.42 | -4.88 | 0 | 0.0% | 0.0740 | 0.1520 | 0.0% | 0.0% | 98,856.42 |
| 2024-10-15 | 544.15 | 547.76 | 202410 | +4.11 | -1.19 | -0.01 | +3.17 | -6.63 | -0.85 | +9.62 | 0 | 0.0% | 0.0754 | 0.1511 | 0.0% | 0.0% | 98,856.42 |
| 2024-10-16 | 544.19 | 543.22 | 202410 | -3.23 | -1.19 | -3.34 | +1.96 | -4.89 | -1.26 | +5.51 | 0 | 0.0% | 0.0713 | 0.1463 | 0.0% | 0.0% | 98,856.42 |
| 2024-10-17 | 549.26 | 547.12 | 202410 | -13.04 | -1.19 | -6.16 | +2.07 | -5.11 | -0.86 | -1.79 | 0 | 0.0% | 0.0634 | 0.1468 | 0.0% | 0.0% | 98,856.42 |
| 2024-10-18 | 548.29 | 548.08 | 202410 | -7.07 | -1.19 | -5.32 | +1.87 | -4.87 | -1.26 | +3.70 | 0 | 0.0% | 0.0576 | 0.1469 | 0.0% | 0.0% | 98,856.42 |
| 2024-10-21 | 546.55 | 548.61 | 202410 | +2.86 | -1.19 | -4.29 | +1.69 | -4.55 | -1.46 | +12.66 | 0 | 0.0% | 0.0586 | 0.1471 | 0.0% | 0.0% | 98,856.42 |
| 2024-10-22 | 547.09 | 547.31 | 202410 | +5.34 | -1.19 | -4.38 | +1.70 | -4.51 | -2.11 | +15.84 | 0 | 0.0% | 0.0580 | 0.1471 | 0.0% | 0.0% | 98,856.42 |
| 2024-10-23 | 545.07 | 548.43 | 202410 | +25.14 | -1.19 | -0.60 | +2.22 | -5.47 | -2.00 | +32.18 | 1 | 83.1% | 0.0613 | 0.1445 | 83.1% | 0.0% | 98,856.42 |
| 2024-10-24 | 544.43 | 546.24 | 202410 | +24.95 | -1.19 | -2.28 | +1.38 | -4.14 | -1.76 | +32.95 | 1 | 84.1% | 0.0622 | 0.1427 | 82.9% | 82.9% | 98,502.48 |
| 2024-10-25 | 546.30 | 544.25 | 202410 | -5.76 | -1.19 | -10.81 | -1.22 | +1.16 | -0.93 | +7.23 | 0 | 0.0% | 0.0620 | 0.1136 | 0.0% | 83.0% | 98,783.18 |
| 2024-10-28 | 545.96 | 546.95 | 202410 | -5.24 | -1.19 | -14.64 | -3.30 | +5.86 | +2.37 | +5.67 | 0 | 0.0% | 0.0607 | 0.1018 | 0.0% | 0.0% | 98,798.46 |
| 2024-10-29 | 546.47 | 546.72 | 202410 | -5.41 | -1.19 | -13.03 | -3.07 | +4.74 | +3.40 | +3.74 | 0 | 0.0% | 0.0607 | 0.1008 | 0.0% | 0.0% | 98,798.46 |
| 2024-10-30 | 543.65 | 546.39 | 202410 | -3.60 | -1.19 | -9.24 | -2.78 | +3.71 | +3.95 | +1.96 | 0 | 0.0% | 0.0646 | 0.0985 | 0.0% | 0.0% | 98,798.46 |
| 2024-10-31 | 534.42 | 538.33 | 202410 | +2.05 | -1.19 | -5.95 | -4.06 | +7.58 | +4.67 | +1.01 | 0 | 0.0% | 0.0910 | 0.1055 | 0.0% | 0.0% | 98,798.46 |
| 2024-11-01 | 538.40 | 533.85 | 202411 | +1.34 | -6.55 | -8.54 | +7.17 | +0.62 | -0.02 | +8.66 | 0 | 0.0% | 0.0920 | 0.1061 | 0.0% | 0.0% | 98,798.46 |
| 2024-11-04 | 533.80 | 534.84 | 202411 | +4.52 | -6.55 | -6.87 | +9.13 | +3.59 | -0.09 | +5.31 | 0 | 0.0% | 0.0969 | 0.1080 | 0.0% | 0.0% | 98,798.46 |
| 2024-11-05 | 536.46 | 534.09 | 202411 | +3.60 | -6.55 | -6.16 | +6.64 | -0.11 | -0.06 | +9.85 | 0 | 0.0% | 0.0985 | 0.1067 | 0.0% | 0.0% | 98,798.46 |
| 2024-11-06 | 553.01 | 553.67 | 202411 | +3.37 | -6.55 | -10.93 | +0.88 | +1.31 | -0.17 | +18.83 | 0 | 0.0% | 0.1447 | 0.1225 | 0.0% | 0.0% | 98,798.46 |
| 2024-11-07 | 556.53 | 555.18 | 202411 | +1.52 | -6.55 | -8.75 | -3.17 | +9.95 | -0.18 | +10.23 | 0 | 0.0% | 0.1457 | 0.1185 | 0.0% | 0.0% | 98,798.46 |
| 2024-11-08 | 560.52 | 558.60 | 202411 | +1.71 | -6.55 | -9.81 | -4.30 | +12.99 | -0.16 | +9.55 | 0 | 0.0% | 0.1469 | 0.1191 | 0.0% | 0.0% | 98,798.46 |
| 2024-11-11 | 566.61 | 564.47 | 202411 | +2.31 | -6.55 | -11.43 | -6.06 | +18.59 | -0.26 | +8.03 | 0 | 0.0% | 0.1489 | 0.1207 | 0.0% | 0.0% | 98,798.46 |
| 2024-11-12 | 564.78 | 565.64 | 202411 | +0.64 | -6.55 | -11.16 | -4.50 | +13.99 | -0.25 | +9.12 | 0 | 0.0% | 0.1490 | 0.1208 | 0.0% | 0.0% | 98,798.46 |
| 2024-11-13 | 566.69 | 563.30 | 202411 | -0.14 | -6.55 | -11.56 | -4.82 | +14.70 | -0.25 | +8.34 | 0 | 0.0% | 0.1490 | 0.1208 | 0.0% | 0.0% | 98,798.46 |
| 2024-11-14 | 566.34 | 566.86 | 202411 | -0.85 | -6.55 | -10.90 | -4.29 | +13.81 | -0.35 | +7.43 | 0 | 0.0% | 0.1467 | 0.1209 | 0.0% | 0.0% | 98,798.46 |
| 2024-11-15 | 559.35 | 561.94 | 202411 | +0.96 | -6.55 | -8.30 | -1.10 | +6.16 | -0.32 | +11.08 | 0 | 0.0% | 0.1545 | 0.1242 | 0.0% | 0.0% | 98,798.46 |
| 2024-11-18 | 560.71 | 559.16 | 202411 | +0.34 | -6.55 | -8.80 | -0.91 | +5.87 | -0.35 | +11.08 | 0 | 0.0% | 0.1538 | 0.1242 | 0.0% | 0.0% | 98,798.46 |
| 2024-11-19 | 560.09 | 560.83 | 202411 | +0.74 | -6.55 | -8.47 | -0.10 | +4.36 | -0.35 | +11.85 | 0 | 0.0% | 0.1540 | 0.1243 | 0.0% | 0.0% | 98,798.46 |
| 2024-11-20 | 560.66 | 562.58 | 202411 | +0.54 | -6.55 | -8.64 | +0.33 | +3.74 | -0.37 | +12.03 | 0 | 0.0% | 0.1530 | 0.1243 | 0.0% | 0.0% | 98,798.46 |
| 2024-11-21 | 568.08 | 562.67 | 202411 | +0.64 | -6.55 | -8.86 | -4.74 | +14.45 | -0.33 | +6.69 | 0 | 0.0% | 0.1581 | 0.1248 | 0.0% | 0.0% | 98,798.46 |
| 2024-11-22 | 574.33 | 569.08 | 202411 | -2.86 | -6.55 | -11.98 | -5.48 | +16.62 | -0.41 | +4.94 | 0 | 0.0% | 0.1612 | 0.1258 | 0.0% | 0.0% | 98,798.46 |
| 2024-11-25 | 573.38 | 575.59 | 202411 | -1.09 | -6.55 | -10.18 | -5.79 | +17.33 | -0.44 | +4.54 | 0 | 0.0% | 0.1615 | 0.1257 | 0.0% | 0.0% | 98,798.46 |
| 2024-11-26 | 573.95 | 572.03 | 202411 | -3.35 | -6.55 | -12.61 | -3.03 | +10.88 | -0.44 | +8.41 | 0 | 0.0% | 0.1615 | 0.1234 | 0.0% | 0.0% | 98,798.46 |
| 2024-11-27 | 569.07 | 573.38 | 202411 | -4.40 | -6.55 | -13.48 | +2.80 | +0.86 | -0.47 | +12.43 | 0 | 0.0% | 0.1640 | 0.1218 | 0.0% | 0.0% | 98,798.46 |
| 2024-11-28 | 571.92 | 572.10 | 202411 | -5.11 | -6.55 | -16.26 | +3.93 | -0.28 | -0.42 | +14.48 | 0 | 0.0% | 0.1472 | 0.1208 | 0.0% | 0.0% | 98,798.46 |
| 2024-11-29 | 574.01 | 571.00 | 202411 | +3.03 | -6.55 | -20.58 | +7.38 | -1.28 | -0.44 | +24.50 | 0 | 0.0% | 0.1464 | 0.1164 | 0.0% | 0.0% | 98,798.46 |
| 2024-12-02 | 578.81 | 575.77 | 202412 | -1.89 | -4.32 | -20.75 | +0.95 | -0.01 | +0.42 | +21.81 | 0 | 0.0% | 0.1405 | 0.1153 | 0.0% | 0.0% | 98,798.46 |
| 2024-12-03 | 578.41 | 579.03 | 202412 | -2.37 | -4.32 | -20.10 | +1.18 | +0.06 | +0.38 | +20.43 | 0 | 0.0% | 0.1415 | 0.1154 | 0.0% | 0.0% | 98,798.46 |
| 2024-12-04 | 580.20 | 579.69 | 202412 | +3.12 | -4.32 | -21.92 | +1.48 | +0.56 | +0.43 | +26.89 | 0 | 0.0% | 0.1007 | 0.1146 | 0.0% | 0.0% | 98,798.46 |
| 2024-12-05 | 579.68 | 580.59 | 202412 | -5.67 | -4.32 | -17.21 | +0.62 | +0.13 | +0.49 | +14.62 | 0 | 0.0% | 0.1002 | 0.1096 | 0.0% | 0.0% | 98,798.46 |
| 2024-12-06 | 579.87 | 577.90 | 202412 | -6.11 | -4.32 | -15.43 | +0.37 | +0.46 | +0.50 | +12.32 | 0 | 0.0% | 0.0985 | 0.1091 | 0.0% | 0.0% | 98,798.46 |
| 2024-12-09 | 578.00 | 580.94 | 202412 | -5.05 | -4.32 | -15.58 | +1.06 | +0.06 | +0.51 | +13.22 | 0 | 0.0% | 0.0937 | 0.1088 | 0.0% | 0.0% | 98,798.46 |
| 2024-12-10 | 578.96 | 577.54 | 202412 | -4.76 | -4.32 | -14.46 | +0.74 | +0.00 | +0.57 | +12.71 | 0 | 0.0% | 0.0924 | 0.1085 | 0.0% | 0.0% | 98,798.46 |
| 2024-12-11 | 582.35 | 578.17 | 202412 | -4.66 | -4.32 | -16.81 | +0.89 | +0.02 | +0.58 | +14.99 | 0 | 0.0% | 0.0936 | 0.1079 | 0.0% | 0.0% | 98,798.46 |
| 2024-12-12 | 581.33 | 581.18 | 202412 | -3.70 | -4.32 | -12.97 | +0.36 | +0.29 | +0.56 | +12.38 | 0 | 0.0% | 0.0940 | 0.1054 | 0.0% | 0.0% | 98,798.46 |
| 2024-12-13 | 578.19 | 581.36 | 202412 | -2.41 | -4.32 | -13.07 | +1.34 | +0.47 | +0.58 | +12.59 | 0 | 0.0% | 0.0831 | 0.1052 | 0.0% | 0.0% | 98,798.46 |
| 2024-12-16 | 579.18 | 577.64 | 202412 | -1.21 | -4.32 | -11.65 | +0.98 | +0.07 | +0.59 | +13.12 | 0 | 0.0% | 0.0830 | 0.1047 | 0.0% | 0.0% | 98,798.46 |
| 2024-12-17 | 577.58 | 577.66 | 202412 | +0.37 | -4.32 | -10.91 | +1.41 | +0.63 | +0.60 | +12.95 | 0 | 0.0% | 0.0840 | 0.1050 | 0.0% | 0.0% | 98,798.46 |
| 2024-12-18 | 578.75 | 578.10 | 202412 | -0.19 | -4.32 | -11.18 | +1.39 | +0.70 | +0.59 | +12.62 | 0 | 0.0% | 0.0839 | 0.1050 | 0.0% | 0.0% | 98,798.46 |
| 2024-12-19 | 569.49 | 568.11 | 202412 | +6.73 | -4.32 | -7.07 | +2.56 | +4.63 | +0.60 | +10.33 | 0 | 0.0% | 0.0942 | 0.1111 | 0.0% | 0.0% | 98,798.46 |
| 2024-12-20 | 570.29 | 564.06 | 202412 | +7.02 | -4.32 | -6.44 | +2.39 | +3.79 | +0.60 | +11.00 | 0 | 0.0% | 0.0853 | 0.1109 | 0.0% | 0.0% | 98,798.46 |
| 2024-12-23 | 569.57 | 570.88 | 202412 | +6.66 | -4.32 | -6.62 | +2.79 | +5.78 | +0.60 | +8.43 | 0 | 0.0% | 0.0853 | 0.1108 | 0.0% | 0.0% | 98,798.46 |
| 2024-12-24 | 574.28 | 573.91 | 202412 | +3.92 | -4.32 | -7.96 | +2.21 | +3.34 | +0.57 | +10.07 | 0 | 0.0% | 0.0905 | 0.1117 | 0.0% | 0.0% | 98,798.46 |
| 2024-12-27 | 572.50 | 575.94 | 202412 | +5.80 | -4.32 | -6.59 | +2.32 | +3.88 | +0.59 | +9.92 | 0 | 0.0% | 0.0856 | 0.1119 | 0.0% | 0.0% | 98,798.46 |
| 2024-12-30 | 570.06 | 570.91 | 202412 | +6.04 | -4.32 | -6.13 | +2.93 | +6.95 | +0.60 | +6.01 | 0 | 0.0% | 0.0852 | 0.1122 | 0.0% | 0.0% | 98,798.46 |
| 2024-12-31 | 570.45 | 567.84 | 202412 | +7.79 | -4.32 | -5.09 | +2.58 | +5.30 | +0.56 | +8.77 | 0 | 0.0% | 0.0840 | 0.1117 | 0.0% | 0.0% | 98,798.46 |
| 2025-01-02 | 576.46 | 571.86 | 202501 | +3.12 | -3.95 | -6.45 | +2.25 | +1.45 | +0.40 | +9.42 | 0 | 0.0% | 0.0873 | 0.1133 | 0.0% | 0.0% | 98,798.46 |
| 2025-01-03 | 575.33 | 573.38 | 202501 | +3.48 | -3.95 | -6.22 | +2.59 | +2.44 | +0.40 | +8.22 | 0 | 0.0% | 0.0875 | 0.1135 | 0.0% | 0.0% | 98,798.46 |
| 2025-01-06 | 579.09 | 576.22 | 202501 | +2.79 | -3.95 | -6.49 | +2.01 | +0.61 | +0.16 | +10.45 | 0 | 0.0% | 0.0900 | 0.1135 | 0.0% | 0.0% | 98,798.46 |
| 2025-01-07 | 574.80 | 574.70 | 202501 | +6.98 | -3.95 | -4.35 | +2.56 | +1.73 | +0.21 | +10.78 | 0 | 0.0% | 0.0937 | 0.1149 | 0.0% | 0.0% | 98,798.46 |
| 2025-01-08 | 575.18 | 574.92 | 202501 | +7.32 | -3.95 | -3.98 | +2.27 | +1.30 | +0.28 | +11.41 | 0 | 0.0% | 0.0938 | 0.1147 | 0.0% | 0.0% | 98,798.46 |
| 2025-01-09 | 575.26 | 574.00 | 202501 | +9.42 | -3.95 | -2.73 | +1.72 | +0.42 | +0.33 | +13.63 | 0 | 0.0% | 0.0932 | 0.1138 | 0.0% | 0.0% | 98,798.46 |
| 2025-01-10 | 569.98 | 574.50 | 202501 | +12.22 | -3.95 | -1.86 | +2.87 | +2.92 | +0.33 | +11.92 | 0 | 0.0% | 0.0981 | 0.1155 | 0.0% | 0.0% | 98,798.46 |
| 2025-01-13 | 569.04 | 569.11 | 202501 | +13.14 | -3.95 | -1.18 | +3.22 | +3.72 | +0.35 | +10.98 | 0 | 0.0% | 0.0950 | 0.1156 | 0.0% | 0.0% | 98,798.46 |
| 2025-01-14 | 568.28 | 572.43 | 202501 | +15.40 | -3.95 | -0.11 | +2.65 | +2.10 | +0.37 | +14.35 | 0 | 0.0% | 0.0949 | 0.1142 | 0.0% | 0.0% | 98,798.46 |
| 2025-01-15 | 577.60 | 568.61 | 202501 | +8.39 | -3.95 | -1.53 | +1.49 | +0.17 | +0.40 | +11.82 | 0 | 0.0% | 0.1117 | 0.1186 | 0.0% | 0.0% | 98,798.46 |
| 2025-01-16 | 579.05 | 580.99 | 202501 | +5.46 | -3.95 | -2.82 | +1.63 | +0.39 | +0.40 | +9.81 | 0 | 0.0% | 0.1119 | 0.1183 | 0.0% | 0.0% | 98,798.46 |
| 2025-01-17 | 584.05 | 580.04 | 202501 | +2.55 | -3.95 | -4.05 | +0.90 | -0.07 | +0.40 | +9.33 | 0 | 0.0% | 0.1154 | 0.1193 | 0.0% | 0.0% | 98,798.46 |
| 2025-01-20 | 581.18 | 583.45 | 202501 | +3.73 | -3.95 | -3.71 | +1.91 | +0.80 | +0.40 | +8.29 | 0 | 0.0% | 0.1169 | 0.1196 | 0.0% | 0.0% | 98,798.46 |
| 2025-01-21 | 581.60 | 581.09 | 202501 | +3.74 | -3.95 | -4.00 | +2.12 | +1.20 | +0.38 | +8.00 | 0 | 0.0% | 0.0996 | 0.1195 | 0.0% | 0.0% | 98,798.46 |
| 2025-01-22 | 586.63 | 584.79 | 202501 | +3.41 | -3.95 | -4.59 | +1.18 | +0.07 | +0.35 | +10.35 | 0 | 0.0% | 0.1032 | 0.1204 | 0.0% | 0.0% | 98,798.46 |
| 2025-01-23 | 587.63 | 585.98 | 202501 | +4.09 | -3.95 | -5.04 | +1.27 | +0.16 | +0.30 | +11.35 | 0 | 0.0% | 0.1027 | 0.1203 | 0.0% | 0.0% | 98,798.46 |
| 2025-01-24 | 584.92 | 586.80 | 202501 | +4.23 | -3.95 | -3.80 | +1.82 | +0.83 | +0.24 | +9.09 | 0 | 0.0% | 0.1018 | 0.1209 | 0.0% | 0.0% | 98,798.46 |
| 2025-01-27 | 575.48 | 577.47 | 202501 | +5.84 | -3.95 | -1.51 | +4.07 | +6.66 | +0.35 | +0.22 | 0 | 0.0% | 0.1181 | 0.1254 | 0.0% | 0.0% | 98,798.46 |
| 2025-01-28 | 582.85 | 581.23 | 202501 | +13.42 | -3.95 | -7.63 | +4.62 | +8.94 | +0.33 | +11.11 | 0 | 0.0% | 0.1247 | 0.1219 | 0.0% | 0.0% | 98,798.46 |
| 2025-01-29 | 584.73 | 586.81 | 202501 | +14.45 | -3.95 | -6.91 | +3.85 | +6.33 | +0.28 | +14.85 | 0 | 0.0% | 0.1249 | 0.1214 | 0.0% | 0.0% | 98,798.46 |
| 2025-01-30 | 586.22 | 586.87 | 202501 | +19.45 | -3.95 | -9.97 | +4.49 | +9.33 | +0.32 | +19.23 | 0 | 0.0% | 0.1202 | 0.1196 | 0.0% | 0.0% | 98,798.46 |
| 2025-01-31 | 592.14 | 590.65 | 202501 | +22.61 | -3.95 | -11.73 | +3.32 | +5.44 | +0.25 | +29.28 | 1 | 96.8% | 0.1240 | 0.1207 | 96.8% | 0.0% | 98,798.46 |
| 2025-02-03 | 586.88 | 584.79 | 202502 | +15.34 | -0.89 | -7.10 | -5.51 | +2.57 | +3.55 | +22.72 | 1 | 94.0% | 0.1276 | 0.1068 | 95.4% | 95.4% | 99,041.64 |
| 2025-02-04 | 586.74 | 585.00 | 202502 | +15.52 | -0.89 | -5.34 | -4.18 | +1.86 | +3.27 | +20.81 | 1 | 96.7% | 0.1241 | 0.1062 | 95.4% | 95.4% | 99,018.70 |
| 2025-02-05 | 584.88 | 583.31 | 202502 | +15.84 | -0.89 | -2.58 | -3.42 | +1.47 | +2.97 | +18.29 | 1 | 96.0% | 0.1250 | 0.1057 | 95.4% | 95.4% | 98,719.36 |
| 2025-02-06 | 591.68 | 590.00 | 202502 | +21.59 | -0.89 | -2.84 | +2.45 | -1.33 | +3.10 | +21.10 | 1 | 91.9% | 0.1306 | 0.1060 | 91.9% | 95.4% | 99,813.66 |
| 2025-02-07 | 590.67 | 591.17 | 202502 | +20.87 | -0.89 | -3.25 | +0.73 | -0.58 | +2.93 | +21.93 | 1 | 95.9% | 0.1251 | 0.1058 | 95.9% | 92.5% | 99,650.97 |
| 2025-02-10 | 593.81 | 592.04 | 202502 | +20.86 | -0.89 | -3.78 | +2.64 | -1.41 | +2.90 | +21.40 | 1 | 96.0% | 0.1250 | 0.1061 | 95.5% | 95.5% | 100,146.71 |
| 2025-02-11 | 592.31 | 592.80 | 202502 | +21.94 | -0.89 | -3.27 | +1.31 | -0.88 | +3.53 | +22.14 | 1 | 95.6% | 0.1255 | 0.1063 | 95.5% | 95.5% | 99,905.10 |
| 2025-02-12 | 588.39 | 591.19 | 202502 | +14.54 | -0.89 | -4.85 | -4.43 | +2.07 | +3.31 | +19.33 | 1 | 100.0% | 0.1172 | 0.1039 | 100.0% | 95.4% | 99,273.74 |
| 2025-02-13 | 591.41 | 589.12 | 202502 | +19.71 | -0.89 | -5.59 | -2.73 | +1.14 | +3.29 | +24.51 | 1 | 100.0% | 0.1180 | 0.1042 | 99.6% | 99.6% | 99,772.16 |
| 2025-02-14 | 590.03 | 592.47 | 202502 | +16.86 | -0.89 | -5.29 | -4.09 | +1.96 | +2.89 | +22.29 | 1 | 100.0% | 0.1151 | 0.1043 | 99.6% | 99.6% | 99,540.92 |
| 2025-02-17 | 593.16 | 592.05 | 202502 | +22.66 | -0.89 | -6.47 | -2.72 | +1.25 | +2.35 | +29.14 | 1 | 100.0% | 0.1144 | 0.1047 | 99.6% | 99.6% | 100,066.24 |
| 2025-02-18 | 593.40 | 594.49 | 202502 | +21.18 | -0.89 | -3.07 | +0.50 | -0.43 | +2.15 | +22.93 | 1 | 100.0% | 0.1144 | 0.1016 | 99.6% | 99.6% | 100,106.24 |
| 2025-02-19 | 595.37 | 595.14 | 202502 | +22.47 | -0.89 | -1.04 | +3.73 | -1.88 | +2.11 | +20.45 | 1 | 100.0% | 0.1113 | 0.0995 | 99.6% | 99.6% | 100,437.40 |
| 2025-02-20 | 589.40 | 594.18 | 202502 | +31.82 | -0.89 | +1.17 | +0.57 | -0.45 | +1.65 | +29.78 | 1 | 100.0% | 0.1176 | 0.1018 | 99.6% | 99.6% | 99,434.74 |
| 2025-02-21 | 590.06 | 590.35 | 202502 | +31.34 | -0.89 | +1.13 | +0.91 | -0.60 | +1.13 | +29.67 | 1 | 100.0% | 0.1163 | 0.1018 | 99.6% | 99.6% | 99,546.45 |
| 2025-02-24 | 583.19 | 584.66 | 202502 | +29.36 | -0.89 | +1.99 | -4.80 | +2.54 | +2.62 | +27.92 | 1 | 100.0% | 0.1084 | 0.1032 | 99.6% | 99.6% | 98,392.00 |
| 2025-02-25 | 574.60 | 580.87 | 202502 | +54.72 | -0.89 | +7.46 | -7.69 | +4.44 | +2.41 | +48.99 | 1 | 100.0% | 0.1119 | 0.1073 | 99.6% | 99.6% | 96,947.77 |
| 2025-02-26 | 582.23 | 580.04 | 202502 | +43.63 | -0.89 | +4.79 | -3.08 | +1.51 | +1.62 | +39.67 | 1 | 98.6% | 0.1217 | 0.1104 | 99.6% | 99.6% | 98,230.37 |
| 2025-02-27 | 583.14 | 581.64 | 202502 | +59.59 | -0.89 | +6.64 | -0.49 | +0.11 | +2.14 | +52.08 | 1 | 98.8% | 0.1215 | 0.1092 | 99.6% | 99.6% | 98,382.93 |
| 2025-02-28 | 576.57 | 575.39 | 202502 | +75.55 | -0.89 | +9.71 | -3.73 | +1.93 | +2.47 | +66.06 | 1 | 99.1% | 0.1211 | 0.1117 | 99.6% | 99.6% | 97,279.66 |
| 2025-03-03 | 578.19 | 584.06 | 202503 | +20.65 | -3.85 | +2.49 | +0.85 | -0.24 | +0.40 | +20.99 | 1 | 100.0% | 0.1185 | 0.1116 | 99.6% | 99.6% | 97,551.33 |
| 2025-03-04 | 559.33 | 570.96 | 202503 | +38.20 | -3.85 | +9.78 | +4.44 | +6.99 | +0.52 | +20.33 | 1 | 72.7% | 0.1651 | 0.1306 | 72.7% | 99.6% | 94,382.61 |
| 2025-03-05 | 551.27 | 560.08 | 202503 | +45.00 | -3.85 | +14.67 | +5.59 | +11.69 | +0.53 | +16.37 | 1 | 70.3% | 0.1706 | 0.1337 | 72.6% | 72.6% | 93,400.32 |
| 2025-03-06 | 552.67 | 555.72 | 202503 | +39.40 | -3.85 | +12.56 | +5.44 | +11.35 | +0.53 | +13.37 | 1 | 73.5% | 0.1633 | 0.1338 | 72.6% | 72.6% | 93,572.48 |
| 2025-03-07 | 542.16 | 548.00 | 202503 | +48.30 | -3.85 | +20.59 | +6.84 | +16.75 | +0.52 | +7.45 | 1 | 69.6% | 0.1724 | 0.1389 | 72.3% | 72.3% | 92,280.09 |
| 2025-03-10 | 538.31 | 546.54 | 202503 | +54.43 | -3.85 | +25.93 | +6.53 | +16.41 | +0.53 | +8.88 | 1 | 71.1% | 0.1688 | 0.1387 | 72.1% | 72.1% | 91,805.46 |
| 2025-03-11 | 526.86 | 533.96 | 202503 | +56.64 | -3.85 | +34.37 | +7.69 | +21.45 | +0.50 | -3.52 | 1 | 67.2% | 0.1784 | 0.1447 | 67.2% | 71.7% | 90,397.55 |
| 2025-03-12 | 532.62 | 529.94 | 202503 | +43.39 | -3.85 | +26.84 | +6.97 | +19.68 | +0.51 | -6.77 | 1 | 63.8% | 0.1880 | 0.1467 | 63.8% | 67.8% | 91,084.08 |
| 2025-03-13 | 528.73 | 530.60 | 202503 | +47.24 | -3.85 | +30.76 | +7.16 | +20.31 | +0.53 | -7.68 | 1 | 65.1% | 0.1843 | 0.1471 | 64.2% | 64.2% | 90,640.13 |
| 2025-03-14 | 534.81 | 530.37 | 202503 | +37.92 | -3.85 | +24.29 | +6.28 | +17.35 | +0.51 | -6.67 | 1 | 61.9% | 0.1938 | 0.1495 | 64.4% | 64.4% | 91,309.67 |
| 2025-03-17 | 537.10 | 534.80 | 202503 | +35.71 | -3.85 | +23.34 | +5.61 | +14.53 | +0.47 | -4.39 | 1 | 62.1% | 0.1931 | 0.1497 | 64.5% | 64.5% | 91,561.69 |
| 2025-03-18 | 534.88 | 537.88 | 202503 | +18.54 | -3.85 | +18.15 | +6.95 | +19.79 | +0.46 | -22.97 | 1 | 62.5% | 0.1921 | 0.1466 | 64.4% | 64.4% | 91,316.61 |
| 2025-03-19 | 540.73 | 535.43 | 202503 | +8.41 | -3.85 | +14.34 | +5.88 | +15.79 | +0.41 | -24.16 | 1 | 60.5% | 0.1983 | 0.1486 | 60.5% | 64.7% | 91,960.17 |
| 2025-03-20 | 542.29 | 543.66 | 202503 | +4.67 | -3.85 | +12.72 | +5.60 | +14.68 | +0.33 | -24.82 | 1 | 60.3% | 0.1991 | 0.1488 | 60.6% | 60.6% | 92,138.20 |
| 2025-03-21 | 540.91 | 541.41 | 202503 | +10.27 | -3.85 | +16.81 | +5.07 | +12.01 | +0.08 | -19.85 | 1 | 60.5% | 0.1982 | 0.1476 | 60.6% | 60.6% | 91,996.15 |
| 2025-03-24 | 550.55 | 546.15 | 202503 | +3.50 | -3.85 | +9.23 | +3.60 | +6.09 | +0.05 | -11.61 | 1 | 56.9% | 0.2108 | 0.1524 | 56.9% | 61.0% | 92,988.71 |
| 2025-03-25 | 551.28 | 551.00 | 202503 | +4.11 | -3.85 | +7.42 | +3.72 | +6.69 | +0.05 | -9.92 | 1 | 58.2% | 0.2064 | 0.1523 | 57.5% | 57.5% | 93,058.40 |
| 2025-03-26 | 548.69 | 553.05 | 202503 | +5.38 | -3.85 | +9.10 | +4.02 | +7.71 | -0.21 | -11.38 | 1 | 60.5% | 0.1984 | 0.1525 | 60.5% | 57.3% | 92,807.27 |
| 2025-03-27 | 546.60 | 547.35 | 202503 | +8.45 | -3.85 | +13.91 | +3.26 | +4.86 | -0.14 | -9.59 | 1 | 60.7% | 0.1977 | 0.1508 | 60.2% | 60.2% | 92,598.10 |
| 2025-03-28 | 534.84 | 543.17 | 202503 | +15.42 | -3.85 | +21.78 | +5.12 | +12.66 | -0.35 | -19.94 | 1 | 58.1% | 0.2066 | 0.1568 | 59.7% | 59.7% | 91,398.53 |
| 2025-03-31 | 530.82 | 529.08 | 202503 | +24.16 | -3.85 | +27.89 | +4.97 | +12.06 | -0.27 | -16.65 | 1 | 58.4% | 0.2055 | 0.1565 | 59.5% | 59.5% | 90,988.92 |
| 2025-04-01 | 538.11 | 535.93 | 202504 | +15.88 | -3.18 | +18.40 | +5.11 | +10.41 | -0.44 | -14.41 | 1 | 65.1% | 0.1843 | 0.1589 | 65.1% | 59.8% | 91,732.02 |
| 2025-04-02 | 537.57 | 537.46 | 202504 | +16.57 | -3.18 | +19.04 | +4.98 | +9.66 | -0.67 | -13.26 | 1 | 67.3% | 0.1782 | 0.1589 | 64.5% | 64.5% | 91,673.40 |
| 2025-04-03 | 511.15 | 518.13 | 202504 | +39.14 | -3.18 | +40.07 | +8.87 | +22.95 | -0.39 | -29.18 | 1 | 48.3% | 0.2484 | 0.1882 | 48.3% | 63.3% | 88,768.16 |
| 2025-04-04 | 487.88 | 504.05 | 202504 | +50.76 | -3.18 | +55.54 | +10.72 | +23.25 | +0.15 | -35.72 | 1 | 41.8% | 0.2869 | 0.2088 | 41.8% | 47.3% | 86,615.25 |
| 2025-04-07 | 472.93 | 454.04 | 202504 | +59.77 | -3.18 | +67.01 | +10.78 | +21.85 | +0.75 | -37.44 | 1 | 39.8% | 0.3012 | 0.2168 | 41.6% | 41.6% | 85,185.48 |
| 2025-04-08 | 489.46 | 482.92 | 202504 | +32.76 | -3.18 | +53.30 | +10.06 | +23.76 | +0.79 | -51.97 | 1 | 36.6% | 0.3283 | 0.2300 | 36.6% | 42.5% | 86,425.03 |
| 2025-04-09 | 466.43 | 468.56 | 202504 | +69.28 | -3.18 | +76.99 | +10.75 | +22.51 | +0.81 | -38.60 | 1 | 33.4% | 0.3591 | 0.2450 | 35.8% | 35.8% | 84,714.71 |
| 2025-04-10 | 484.89 | 510.77 | 202504 | +43.46 | -3.18 | +64.51 | +8.63 | +24.06 | +0.88 | -51.43 | 1 | 30.5% | 0.3936 | 0.2597 | 30.5% | 36.7% | 85,914.60 |
| 2025-04-11 | 479.93 | 485.72 | 202504 | +56.24 | -3.18 | +71.22 | +8.33 | +23.93 | +0.82 | -44.88 | 1 | 30.8% | 0.3896 | 0.2590 | 30.8% | 30.8% | 85,644.97 |
| 2025-04-14 | 493.72 | 491.92 | 202504 | +39.75 | -3.18 | +58.88 | +5.71 | +20.18 | +0.77 | -42.60 | 1 | 29.5% | 0.4065 | 0.2669 | 31.4% | 31.4% | 86,403.61 |
| 2025-04-15 | 498.57 | 496.02 | 202504 | +35.52 | -3.18 | +55.27 | +4.17 | +15.50 | +0.65 | -36.89 | 1 | 29.3% | 0.4095 | 0.2681 | 31.6% | 31.6% | 86,670.12 |
| 2025-04-16 | 492.79 | 489.69 | 202504 | +43.19 | -3.18 | +62.97 | +4.05 | +14.64 | +0.49 | -35.79 | 1 | 29.5% | 0.4068 | 0.2677 | 31.4% | 31.4% | 86,352.40 |
| 2025-04-17 | 487.94 | 489.97 | 202504 | +48.35 | -3.18 | +67.23 | +4.53 | +15.42 | +0.28 | -35.93 | 1 | 29.5% | 0.4062 | 0.2679 | 31.2% | 31.2% | 86,085.62 |
| 2025-04-22 | 484.14 | 478.83 | 202504 | +51.07 | -3.18 | +68.29 | +5.30 | +17.48 | +0.11 | -36.94 | 1 | 29.5% | 0.4062 | 0.2680 | 31.0% | 31.0% | 85,876.62 |
| 2025-04-23 | 498.72 | 495.83 | 202504 | +26.10 | -3.18 | +50.49 | +3.19 | +10.56 | +0.20 | -35.15 | 1 | 28.8% | 0.4173 | 0.2749 | 31.6% | 31.6% | 86,678.56 |
| 2025-04-24 | 502.31 | 495.74 | 202504 | +20.15 | -3.18 | +52.76 | +0.53 | +1.89 | +0.07 | -31.91 | 1 | 28.6% | 0.4190 | 0.2738 | 28.6% | 31.8% | 86,876.04 |
| 2025-04-25 | 505.10 | 508.44 | 202504 | +16.05 | -3.18 | +51.74 | -0.83 | -0.14 | -0.15 | -31.39 | 1 | 28.5% | 0.4206 | 0.2741 | 29.0% | 29.0% | 87,043.51 |
| 2025-04-28 | 506.32 | 508.92 | 202504 | +15.84 | -3.18 | +51.77 | -1.88 | +0.27 | -0.18 | -30.97 | 1 | 28.5% | 0.4212 | 0.2740 | 29.1% | 29.1% | 87,104.59 |
| 2025-04-29 | 508.33 | 509.18 | 202504 | +22.82 | -3.18 | +54.13 | -3.69 | +5.43 | -0.36 | -29.51 | 1 | 28.8% | 0.4166 | 0.2731 | 29.1% | 29.1% | 87,205.19 |
| 2025-04-30 | 510.17 | 511.23 | 202504 | +16.27 | -3.18 | +48.94 | -3.71 | +5.26 | -0.26 | -30.78 | 1 | 28.8% | 0.4167 | 0.2731 | 29.2% | 29.2% | 87,297.18 |
| 2025-05-02 | 522.72 | 520.00 | 202505 | +18.86 | -5.24 | +38.86 | +0.29 | +8.15 | -0.12 | -23.09 | 1 | 28.3% | 0.4236 | 0.2785 | 29.7% | 29.7% | 87,924.52 |
| 2025-05-05 | 523.60 | 521.89 | 202505 | +17.47 | -5.24 | +37.29 | +0.29 | +8.73 | -0.34 | -23.27 | 1 | 28.3% | 0.4238 | 0.2786 | 29.8% | 29.8% | 87,968.69 |
| 2025-05-06 | 520.83 | 521.77 | 202505 | +23.03 | -5.24 | +43.06 | +0.29 | +11.34 | -0.79 | -25.64 | 1 | 31.3% | 0.3828 | 0.2772 | 29.7% | 29.7% | 87,830.32 |
| 2025-05-07 | 518.30 | 519.69 | 202505 | +22.60 | -5.24 | +44.33 | +0.30 | +10.77 | -1.11 | -26.44 | 1 | 35.3% | 0.3404 | 0.2773 | 35.3% | 29.5% | 87,703.43 |
| 2025-05-08 | 526.60 | 525.34 | 202505 | +22.10 | -5.24 | +40.75 | +0.23 | +16.47 | -1.56 | -28.56 | 1 | 37.7% | 0.3180 | 0.2794 | 35.3% | 35.3% | 88,125.40 |
| 2025-05-09 | 526.26 | 527.31 | 202505 | +19.67 | -5.24 | +40.17 | +0.23 | +16.61 | -1.84 | -30.26 | 1 | 40.1% | 0.2994 | 0.2794 | 40.1% | 35.2% | 88,104.96 |
| 2025-05-12 | 543.51 | 540.09 | 202505 | +12.98 | -5.24 | +26.19 | -0.02 | +20.36 | -1.87 | -26.44 | 1 | 41.7% | 0.2463 | 0.2878 | 40.8% | 40.8% | 89,145.96 |
| 2025-05-13 | 547.17 | 544.09 | 202505 | +11.27 | -5.24 | +25.79 | -0.18 | +21.28 | -2.17 | -28.20 | 1 | 41.7% | 0.2170 | 0.2880 | 41.0% | 41.0% | 89,391.16 |
| 2025-05-14 | 545.69 | 546.26 | 202505 | +8.81 | -5.24 | +25.87 | -0.15 | +21.16 | -2.62 | -30.21 | 1 | 41.7% | 0.2110 | 0.2880 | 40.9% | 40.9% | 89,292.19 |
| 2025-05-15 | 547.75 | 543.65 | 202505 | +5.73 | -5.24 | +26.39 | -0.32 | +21.62 | -2.95 | -33.77 | 1 | 41.7% | 0.1945 | 0.2879 | 41.0% | 41.0% | 89,429.97 |
| 2025-05-16 | 551.59 | 547.90 | 202505 | +0.20 | -5.24 | +24.16 | -0.44 | +21.84 | -3.38 | -36.74 | 1 | 41.6% | 0.1939 | 0.2884 | 41.2% | 41.2% | 89,687.50 |
| 2025-05-19 | 548.41 | 546.14 | 202505 | -9.10 | -5.24 | +27.53 | -0.42 | +21.84 | -3.74 | -49.07 | 0 | 0.0% | 0.1883 | 0.2884 | 0.0% | 41.1% | 89,474.42 |
| 2025-05-20 | 549.82 | 548.69 | 202505 | -15.66 | -5.24 | +23.00 | -0.32 | +21.75 | -4.53 | -50.33 | 0 | 0.0% | 0.1799 | 0.2879 | 0.0% | 0.0% | 89,455.95 |
| 2025-05-21 | 545.61 | 544.69 | 202505 | -22.36 | -5.24 | +26.22 | -0.25 | +21.65 | -5.29 | -59.44 | 0 | 0.0% | 0.1798 | 0.2882 | 0.0% | 0.0% | 89,455.95 |
| 2025-05-22 | 541.09 | 541.01 | 202505 | -21.69 | -5.24 | +25.20 | -0.02 | +20.88 | -4.71 | -57.81 | 0 | 0.0% | 0.1631 | 0.2877 | 0.0% | 0.0% | 89,455.95 |
| 2025-05-23 | 535.21 | 540.22 | 202505 | -21.05 | -5.24 | +23.90 | +0.19 | +18.63 | -4.87 | -53.66 | 0 | 0.0% | 0.1710 | 0.2870 | 0.0% | 0.0% | 89,455.95 |
| 2025-05-26 | 540.15 | 538.99 | 202505 | -10.66 | -5.24 | +25.38 | -0.01 | +20.97 | -5.62 | -46.14 | 0 | 0.0% | 0.1722 | 0.2863 | 0.0% | 0.0% | 89,455.95 |
| 2025-05-27 | 544.20 | 540.91 | 202505 | -9.28 | -5.24 | +23.35 | -0.14 | +21.51 | -6.15 | -42.62 | 0 | 0.0% | 0.1728 | 0.2868 | 0.0% | 0.0% | 89,455.95 |
| 2025-05-28 | 545.29 | 545.77 | 202505 | -14.49 | -5.24 | +18.81 | -0.05 | +21.20 | -6.66 | -42.55 | 0 | 0.0% | 0.1729 | 0.2861 | 0.0% | 0.0% | 89,455.95 |
| 2025-05-29 | 542.49 | 551.54 | 202505 | -4.98 | -5.24 | +21.65 | -0.03 | +21.18 | -6.92 | -35.62 | 0 | 0.0% | 0.1756 | 0.2861 | 0.0% | 0.0% | 89,455.95 |
| 2025-05-30 | 543.03 | 543.40 | 202505 | -21.95 | -5.24 | +11.45 | +0.21 | +18.36 | -5.79 | -40.94 | 0 | 0.0% | 0.1567 | 0.2782 | 0.0% | 0.0% | 89,455.95 |
| 2025-06-02 | 539.98 | 540.00 | 202506 | -13.54 | -4.58 | +6.06 | +2.30 | +16.60 | -4.31 | -29.62 | 0 | 0.0% | 0.1589 | 0.2769 | 0.0% | 0.0% | 89,455.95 |
| 2025-06-03 | 546.54 | 542.20 | 202506 | -15.84 | -4.58 | +4.38 | +2.59 | +19.60 | -4.43 | -33.40 | 0 | 0.0% | 0.1610 | 0.2780 | 0.0% | 0.0% | 89,455.95 |
| 2025-06-04 | 546.86 | 547.56 | 202506 | -22.60 | -4.58 | +2.58 | +2.23 | +15.78 | -4.61 | -34.00 | 0 | 0.0% | 0.1588 | 0.2751 | 0.0% | 0.0% | 89,455.95 |
| 2025-06-05 | 547.43 | 546.70 | 202506 | -22.88 | -4.58 | +2.43 | +2.09 | +14.08 | -4.18 | -32.73 | 0 | 0.0% | 0.1510 | 0.2747 | 0.0% | 0.0% | 89,455.95 |
| 2025-06-06 | 549.23 | 546.11 | 202506 | -29.77 | -4.58 | +1.61 | +1.70 | +8.51 | -3.72 | -33.30 | 0 | 0.0% | 0.1508 | 0.2710 | 0.0% | 0.0% | 89,455.95 |
| 2025-06-09 | 548.99 | 548.75 | 202506 | -23.86 | -4.58 | +2.31 | +1.87 | +11.26 | -3.68 | -31.04 | 0 | 0.0% | 0.1004 | 0.2702 | 0.0% | 0.0% | 89,455.95 |
| 2025-06-10 | 549.27 | 549.94 | 202506 | -25.25 | -4.58 | +1.98 | +1.71 | +8.89 | -3.93 | -29.34 | 0 | 0.0% | 0.0976 | 0.2697 | 0.0% | 0.0% | 89,455.95 |
| 2025-06-11 | 548.98 | 550.59 | 202506 | -17.11 | -4.58 | +2.48 | +1.91 | +11.81 | -4.33 | -24.41 | 0 | 0.0% | 0.0971 | 0.2688 | 0.0% | 0.0% | 89,455.95 |
| 2025-06-12 | 544.25 | 545.26 | 202506 | -12.36 | -4.58 | +2.86 | +1.82 | +10.32 | -4.57 | -18.22 | 0 | 0.0% | 0.1011 | 0.2693 | 0.0% | 0.0% | 89,455.95 |
| 2025-06-13 | 542.39 | 539.53 | 202506 | -12.33 | -4.58 | +2.83 | +1.68 | +7.94 | -5.04 | -15.16 | 0 | 0.0% | 0.0979 | 0.2692 | 0.0% | 0.0% | 89,455.95 |
| 2025-06-16 | 544.19 | 541.90 | 202506 | -10.08 | -4.58 | +3.16 | +1.96 | +12.04 | -5.60 | -17.05 | 0 | 0.0% | 0.0971 | 0.2684 | 0.0% | 0.0% | 89,455.95 |
| 2025-06-17 | 542.91 | 541.67 | 202506 | -9.13 | -4.58 | +3.54 | +1.97 | +12.16 | -6.14 | -16.08 | 0 | 0.0% | 0.0967 | 0.2684 | 0.0% | 0.0% | 89,455.95 |
| 2025-06-18 | 542.88 | 542.71 | 202506 | -9.27 | -4.58 | +3.37 | +1.92 | +11.37 | -6.77 | -14.59 | 0 | 0.0% | 0.0930 | 0.2683 | 0.0% | 0.0% | 89,455.95 |
| 2025-06-19 | 538.18 | 541.51 | 202506 | -2.42 | -4.58 | +7.23 | +2.09 | +14.01 | -7.33 | -13.84 | 0 | 0.0% | 0.0935 | 0.2664 | 0.0% | 0.0% | 89,455.95 |
| 2025-06-20 | 539.80 | 539.56 | 202506 | -1.65 | -4.58 | +6.90 | +2.18 | +15.34 | -7.76 | -13.73 | 0 | 0.0% | 0.0851 | 0.2664 | 0.0% | 0.0% | 89,455.95 |
| 2025-06-23 | 538.75 | 537.97 | 202506 | -1.44 | -4.58 | +6.34 | +2.07 | +13.75 | -7.97 | -11.06 | 0 | 0.0% | 0.0789 | 0.2663 | 0.0% | 0.0% | 89,455.95 |
| 2025-06-24 | 543.79 | 544.71 | 202506 | -3.45 | -4.58 | +4.25 | +2.19 | +15.31 | -8.52 | -12.11 | 0 | 0.0% | 0.0814 | 0.2669 | 0.0% | 0.0% | 89,455.95 |
| 2025-06-25 | 543.04 | 545.45 | 202506 | -7.09 | -4.58 | +2.95 | +1.77 | +8.68 | -9.18 | -6.73 | 0 | 0.0% | 0.0812 | 0.2631 | 0.0% | 0.0% | 89,455.95 |
| 2025-06-26 | 543.26 | 542.56 | 202506 | -7.54 | -4.58 | +2.81 | +1.62 | +6.42 | -9.36 | -4.45 | 0 | 0.0% | 0.0791 | 0.2626 | 0.0% | 0.0% | 89,455.95 |
| 2025-06-27 | 547.86 | 545.76 | 202506 | -5.00 | -4.58 | +2.94 | +2.04 | +12.69 | -9.87 | -8.22 | 0 | 0.0% | 0.0844 | 0.2617 | 0.0% | 0.0% | 89,455.95 |
| 2025-06-30 | 546.77 | 548.41 | 202506 | -4.32 | -4.58 | +2.99 | +1.98 | +11.65 | -10.08 | -6.28 | 0 | 0.0% | 0.0819 | 0.2617 | 0.0% | 0.0% | 89,455.95 |
| 2025-07-01 | 545.72 | 547.10 | 202507 | -10.05 | -5.27 | +2.03 | -1.41 | +0.43 | -10.54 | +4.71 | 0 | 0.0% | 0.0702 | 0.2396 | 0.0% | 0.0% | 89,455.95 |
| 2025-07-02 | 547.21 | 548.02 | 202507 | -19.67 | -5.27 | -6.62 | -0.09 | +4.05 | -8.09 | -3.66 | 0 | 0.0% | 0.0709 | 0.2180 | 0.0% | 0.0% | 89,455.95 |
| 2025-07-03 | 552.81 | 548.47 | 202507 | -13.03 | -5.27 | -13.49 | +1.12 | +10.67 | -5.28 | -0.78 | 0 | 0.0% | 0.0795 | 0.2074 | 0.0% | 0.0% | 89,455.95 |
| 2025-07-04 | 549.17 | 550.28 | 202507 | -20.74 | -5.27 | -5.97 | +0.43 | +4.57 | -4.50 | -10.01 | 0 | 0.0% | 0.0826 | 0.1974 | 0.0% | 0.0% | 89,455.95 |
| 2025-07-07 | 550.96 | 550.19 | 202507 | -2.47 | -5.27 | -14.75 | +2.39 | +17.03 | -3.75 | +1.88 | 0 | 0.0% | 0.0833 | 0.1675 | 0.0% | 0.0% | 89,455.95 |
| 2025-07-08 | 551.21 | 550.09 | 202507 | -13.19 | -5.27 | -7.90 | +1.26 | +8.51 | -2.77 | -7.02 | 0 | 0.0% | 0.0833 | 0.1497 | 0.0% | 0.0% | 89,455.95 |
| 2025-07-09 | 552.74 | 550.69 | 202507 | +0.88 | -5.27 | -10.19 | +1.70 | +11.75 | -2.67 | +5.55 | 0 | 0.0% | 0.0838 | 0.1475 | 0.0% | 0.0% | 89,455.95 |
| 2025-07-10 | 556.65 | 552.54 | 202507 | -1.78 | -5.27 | -6.30 | +0.73 | +3.71 | -2.54 | +7.89 | 0 | 0.0% | 0.0799 | 0.1376 | 0.0% | 0.0% | 89,455.95 |
| 2025-07-11 | 553.24 | 555.14 | 202507 | -9.30 | -5.27 | -3.22 | +0.75 | +3.73 | -2.43 | -2.86 | 0 | 0.0% | 0.0825 | 0.1376 | 0.0% | 0.0% | 89,455.95 |
| 2025-07-14 | 553.92 | 551.83 | 202507 | +1.12 | -5.27 | -5.68 | +1.19 | +7.22 | -2.42 | +6.08 | 0 | 0.0% | 0.0820 | 0.1348 | 0.0% | 0.0% | 89,455.95 |
| 2025-07-15 | 556.95 | 556.55 | 202507 | +17.46 | -5.27 | -8.58 | +1.51 | +9.54 | -2.26 | +22.51 | 0 | 0.0% | 0.0826 | 0.1327 | 0.0% | 0.0% | 89,455.95 |
| 2025-07-16 | 549.19 | 553.13 | 202507 | +7.51 | -5.27 | -7.40 | +2.53 | +16.11 | -2.05 | +3.59 | 0 | 0.0% | 0.0989 | 0.1353 | 0.0% | 0.0% | 89,455.95 |
| 2025-07-17 | 559.83 | 558.67 | 202507 | +26.26 | -5.27 | -5.39 | +0.97 | +4.66 | -1.99 | +33.27 | 1 | 94.0% | 0.1128 | 0.1276 | 94.0% | 0.0% | 89,455.95 |
| 2025-07-18 | 558.34 | 560.77 | 202507 | +23.10 | -5.27 | -3.39 | +0.98 | +4.46 | -1.73 | +28.05 | 1 | 94.1% | 0.1139 | 0.1275 | 94.1% | 94.1% | 89,007.95 |
| 2025-07-21 | 558.89 | 559.72 | 202507 | +24.70 | -5.27 | -2.49 | +0.89 | +3.76 | -1.72 | +29.53 | 1 | 94.3% | 0.1132 | 0.1273 | 94.1% | 94.1% | 89,090.58 |
| 2025-07-22 | 555.14 | 557.15 | 202507 | +19.56 | -5.27 | -0.69 | +1.18 | +5.55 | -1.35 | +20.13 | 1 | 93.4% | 0.1134 | 0.1284 | 94.1% | 94.1% | 88,528.50 |
| 2025-07-23 | 559.76 | 558.51 | 202507 | +29.89 | -5.27 | -1.53 | +0.92 | +3.42 | -1.36 | +33.70 | 1 | 93.0% | 0.1159 | 0.1291 | 94.1% | 94.1% | 89,220.49 |
| 2025-07-24 | 560.99 | 561.34 | 202507 | +33.11 | -5.27 | -1.48 | +0.93 | +2.86 | -1.12 | +37.19 | 1 | 93.0% | 0.1158 | 0.1290 | 94.1% | 94.1% | 89,406.28 |
| 2025-07-25 | 562.08 | 560.96 | 202507 | +22.39 | -5.27 | +2.74 | +0.32 | -0.14 | -0.68 | +25.42 | 1 | 100.0% | 0.1130 | 0.1200 | 100.0% | 94.1% | 89,569.18 |
| 2025-07-28 | 566.78 | 566.01 | 202507 | +29.44 | -5.27 | +1.45 | +0.18 | -0.23 | -0.38 | +33.69 | 1 | 99.3% | 0.1150 | 0.1209 | 99.8% | 99.8% | 90,276.54 |
| 2025-07-29 | 569.06 | 570.65 | 202507 | +36.87 | -5.27 | -0.26 | +0.29 | -0.24 | -0.34 | +42.69 | 1 | 99.8% | 0.1144 | 0.1202 | 99.8% | 99.8% | 90,638.91 |
| 2025-07-30 | 571.81 | 568.94 | 202507 | +43.65 | -5.27 | -2.21 | +0.39 | -0.15 | -0.30 | +51.19 | 1 | 100.0% | 0.1147 | 0.1197 | 99.8% | 99.8% | 91,076.33 |
| 2025-07-31 | 573.04 | 576.37 | 202507 | +36.08 | -5.27 | +0.21 | +0.00 | +0.17 | -0.21 | +41.17 | 1 | 100.0% | 0.1108 | 0.1159 | 99.8% | 99.8% | 91,270.61 |
| 2025-08-01 | 556.13 | 568.04 | 202508 | +14.26 | -4.68 | +6.44 | -0.33 | +4.30 | +0.11 | +8.42 | 1 | 76.9% | 0.1560 | 0.1325 | 76.9% | 99.8% | 88,582.80 |
| 2025-08-04 | 562.60 | 557.91 | 202508 | +12.26 | -4.68 | +7.81 | +0.08 | +0.33 | +0.41 | +8.31 | 1 | 74.7% | 0.1606 | 0.1176 | 77.4% | 77.4% | 89,422.40 |
| 2025-08-05 | 561.40 | 566.23 | 202508 | +14.79 | -4.68 | +7.88 | +0.13 | +0.65 | +0.41 | +10.40 | 1 | 74.5% | 0.1610 | 0.1170 | 77.3% | 77.3% | 89,274.38 |
| 2025-08-06 | 562.73 | 564.15 | 202508 | +13.46 | -4.68 | +7.84 | +0.12 | +0.53 | +0.44 | +9.22 | 1 | 74.6% | 0.1609 | 0.1169 | 77.4% | 77.4% | 89,438.00 |
| 2025-08-07 | 563.77 | 562.81 | 202508 | +14.39 | -4.68 | +8.20 | +0.16 | +1.04 | +0.52 | +9.16 | 1 | 75.3% | 0.1594 | 0.1167 | 77.4% | 77.4% | 89,565.79 |
| 2025-08-08 | 565.40 | 564.46 | 202508 | +15.55 | -4.68 | +8.16 | +0.29 | +2.47 | +0.49 | +8.82 | 1 | 76.2% | 0.1575 | 0.1160 | 77.5% | 77.5% | 89,766.92 |
| 2025-08-11 | 568.80 | 567.93 | 202508 | +11.88 | -4.68 | +7.69 | +0.28 | +2.32 | +0.50 | +5.76 | 1 | 75.7% | 0.1584 | 0.1158 | 77.6% | 77.6% | 90,184.53 |
| 2025-08-12 | 568.94 | 568.47 | 202508 | +13.24 | -4.68 | +7.77 | +0.31 | +2.63 | +0.46 | +6.76 | 1 | 76.1% | 0.1577 | 0.1158 | 77.6% | 77.6% | 90,201.93 |
| 2025-08-13 | 569.68 | 570.25 | 202508 | +11.60 | -4.68 | +7.37 | +0.21 | +1.33 | +0.41 | +6.97 | 1 | 81.5% | 0.1473 | 0.1145 | 81.5% | 77.6% | 90,293.79 |
| 2025-08-14 | 572.58 | 571.26 | 202508 | +10.25 | -4.68 | +6.30 | +0.15 | +0.71 | +0.42 | +7.35 | 1 | 90.2% | 0.1330 | 0.1133 | 90.2% | 81.5% | 90,654.15 |
| 2025-08-15 | 571.00 | 574.93 | 202508 | +12.30 | -4.68 | +5.40 | -0.04 | -0.01 | +0.41 | +11.23 | 1 | 90.2% | 0.1331 | 0.1108 | 89.7% | 89.7% | 90,391.65 |
| 2025-08-18 | 571.83 | 571.44 | 202508 | +10.34 | -4.68 | +6.25 | +0.06 | +0.14 | +0.42 | +8.15 | 1 | 90.2% | 0.1331 | 0.1095 | 89.7% | 89.7% | 90,510.02 |
| 2025-08-19 | 571.91 | 571.69 | 202508 | +10.71 | -4.68 | +6.83 | +0.13 | +0.58 | +0.38 | +7.46 | 1 | 92.4% | 0.1299 | 0.1087 | 89.7% | 89.7% | 90,521.12 |
| 2025-08-20 | 568.84 | 570.31 | 202508 | +13.58 | -4.68 | +7.23 | +0.07 | +0.19 | +0.37 | +10.39 | 1 | 92.7% | 0.1294 | 0.1094 | 92.7% | 89.7% | 90,085.11 |
| 2025-08-21 | 570.73 | 570.97 | 202508 | +10.89 | -4.68 | +6.62 | +0.04 | +0.03 | +0.27 | +8.61 | 1 | 92.5% | 0.1297 | 0.1088 | 92.2% | 92.2% | 90,351.13 |
| 2025-08-22 | 573.73 | 570.16 | 202508 | +9.78 | -4.68 | +6.25 | +0.09 | +0.26 | +0.29 | +7.56 | 1 | 91.9% | 0.1306 | 0.1092 | 92.3% | 92.3% | 90,789.08 |
| 2025-08-25 | 573.47 | 572.26 | 202508 | +9.55 | -4.68 | +5.64 | -0.01 | -0.03 | +0.35 | +8.27 | 1 | 93.9% | 0.1277 | 0.1084 | 92.3% | 92.3% | 90,751.15 |
| 2025-08-26 | 572.25 | 572.84 | 202508 | +12.41 | -4.68 | +6.71 | +0.10 | +0.27 | +0.33 | +9.68 | 1 | 94.2% | 0.1274 | 0.1061 | 92.2% | 92.2% | 90,572.21 |
| 2025-08-27 | 576.66 | 575.92 | 202508 | +9.66 | -4.68 | +5.95 | +0.19 | +0.91 | +0.28 | +7.01 | 1 | 92.9% | 0.1292 | 0.1070 | 92.3% | 92.3% | 91,215.99 |
| 2025-08-28 | 575.12 | 576.64 | 202508 | +11.28 | -4.68 | +6.05 | +0.16 | +0.54 | +0.22 | +8.99 | 1 | 92.7% | 0.1294 | 0.1073 | 92.3% | 92.3% | 90,990.94 |
| 2025-08-29 | 570.93 | 575.89 | 202508 | +15.54 | -4.68 | +6.42 | +0.09 | +0.14 | +0.18 | +13.41 | 1 | 100.0% | 0.0716 | 0.1084 | 100.0% | 92.2% | 90,379.60 |
| 2025-09-01 | 572.50 | 571.05 | 202509 | +12.91 | -5.17 | +5.46 | +0.03 | +0.36 | +0.17 | +12.06 | 1 | 100.0% | 0.0609 | 0.1085 | 99.8% | 99.8% | 90,619.41 |
| 2025-09-02 | 565.93 | 571.43 | 202509 | +16.48 | -5.17 | +5.83 | -0.02 | +0.03 | +0.22 | +15.59 | 1 | 100.0% | 0.0746 | 0.1114 | 99.8% | 99.8% | 89,581.03 |
| 2025-09-03 | 569.83 | 570.67 | 202509 | +14.64 | -5.17 | +5.48 | -0.00 | +0.02 | +0.25 | +14.06 | 1 | 100.0% | 0.0778 | 0.1121 | 99.8% | 99.8% | 90,197.51 |
| 2025-09-04 | 574.55 | 572.27 | 202509 | +8.53 | -5.17 | +4.14 | -0.01 | -0.00 | +0.24 | +9.32 | 1 | 100.0% | 0.0824 | 0.1115 | 99.8% | 99.8% | 90,943.03 |
| 2025-09-05 | 570.63 | 577.00 | 202509 | +9.19 | -5.17 | +4.23 | -0.05 | +0.56 | +0.17 | +9.45 | 1 | 100.0% | 0.0865 | 0.1123 | 99.8% | 99.8% | 90,323.43 |
| 2025-09-08 | 574.28 | 573.91 | 202509 | +8.03 | -5.17 | +3.92 | -0.03 | +0.06 | +0.13 | +9.12 | 1 | 100.0% | 0.0868 | 0.1127 | 99.8% | 99.8% | 90,899.94 |
| 2025-09-09 | 574.30 | 573.53 | 202509 | +6.88 | -5.17 | +3.50 | -0.04 | +0.26 | +0.05 | +8.28 | 1 | 100.0% | 0.0868 | 0.1125 | 99.8% | 99.8% | 90,903.46 |
| 2025-09-10 | 577.38 | 578.64 | 202509 | +5.68 | -5.17 | +2.82 | -0.03 | +0.08 | +0.03 | +7.94 | 1 | 100.0% | 0.0885 | 0.1129 | 99.8% | 99.8% | 91,390.41 |
| 2025-09-11 | 581.07 | 579.28 | 202509 | +7.89 | -5.17 | +0.60 | -0.04 | +0.35 | -0.16 | +12.31 | 1 | 100.0% | 0.0895 | 0.1116 | 99.8% | 99.8% | 91,973.53 |
| 2025-09-12 | 581.38 | 580.81 | 202509 | +7.00 | -5.17 | +0.69 | -0.04 | +0.28 | -0.30 | +11.54 | 1 | 100.0% | 0.0885 | 0.1115 | 99.8% | 99.8% | 92,021.81 |
| 2025-09-15 | 581.84 | 581.88 | 202509 | +8.77 | -5.17 | +0.14 | -0.05 | +0.58 | -0.15 | +13.43 | 1 | 100.0% | 0.0885 | 0.1113 | 99.8% | 99.8% | 92,095.62 |
| 2025-09-16 | 577.10 | 581.45 | 202509 | +5.26 | -5.17 | +2.33 | -0.06 | +0.70 | -0.18 | +7.64 | 1 | 100.0% | 0.0942 | 0.1117 | 99.8% | 99.8% | 91,346.35 |
| 2025-09-17 | 576.53 | 577.27 | 202509 | +4.80 | -5.17 | +2.24 | -0.06 | +1.23 | -0.43 | +6.99 | 1 | 100.0% | 0.0918 | 0.1117 | 99.8% | 99.8% | 91,256.89 |
| 2025-09-18 | 583.05 | 580.56 | 202509 | +7.61 | -5.17 | +0.74 | -0.03 | +0.25 | -0.56 | +12.38 | 1 | 100.0% | 0.0989 | 0.1136 | 99.8% | 99.8% | 92,286.31 |
| 2025-09-19 | 583.71 | 581.84 | 202509 | +5.32 | -5.17 | +1.46 | +0.01 | -0.00 | -0.80 | +9.82 | 1 | 100.0% | 0.0976 | 0.1126 | 99.8% | 99.8% | 92,391.00 |
| 2025-09-22 | 584.93 | 584.95 | 202509 | +6.04 | -5.17 | +0.67 | -0.01 | +0.03 | -0.79 | +11.31 | 1 | 100.0% | 0.0976 | 0.1124 | 99.8% | 99.8% | 92,583.00 |
| 2025-09-23 | 585.32 | 585.80 | 202509 | +7.29 | -5.17 | +0.39 | -0.03 | +0.16 | -0.69 | +12.63 | 1 | 100.0% | 0.0969 | 0.1123 | 99.8% | 99.8% | 92,645.38 |
| 2025-09-24 | 584.38 | 583.63 | 202509 | +6.37 | -5.17 | +1.08 | -0.04 | +0.22 | -0.30 | +10.58 | 1 | 100.0% | 0.0942 | 0.1124 | 99.8% | 99.8% | 92,496.39 |
| 2025-09-25 | 583.71 | 582.79 | 202509 | +5.57 | -5.17 | +2.22 | -0.00 | -0.00 | -0.31 | +8.83 | 1 | 100.0% | 0.0936 | 0.1108 | 99.8% | 99.8% | 92,391.25 |
| 2025-09-26 | 584.19 | 583.69 | 202509 | +5.28 | -5.17 | +1.27 | -0.04 | +0.26 | -0.40 | +9.36 | 1 | 100.0% | 0.0886 | 0.1097 | 99.8% | 99.8% | 92,465.91 |
| 2025-09-29 | 585.74 | 586.38 | 202509 | +5.55 | -5.17 | +1.25 | -0.02 | +0.07 | -0.23 | +9.66 | 1 | 100.0% | 0.0886 | 0.1097 | 99.8% | 99.8% | 92,710.97 |
| 2025-09-30 | 585.07 | 584.89 | 202509 | +5.11 | -5.17 | +1.14 | -0.04 | +0.19 | -0.26 | +9.25 | 1 | 100.0% | 0.0756 | 0.1098 | 99.8% | 99.8% | 92,605.92 |
| 2025-10-01 | 589.41 | 582.62 | 202510 | +4.48 | -5.57 | +2.00 | -0.06 | +0.16 | -0.25 | +8.20 | 1 | 100.0% | 0.0761 | 0.1105 | 99.8% | 99.8% | 93,291.02 |
| 2025-10-02 | 591.48 | 591.07 | 202510 | +3.90 | -5.57 | +2.35 | -0.23 | +0.98 | -0.27 | +6.65 | 1 | 100.0% | 0.0724 | 0.1099 | 99.8% | 99.8% | 93,618.85 |
| 2025-10-03 | 593.99 | 594.01 | 202510 | +5.99 | -5.57 | +1.23 | -0.16 | +0.51 | -0.30 | +10.28 | 1 | 100.0% | 0.0660 | 0.1091 | 99.8% | 99.8% | 94,015.37 |
| 2025-10-06 | 595.94 | 595.96 | 202510 | +6.00 | -5.57 | +0.55 | -0.19 | +0.73 | -0.20 | +10.68 | 1 | 100.0% | 0.0642 | 0.1092 | 99.8% | 99.8% | 94,323.77 |
| 2025-10-07 | 595.10 | 595.86 | 202510 | +3.83 | -5.57 | +1.44 | -0.22 | +0.94 | -0.08 | +7.32 | 1 | 100.0% | 0.0649 | 0.1089 | 99.8% | 99.8% | 94,189.78 |
| 2025-10-08 | 600.36 | 597.47 | 202510 | +14.21 | -5.57 | -1.68 | -0.05 | +0.19 | -0.04 | +21.35 | 1 | 100.0% | 0.0685 | 0.1054 | 99.8% | 99.8% | 95,021.62 |
| 2025-10-09 | 600.60 | 600.84 | 202510 | +3.83 | -5.57 | +0.78 | -0.39 | +2.41 | -0.07 | +6.66 | 1 | 100.0% | 0.0666 | 0.0987 | 99.8% | 99.8% | 95,059.62 |
| 2025-10-10 | 588.75 | 600.17 | 202510 | +3.87 | -5.57 | +2.36 | +0.13 | -0.07 | +0.05 | +6.97 | 1 | 100.0% | 0.1016 | 0.1075 | 99.8% | 99.8% | 93,187.34 |
| 2025-10-13 | 593.54 | 590.56 | 202510 | +2.69 | -5.57 | +1.55 | -0.03 | +0.15 | +0.17 | +6.41 | 1 | 100.0% | 0.1050 | 0.1085 | 99.8% | 99.8% | 93,943.48 |
| 2025-10-14 | 590.64 | 588.73 | 202510 | +2.42 | -5.57 | +1.34 | +0.34 | +0.08 | +0.30 | +5.93 | 1 | 100.0% | 0.1018 | 0.1080 | 99.8% | 99.8% | 93,485.07 |
| 2025-10-15 | 594.28 | 593.37 | 202510 | +2.47 | -5.57 | +1.35 | +0.00 | +0.09 | +0.17 | +6.42 | 1 | 100.0% | 0.1030 | 0.1075 | 99.8% | 99.8% | 94,061.33 |
| 2025-10-16 | 593.58 | 594.09 | 202510 | +3.07 | -5.57 | +1.77 | +0.03 | +0.04 | +0.24 | +6.56 | 1 | 100.0% | 0.0966 | 0.1076 | 99.8% | 99.8% | 93,949.44 |
| 2025-10-17 | 587.38 | 582.34 | 202510 | +5.67 | -5.57 | +1.98 | +0.33 | +0.03 | +0.45 | +8.45 | 1 | 100.0% | 0.1047 | 0.1101 | 99.8% | 99.8% | 92,970.85 |
| 2025-10-20 | 597.46 | 594.18 | 202510 | +3.65 | -5.57 | +1.52 | -0.24 | +1.35 | +0.57 | +6.01 | 1 | 99.7% | 0.1203 | 0.1140 | 99.8% | 99.8% | 94,563.74 |
| 2025-10-21 | 599.81 | 598.02 | 202510 | +3.93 | -5.57 | +1.52 | -0.37 | +2.42 | +0.58 | +5.34 | 1 | 99.4% | 0.1207 | 0.1140 | 99.8% | 99.8% | 94,935.14 |
| 2025-10-22 | 596.32 | 599.65 | 202510 | +7.80 | -5.57 | +2.03 | -0.31 | +1.94 | +0.59 | +9.11 | 1 | 97.6% | 0.1230 | 0.1145 | 99.8% | 99.8% | 94,382.39 |
| 2025-10-23 | 598.82 | 598.47 | 202510 | +8.00 | -5.57 | +2.29 | -0.40 | +2.89 | +0.57 | +8.23 | 1 | 97.4% | 0.1232 | 0.1147 | 99.8% | 99.8% | 94,778.57 |
| 2025-10-24 | 603.31 | 601.07 | 202510 | +6.65 | -5.57 | -1.23 | +0.15 | -0.04 | +0.64 | +12.70 | 1 | 95.9% | 0.1251 | 0.0961 | 95.9% | 99.8% | 95,487.87 |
| 2025-10-27 | 607.16 | 607.62 | 202510 | +5.19 | -5.57 | -0.38 | -0.19 | +1.24 | +0.66 | +9.43 | 1 | 95.1% | 0.1262 | 0.0943 | 96.0% | 96.0% | 96,095.19 |
| 2025-10-28 | 608.42 | 607.21 | 202510 | +6.21 | -5.57 | -0.98 | -0.13 | +0.88 | +0.65 | +11.35 | 1 | 95.4% | 0.1257 | 0.0940 | 96.0% | 96.0% | 96,285.94 |
| 2025-10-29 | 609.35 | 611.14 | 202510 | +4.97 | -5.57 | -1.26 | -0.15 | +1.03 | +0.66 | +10.25 | 1 | 96.7% | 0.1241 | 0.0940 | 96.1% | 96.1% | 96,427.35 |
| 2025-10-30 | 610.19 | 609.88 | 202510 | +4.22 | -5.57 | -1.32 | -0.18 | +1.11 | +0.65 | +9.52 | 1 | 96.8% | 0.1239 | 0.0940 | 96.1% | 96.1% | 96,555.07 |
| 2025-10-31 | 609.37 | 611.09 | 202510 | +2.48 | -5.57 | -1.22 | -0.14 | +0.98 | +0.66 | +7.76 | 1 | 96.9% | 0.1239 | 0.0941 | 96.1% | 96.1% | 96,431.47 |
| 2025-11-03 | 610.50 | 610.20 | 202511 | +5.84 | -6.61 | -1.24 | +0.12 | +1.96 | +1.34 | +10.27 | 1 | 97.0% | 0.1237 | 0.0936 | 96.1% | 96.1% | 96,601.93 |
| 2025-11-04 | 608.19 | 605.12 | 202511 | +6.26 | -6.61 | -0.99 | +0.05 | +1.08 | +1.34 | +11.38 | 1 | 96.3% | 0.1246 | 0.0941 | 96.0% | 96.0% | 96,251.89 |
| 2025-11-05 | 609.18 | 604.16 | 202511 | +6.35 | -6.61 | -1.29 | +0.05 | +1.18 | +1.32 | +11.71 | 1 | 98.9% | 0.1213 | 0.0941 | 96.1% | 96.1% | 96,401.23 |
| 2025-11-06 | 600.58 | 606.08 | 202511 | +12.64 | -6.61 | +0.05 | -0.09 | +0.10 | +1.30 | +17.89 | 1 | 90.6% | 0.1324 | 0.0988 | 90.6% | 96.0% | 95,095.20 |
| 2025-11-07 | 592.78 | 602.24 | 202511 | +14.02 | -6.61 | +0.32 | -0.30 | +0.14 | +1.30 | +19.17 | 1 | 99.7% | 0.1204 | 0.1026 | 99.7% | 90.8% | 93,979.78 |
| 2025-11-10 | 604.55 | 603.58 | 202511 | +8.81 | -6.61 | -0.78 | -0.06 | +0.25 | +1.28 | +14.73 | 1 | 88.1% | 0.1362 | 0.1098 | 88.1% | 99.2% | 95,679.52 |
| 2025-11-11 | 606.74 | 607.83 | 202511 | +7.64 | -6.61 | -0.86 | -0.03 | +0.40 | +1.33 | +13.40 | 1 | 89.0% | 0.1348 | 0.1099 | 88.5% | 88.5% | 96,032.07 |
| 2025-11-12 | 610.27 | 611.21 | 202511 | +4.37 | -6.61 | -1.78 | -0.05 | +0.26 | +1.34 | +11.19 | 1 | 89.1% | 0.1346 | 0.1095 | 88.5% | 88.5% | 96,525.96 |
| 2025-11-13 | 602.58 | 610.50 | 202511 | +8.08 | -6.61 | -0.37 | -0.19 | -0.14 | +1.34 | +14.05 | 1 | 83.7% | 0.1434 | 0.1130 | 83.7% | 88.4% | 95,449.15 |
| 2025-11-14 | 601.04 | 598.09 | 202511 | +10.81 | -6.61 | +0.03 | -0.18 | -0.14 | +1.34 | +16.36 | 1 | 87.1% | 0.1378 | 0.1129 | 87.1% | 84.0% | 95,208.12 |
| 2025-11-17 | 598.46 | 602.25 | 202511 | +11.12 | -6.61 | +0.20 | -0.25 | -0.02 | +1.34 | +16.46 | 1 | 95.7% | 0.1254 | 0.1133 | 95.7% | 86.4% | 94,847.98 |
| 2025-11-18 | 590.65 | 590.76 | 202511 | +11.56 | -6.61 | +0.54 | -0.40 | +1.55 | +1.34 | +15.12 | 1 | 90.3% | 0.1329 | 0.1167 | 90.3% | 95.1% | 93,768.82 |
| 2025-11-19 | 592.15 | 589.74 | 202511 | +13.41 | -6.61 | +0.61 | -0.32 | +0.46 | +1.33 | +17.95 | 1 | 90.9% | 0.1320 | 0.1158 | 90.7% | 90.7% | 93,973.72 |
| 2025-11-20 | 596.24 | 600.41 | 202511 | +10.15 | -6.61 | +0.41 | -0.29 | +0.21 | +1.28 | +15.14 | 1 | 89.9% | 0.1335 | 0.1164 | 90.8% | 90.8% | 94,562.01 |
| 2025-11-21 | 589.45 | 585.08 | 202511 | +7.24 | -6.61 | +0.32 | -0.43 | +2.80 | +1.29 | +9.87 | 1 | 88.3% | 0.1359 | 0.1179 | 90.7% | 90.7% | 93,585.41 |
| 2025-11-24 | 597.29 | 593.68 | 202511 | +4.73 | -6.61 | -0.01 | -0.34 | +0.65 | +1.29 | +9.75 | 1 | 83.9% | 0.1430 | 0.1206 | 83.9% | 90.8% | 94,714.45 |
| 2025-11-25 | 598.75 | 598.08 | 202511 | -1.14 | -6.61 | -0.90 | -0.41 | +2.10 | +1.25 | +3.44 | 0 | 0.0% | 0.1431 | 0.1180 | 0.0% | 84.5% | 94,911.09 |
| 2025-11-26 | 605.95 | 603.70 | 202511 | +2.06 | -6.61 | -1.27 | -0.27 | +0.15 | +1.23 | +8.84 | 0 | 0.0% | 0.1499 | 0.1195 | 0.0% | 0.0% | 95,494.21 |
| 2025-11-27 | 605.40 | 605.42 | 202511 | +2.03 | -6.61 | -0.49 | -0.20 | -0.10 | +1.09 | +8.33 | 0 | 0.0% | 0.1498 | 0.1186 | 0.0% | 0.0% | 95,494.21 |
| 2025-11-28 | 607.69 | 607.54 | 202511 | +3.27 | -6.61 | -1.21 | -0.25 | +0.12 | +0.92 | +10.29 | 0 | 0.0% | 0.1505 | 0.1176 | 0.0% | 0.0% | 95,494.21 |
| 2025-12-01 | 605.22 | 604.04 | 202512 | +2.14 | -7.46 | -0.00 | -0.10 | -0.02 | +0.80 | +8.93 | 0 | 0.0% | 0.1509 | 0.1176 | 0.0% | 0.0% | 95,494.21 |
| 2025-12-02 | 605.26 | 604.17 | 202512 | +2.08 | -7.46 | +0.18 | -0.10 | +0.04 | +0.64 | +8.77 | 0 | 0.0% | 0.1504 | 0.1176 | 0.0% | 0.0% | 95,494.21 |
| 2025-12-03 | 605.13 | 605.93 | 202512 | +2.52 | -7.46 | +0.51 | -0.09 | -0.08 | +0.64 | +9.01 | 0 | 0.0% | 0.1502 | 0.1172 | 0.0% | 0.0% | 95,494.21 |
| 2025-12-04 | 606.88 | 606.74 | 202512 | +3.03 | -7.46 | +0.64 | -0.06 | -0.17 | +0.38 | +9.70 | 0 | 0.0% | 0.1413 | 0.1167 | 0.0% | 0.0% | 95,494.21 |
| 2025-12-05 | 609.09 | 608.50 | 202512 | +2.98 | -7.46 | +0.53 | -0.05 | -0.14 | +0.41 | +9.69 | 0 | 0.0% | 0.1321 | 0.1169 | 0.0% | 0.0% | 95,494.21 |
| 2025-12-08 | 608.05 | 608.95 | 202512 | +2.93 | -7.46 | +0.70 | -0.06 | -0.17 | +0.33 | +9.59 | 0 | 0.0% | 0.1133 | 0.1170 | 0.0% | 0.0% | 95,494.21 |
| 2025-12-09 | 608.69 | 608.31 | 202512 | +2.96 | -7.46 | +0.37 | -0.09 | -0.06 | +0.12 | +10.09 | 0 | 0.0% | 0.1126 | 0.1155 | 0.0% | 0.0% | 95,494.21 |
| 2025-12-10 | 607.32 | 606.72 | 202512 | +2.35 | -7.46 | +0.44 | -0.10 | +0.16 | -0.29 | +9.60 | 0 | 0.0% | 0.1109 | 0.1156 | 0.0% | 0.0% | 95,494.21 |
| 2025-12-11 | 605.21 | 603.69 | 202512 | +2.48 | -7.46 | +1.05 | -0.09 | -0.10 | -0.06 | +9.13 | 0 | 0.0% | 0.1016 | 0.1139 | 0.0% | 0.0% | 95,494.21 |
| 2025-12-12 | 601.42 | 608.45 | 202512 | +2.62 | -7.46 | +1.15 | -0.10 | +0.15 | -0.38 | +9.25 | 0 | 0.0% | 0.1038 | 0.1148 | 0.0% | 0.0% | 95,494.21 |
| 2025-12-15 | 602.47 | 604.64 | 202512 | +2.57 | -7.46 | +1.24 | -0.09 | +0.02 | -0.41 | +9.27 | 0 | 0.0% | 0.1027 | 0.1148 | 0.0% | 0.0% | 95,494.21 |
| 2025-12-16 | 598.38 | 598.94 | 202512 | +3.11 | -7.46 | +0.99 | -0.10 | +0.41 | -0.27 | +9.54 | 0 | 0.0% | 0.0938 | 0.1157 | 0.0% | 0.0% | 95,494.21 |
| 2025-12-17 | 595.78 | 601.75 | 202512 | +2.22 | -7.46 | +0.93 | -0.10 | +0.97 | -0.30 | +8.17 | 0 | 0.0% | 0.0951 | 0.1161 | 0.0% | 0.0% | 95,494.21 |
| 2025-12-18 | 602.35 | 595.98 | 202512 | +0.65 | -7.46 | +0.91 | -0.10 | +0.26 | -0.66 | +7.71 | 0 | 0.0% | 0.0999 | 0.1181 | 0.0% | 0.0% | 95,494.21 |
| 2025-12-19 | 605.00 | 601.64 | 202512 | +1.34 | -7.46 | +0.81 | -0.10 | +0.04 | -0.91 | +8.95 | 0 | 0.0% | 0.0901 | 0.1183 | 0.0% | 0.0% | 95,494.21 |
| 2025-12-22 | 606.16 | 605.86 | 202512 | +1.95 | -7.46 | +0.83 | -0.09 | -0.08 | -0.78 | +9.54 | 0 | 0.0% | 0.0784 | 0.1183 | 0.0% | 0.0% | 95,494.21 |
| 2025-12-23 | 607.70 | 606.12 | 202512 | +3.63 | -7.46 | +0.86 | -0.08 | -0.09 | -0.62 | +11.02 | 0 | 0.0% | 0.0785 | 0.1183 | 0.0% | 0.0% | 95,494.21 |
| 2025-12-24 | 608.01 | 607.50 | 202512 | +2.59 | -7.46 | +1.14 | -0.05 | -0.18 | -0.80 | +9.94 | 0 | 0.0% | 0.0664 | 0.1174 | 0.0% | 0.0% | 95,494.21 |
| 2025-12-29 | 608.36 | 609.08 | 202512 | +2.47 | -7.46 | +1.10 | -0.04 | -0.15 | -0.67 | +9.69 | 0 | 0.0% | 0.0662 | 0.1173 | 0.0% | 0.0% | 95,494.21 |
| 2025-12-30 | 609.64 | 608.07 | 202512 | +2.19 | -7.46 | +1.03 | -0.00 | +0.01 | -0.99 | +9.61 | 0 | 0.0% | 0.0653 | 0.1171 | 0.0% | 0.0% | 95,494.21 |
| 2025-12-31 | 608.19 | 608.54 | 202512 | +2.08 | -7.46 | +1.17 | -0.00 | +0.01 | -1.32 | +9.68 | 0 | 0.0% | 0.0641 | 0.1171 | 0.0% | 0.0% | 95,494.21 |
| 2026-01-02 | 606.75 | 608.83 | 202601 | +1.70 | -7.54 | +1.20 | +0.14 | -0.27 | -1.02 | +9.19 | 0 | 0.0% | 0.0648 | 0.1171 | 0.0% | 0.0% | 95,494.21 |
| 2026-01-05 | 614.32 | 611.54 | 202601 | +2.41 | -7.54 | +1.08 | -0.40 | +1.68 | -0.78 | +8.37 | 0 | 0.0% | 0.0780 | 0.1185 | 0.0% | 0.0% | 95,494.21 |
| 2026-01-06 | 616.42 | 614.03 | 202601 | +2.40 | -7.54 | +1.07 | -0.48 | +2.12 | -0.86 | +8.09 | 0 | 0.0% | 0.0783 | 0.1186 | 0.0% | 0.0% | 95,494.21 |
| 2026-01-07 | 618.31 | 618.34 | 202601 | +7.52 | -7.54 | +0.82 | +0.01 | +0.05 | -0.59 | +14.77 | 0 | 0.0% | 0.0780 | 0.1109 | 0.0% | 0.0% | 95,494.21 |
| 2026-01-08 | 617.37 | 615.73 | 202601 | +4.59 | -7.54 | +1.41 | -0.12 | +0.48 | -0.46 | +10.82 | 0 | 0.0% | 0.0779 | 0.1099 | 0.0% | 0.0% | 95,494.21 |
| 2026-01-09 | 622.32 | 618.25 | 202601 | +9.12 | -7.54 | +0.94 | -0.16 | +0.64 | -0.39 | +15.63 | 0 | 0.0% | 0.0821 | 0.1103 | 0.0% | 0.0% | 95,494.21 |
| 2026-01-12 | 622.16 | 618.61 | 202601 | +6.13 | -7.54 | +1.10 | -0.27 | +1.12 | -0.43 | +12.15 | 0 | 0.0% | 0.0813 | 0.1098 | 0.0% | 0.0% | 95,494.21 |
| 2026-01-13 | 623.00 | 622.82 | 202601 | +6.03 | -7.54 | +0.79 | -0.25 | +0.95 | -0.75 | +12.84 | 0 | 0.0% | 0.0794 | 0.1097 | 0.0% | 0.0% | 95,494.21 |
| 2026-01-14 | 619.55 | 622.74 | 202601 | +8.03 | -7.54 | +0.97 | +0.25 | -0.38 | -0.36 | +15.09 | 0 | 0.0% | 0.0785 | 0.1080 | 0.0% | 0.0% | 95,494.21 |
| 2026-01-15 | 626.62 | 622.85 | 202601 | +6.55 | -7.54 | +1.26 | -0.44 | +2.18 | -0.25 | +11.35 | 0 | 0.0% | 0.0859 | 0.1050 | 0.0% | 0.0% | 95,494.21 |
| 2026-01-16 | 625.24 | 626.51 | 202601 | +4.24 | -7.54 | +1.38 | -0.45 | +2.21 | -0.20 | +8.84 | 0 | 0.0% | 0.0811 | 0.1049 | 0.0% | 0.0% | 95,494.21 |
| 2026-01-19 | 616.35 | 617.93 | 202601 | +2.78 | -7.54 | +1.44 | +0.12 | -0.13 | -0.05 | +8.94 | 0 | 0.0% | 0.0978 | 0.1086 | 0.0% | 0.0% | 95,494.21 |
| 2026-01-20 | 611.35 | 611.66 | 202601 | +3.99 | -7.54 | +0.85 | +0.27 | -0.36 | +0.28 | +10.49 | 0 | 0.0% | 0.0973 | 0.1097 | 0.0% | 0.0% | 95,494.21 |
| 2026-01-21 | 611.38 | 608.50 | 202601 | +6.03 | -7.54 | +0.40 | +0.07 | +0.01 | +0.48 | +12.62 | 0 | 0.0% | 0.0963 | 0.1087 | 0.0% | 0.0% | 95,494.21 |
| 2026-01-22 | 615.62 | 616.24 | 202601 | +6.25 | -7.54 | +0.37 | -0.30 | +1.28 | +0.36 | +12.08 | 0 | 0.0% | 0.0989 | 0.1089 | 0.0% | 0.0% | 95,494.21 |
| 2026-01-23 | 614.56 | 615.81 | 202601 | +7.30 | -7.54 | +0.32 | -0.30 | +1.28 | +0.10 | +13.46 | 0 | 0.0% | 0.0990 | 0.1089 | 0.0% | 0.0% | 95,494.21 |
| 2026-01-26 | 612.36 | 611.41 | 202601 | +9.11 | -7.54 | +0.51 | -0.23 | +0.99 | +0.17 | +15.21 | 0 | 0.0% | 0.1001 | 0.1091 | 0.0% | 0.0% | 95,494.21 |
| 2026-01-27 | 611.03 | 614.91 | 202601 | +11.64 | -7.54 | -0.04 | -0.20 | +0.89 | +1.03 | +17.52 | 0 | 0.0% | 0.1005 | 0.1092 | 0.0% | 0.0% | 95,494.21 |
| 2026-01-28 | 612.51 | 612.44 | 202601 | +11.17 | -7.54 | +0.23 | -0.23 | +1.00 | +1.20 | +16.51 | 0 | 0.0% | 0.1006 | 0.1092 | 0.0% | 0.0% | 95,494.21 |
| 2026-01-29 | 606.86 | 611.82 | 202601 | +13.35 | -7.54 | +0.28 | -0.01 | +0.24 | +1.27 | +19.12 | 0 | 0.0% | 0.1058 | 0.1108 | 0.0% | 0.0% | 95,494.21 |
| 2026-01-30 | 611.11 | 606.70 | 202601 | +11.55 | -7.54 | +0.38 | -0.11 | +0.54 | +1.36 | +16.92 | 0 | 0.0% | 0.1083 | 0.1115 | 0.0% | 0.0% | 95,494.21 |
| 2026-02-02 | 617.80 | 606.62 | 202602 | +9.46 | -7.57 | +0.48 | -0.19 | +1.92 | +1.41 | +13.41 | 0 | 0.0% | 0.1062 | 0.1136 | 0.0% | 0.0% | 95,494.21 |
| 2026-02-03 | 615.15 | 620.40 | 202602 | +6.70 | -7.57 | +0.73 | +0.04 | +0.01 | +1.41 | +12.08 | 0 | 0.0% | 0.1067 | 0.1100 | 0.0% | 0.0% | 95,494.21 |
| 2026-02-04 | 613.58 | 614.54 | 202602 | +3.98 | -7.57 | +0.82 | +0.29 | -0.09 | +1.43 | +9.09 | 0 | 0.0% | 0.1064 | 0.1066 | 0.0% | 0.0% | 95,494.21 |
| 2026-02-05 | 608.06 | 612.81 | 202602 | +10.75 | -7.57 | +0.75 | +0.14 | -0.20 | +1.47 | +16.17 | 0 | 0.0% | 0.1107 | 0.1007 | 0.0% | 0.0% | 95,494.21 |
| 2026-02-06 | 613.74 | 604.85 | 202602 | +9.48 | -7.57 | +0.68 | -0.03 | +0.41 | +1.40 | +14.58 | 0 | 0.0% | 0.1122 | 0.1022 | 0.0% | 0.0% | 95,494.21 |
| 2026-02-09 | 617.00 | 615.40 | 202602 | +10.06 | -7.57 | +0.74 | -0.16 | +1.58 | +1.34 | +14.13 | 0 | 0.0% | 0.1142 | 0.1021 | 0.0% | 0.0% | 95,494.21 |
| 2026-02-10 | 618.06 | 616.34 | 202602 | +6.41 | -7.57 | +0.95 | -0.02 | +0.34 | +1.25 | +11.46 | 0 | 0.0% | 0.1143 | 0.0985 | 0.0% | 0.0% | 95,494.21 |
| 2026-02-11 | 618.22 | 617.40 | 202602 | +5.89 | -7.57 | +1.10 | +0.02 | +0.12 | +1.24 | +10.97 | 0 | 0.0% | 0.1126 | 0.0983 | 0.0% | 0.0% | 95,494.21 |
| 2026-02-12 | 612.37 | 620.41 | 202602 | +6.51 | -7.57 | +1.27 | +0.21 | -0.19 | +1.15 | +11.64 | 0 | 0.0% | 0.1088 | 0.1000 | 0.0% | 0.0% | 95,494.21 |
| 2026-02-13 | 611.81 | 609.62 | 202602 | +3.47 | -7.57 | +1.14 | +0.49 | +0.63 | +1.31 | +7.47 | 0 | 0.0% | 0.1087 | 0.0960 | 0.0% | 0.0% | 95,494.21 |
| 2026-02-16 | 610.52 | 611.36 | 202602 | +3.52 | -7.57 | +1.19 | +0.50 | +0.70 | +1.21 | +7.50 | 0 | 0.0% | 0.0970 | 0.0961 | 0.0% | 0.0% | 95,494.21 |
| 2026-02-17 | 611.92 | 610.68 | 202602 | +4.02 | -7.57 | +1.13 | +0.34 | +0.08 | +1.16 | +8.87 | 0 | 0.0% | 0.0930 | 0.0952 | 0.0% | 0.0% | 95,494.21 |
| 2026-02-18 | 618.70 | 614.33 | 202602 | +5.74 | -7.57 | +0.78 | +0.36 | +0.18 | +1.13 | +10.85 | 0 | 0.0% | 0.1009 | 0.0944 | 0.0% | 0.0% | 95,494.21 |
| 2026-02-19 | 617.93 | 618.37 | 202602 | +3.95 | -7.57 | +1.27 | +0.18 | -0.21 | +1.05 | +9.22 | 0 | 0.0% | 0.0982 | 0.0908 | 0.0% | 0.0% | 95,494.21 |
| 2026-02-20 | 619.57 | 619.28 | 202602 | +4.05 | -7.57 | +1.18 | +0.13 | -0.21 | +1.03 | +9.50 | 0 | 0.0% | 0.0983 | 0.0909 | 0.0% | 0.0% | 95,494.21 |
| 2026-02-23 | 614.99 | 616.44 | 202602 | +5.86 | -7.57 | +1.08 | +0.08 | -0.13 | +1.04 | +11.37 | 0 | 0.0% | 0.1013 | 0.0892 | 0.0% | 0.0% | 95,494.21 |
| 2026-02-24 | 617.69 | 615.27 | 202602 | +4.58 | -7.57 | +1.06 | +0.04 | -0.02 | +0.88 | +10.19 | 0 | 0.0% | 0.1019 | 0.0895 | 0.0% | 0.0% | 95,494.21 |
| 2026-02-25 | 622.04 | 619.51 | 202602 | +4.36 | -7.57 | +0.98 | -0.08 | +0.72 | +0.79 | +9.52 | 0 | 0.0% | 0.1043 | 0.0903 | 0.0% | 0.0% | 95,494.21 |
| 2026-02-26 | 620.98 | 622.51 | 202602 | +3.85 | -7.57 | +1.05 | -0.01 | +0.17 | +0.67 | +9.53 | 0 | 0.0% | 0.0979 | 0.0899 | 0.0% | 0.0% | 95,494.21 |
| 2026-02-27 | 618.43 | 620.62 | 202602 | +3.97 | -7.57 | +1.00 | +0.05 | -0.08 | +0.54 | +10.03 | 0 | 0.0% | 0.0970 | 0.0904 | 0.0% | 0.0% | 95,494.21 |
| 2026-03-02 | 620.10 | 613.00 | 202603 | +3.83 | -7.59 | +0.55 | -0.01 | -0.02 | +0.91 | +10.00 | 0 | 0.0% | 0.0896 | 0.0905 | 0.0% | 0.0% | 95,494.21 |
| 2026-03-03 | 613.15 | 616.00 | 202603 | +5.82 | -7.59 | +0.16 | -0.04 | -0.07 | +0.99 | +12.37 | 0 | 0.0% | 0.0973 | 0.0935 | 0.0% | 0.0% | 95,494.21 |
| 2026-03-04 | 620.03 | 614.20 | 202603 | +4.84 | -7.59 | +0.48 | +0.01 | +0.21 | +1.05 | +10.68 | 0 | 0.0% | 0.1047 | 0.0959 | 0.0% | 0.0% | 95,494.21 |
| 2026-03-05 | 616.96 | 619.70 | 202603 | +4.80 | -7.59 | +0.10 | -0.02 | -0.07 | +0.95 | +11.43 | 0 | 0.0% | 0.1007 | 0.0964 | 0.0% | 0.0% | 95,494.21 |
| 2026-03-06 | 610.03 | 617.43 | 202603 | +7.17 | -7.59 | -0.21 | -0.04 | +0.02 | +0.86 | +14.13 | 0 | 0.0% | 0.1039 | 0.0993 | 0.0% | 0.0% | 95,494.21 |
| 2026-03-09 | 607.34 | 601.27 | 202603 | +6.76 | -7.59 | -0.41 | -0.03 | +0.37 | +0.85 | +13.57 | 0 | 0.0% | 0.1027 | 0.0996 | 0.0% | 0.0% | 95,494.21 |
| 2026-03-10 | 615.79 | 614.00 | 202603 | +3.00 | -7.59 | +0.10 | -0.04 | -0.07 | +0.95 | +9.65 | 0 | 0.0% | 0.1149 | 0.1032 | 0.0% | 0.0% | 95,494.21 |
| 2026-03-11 | 613.53 | 613.14 | 202603 | +1.83 | -7.59 | +0.10 | -0.03 | +0.41 | +0.72 | +8.22 | 0 | 0.0% | 0.1155 | 0.1027 | 0.0% | 0.0% | 95,494.21 |
| 2026-03-12 | 610.62 | 612.81 | 202603 | +2.26 | -7.59 | +0.35 | -0.02 | +0.70 | +0.53 | +8.29 | 0 | 0.0% | 0.1117 | 0.1031 | 0.0% | 0.0% | 95,494.21 |
| 2026-03-13 | 609.54 | 607.97 | 202603 | +1.56 | -7.59 | +0.77 | +0.04 | +1.69 | +0.54 | +6.10 | 0 | 0.0% | 0.1118 | 0.1022 | 0.0% | 0.0% | 95,494.21 |
| 2026-03-16 | 611.16 | 611.07 | 202603 | +2.58 | -7.59 | +1.10 | +0.06 | +2.02 | +0.50 | +6.50 | 0 | 0.0% | 0.1120 | 0.1018 | 0.0% | 0.0% | 95,494.21 |
| 2026-03-17 | 612.33 | 609.61 | 202603 | +1.82 | -7.59 | +0.99 | -0.02 | +0.64 | +0.15 | +7.66 | 0 | 0.0% | 0.1119 | 0.0995 | 0.0% | 0.0% | 95,494.21 |
| 2026-03-18 | 608.62 | 615.43 | 202603 | +1.65 | -7.59 | +0.79 | -0.02 | +0.83 | +0.06 | +7.58 | 0 | 0.0% | 0.1060 | 0.0999 | 0.0% | 0.0% | 95,494.21 |
| 2026-03-19 | 598.40 | 604.59 | 202603 | +4.69 | -7.59 | +0.73 | +0.10 | +2.73 | +0.23 | +8.49 | 0 | 0.0% | 0.1205 | 0.1058 | 0.0% | 0.0% | 95,494.21 |
| 2026-03-20 | 592.57 | 600.28 | 202603 | +7.49 | -7.59 | +1.33 | +0.20 | +3.84 | +0.29 | +9.43 | 0 | 0.0% | 0.1227 | 0.1074 | 0.0% | 0.0% | 95,494.21 |
| 2026-03-23 | 594.90 | 584.46 | 202603 | +4.67 | -7.59 | +0.81 | +0.13 | +2.95 | +0.31 | +8.07 | 0 | 0.0% | 0.1229 | 0.1078 | 0.0% | 0.0% | 95,494.21 |
| 2026-03-24 | 595.05 | 595.28 | 202603 | +3.72 | -7.59 | +1.02 | +0.10 | +2.70 | +0.27 | +7.22 | 0 | 0.0% | 0.1211 | 0.1078 | 0.0% | 0.0% | 95,494.21 |
| 2026-03-25 | 599.96 | 599.06 | 202603 | +1.14 | -7.59 | +0.70 | +0.00 | +1.22 | +0.01 | +6.80 | 0 | 0.0% | 0.1224 | 0.1091 | 0.0% | 0.0% | 95,494.21 |
| 2026-03-26 | 593.53 | 597.16 | 202603 | +1.30 | -7.59 | +0.97 | +0.13 | +2.94 | -0.53 | +5.37 | 0 | 0.0% | 0.1264 | 0.1111 | 0.0% | 0.0% | 95,494.21 |
| 2026-03-27 | 585.37 | 592.81 | 202603 | +2.87 | -7.59 | +2.24 | +0.42 | +5.76 | -0.63 | +2.67 | 0 | 0.0% | 0.1329 | 0.1144 | 0.0% | 0.0% | 95,494.21 |
| 2026-03-30 | 589.28 | 584.05 | 202603 | +6.54 | -7.59 | +3.23 | +0.06 | +2.16 | -0.50 | +9.18 | 0 | 0.0% | 0.1357 | 0.1122 | 0.0% | 0.0% | 95,494.21 |
| 2026-03-31 | 589.23 | 587.17 | 202603 | +7.41 | -7.59 | +4.08 | +0.02 | +1.52 | -0.76 | +10.14 | 0 | 0.0% | 0.1320 | 0.1119 | 0.0% | 0.0% | 95,494.21 |
| 2026-04-01 | 600.57 | 600.41 | 202604 | +0.82 | -7.39 | +2.05 | -0.37 | +0.16 | -0.50 | +6.87 | 0 | 0.0% | 0.1448 | 0.1188 | 0.0% | 0.0% | 95,494.21 |
| 2026-04-02 | 600.71 | 593.81 | 202604 | -0.25 | -7.39 | +1.61 | -0.39 | +0.17 | -0.63 | +6.38 | 0 | 0.0% | 0.1444 | 0.1188 | 0.0% | 0.0% | 95,494.21 |
| 2026-04-07 | 597.32 | 602.12 | 202604 | +4.46 | -7.39 | +3.30 | -0.27 | +0.05 | -0.68 | +9.46 | 0 | 0.0% | 0.1405 | 0.1180 | 0.0% | 0.0% | 95,494.21 |
| 2026-04-08 | 612.60 | 614.19 | 202604 | +0.09 | -7.39 | +0.99 | +0.63 | +1.20 | -0.60 | +5.28 | 0 | 0.0% | 0.1680 | 0.1294 | 0.0% | 0.0% | 95,494.21 |
| 2026-04-09 | 613.30 | 613.27 | 202604 | -0.62 | -7.39 | +0.97 | +0.72 | +1.54 | -0.95 | +4.50 | 0 | 0.0% | 0.1604 | 0.1294 | 0.0% | 0.0% | 95,494.21 |
| 2026-04-10 | 615.00 | 615.05 | 202604 | -0.45 | -7.39 | +0.48 | +0.65 | +1.26 | -1.36 | +5.92 | 0 | 0.0% | 0.1602 | 0.1291 | 0.0% | 0.0% | 95,494.21 |
| 2026-04-13 | 614.72 | 611.33 | 202604 | -1.44 | -7.39 | +0.93 | +1.00 | +2.76 | -1.56 | +2.82 | 0 | 0.0% | 0.1592 | 0.1268 | 0.0% | 0.0% | 95,494.21 |
| 2026-04-14 | 621.58 | 617.12 | 202604 | -1.91 | -7.39 | +0.82 | +1.23 | +4.28 | -1.67 | +0.83 | 0 | 0.0% | 0.1634 | 0.1289 | 0.0% | 0.0% | 95,494.21 |
| 2026-04-15 | 623.91 | 622.67 | 202604 | +3.30 | -7.39 | +1.52 | +0.92 | +2.56 | -1.71 | +7.41 | 0 | 0.0% | 0.1636 | 0.1257 | 0.0% | 0.0% | 95,494.21 |
| 2026-04-16 | 627.67 | 627.21 | 202604 | +9.97 | -7.39 | +2.49 | +0.82 | +2.16 | -1.45 | +13.35 | 0 | 0.0% | 0.1646 | 0.1250 | 0.0% | 0.0% | 95,494.21 |
| 2026-04-17 | 634.99 | 627.67 | 202604 | +14.49 | -7.39 | +2.96 | +1.08 | +3.79 | -1.21 | +15.27 | 0 | 0.0% | 0.1661 | 0.1271 | 0.0% | 0.0% | 95,494.21 |
| 2026-04-20 | 632.60 | 632.17 | 202604 | +6.67 | -7.39 | +2.86 | +1.13 | +4.14 | -1.39 | +7.32 | 0 | 0.0% | 0.1520 | 0.1267 | 0.0% | 0.0% | 95,494.21 |
| 2026-04-21 | 631.99 | 634.36 | 202604 | +5.02 | -7.39 | +2.85 | +1.05 | +3.53 | -1.70 | +6.67 | 0 | 0.0% | 0.1454 | 0.1266 | 0.0% | 0.0% | 95,494.21 |
| 2026-04-22 | 634.78 | 633.63 | 202604 | +6.81 | -7.39 | +2.95 | +1.06 | +3.49 | -2.14 | +8.85 | 0 | 0.0% | 0.1455 | 0.1266 | 0.0% | 0.0% | 95,494.21 |
| 2026-04-23 | 636.73 | 634.03 | 202604 | +10.51 | -7.39 | +3.73 | +1.02 | +3.43 | -1.14 | +10.87 | 0 | 0.0% | 0.1450 | 0.1266 | 0.0% | 0.0% | 95,494.21 |
| 2026-04-24 | 635.73 | 635.73 | 202604 | +6.83 | -7.39 | +3.76 | +1.00 | +3.35 | -1.14 | +7.24 | 0 | 0.0% | 0.1449 | 0.1266 | 0.0% | 0.0% | 95,494.21 |
| 2026-04-27 | 634.90 | 635.99 | 202604 | +9.37 | -7.39 | +3.78 | +0.70 | +1.63 | -1.16 | +11.81 | 0 | 0.0% | 0.1367 | 0.1250 | 0.0% | 0.0% | 95,494.21 |
| 2026-04-28 | 632.86 | 637.40 | 202604 | +4.19 | -7.39 | +3.92 | +0.77 | +1.94 | -1.21 | +6.17 | 0 | 0.0% | 0.1235 | 0.1246 | 0.0% | 0.0% | 95,494.21 |
| 2026-04-29 | 632.93 | 635.66 | 202604 | +1.17 | -7.39 | +3.75 | +1.01 | +3.44 | -0.97 | +1.35 | 0 | 0.0% | 0.1237 | 0.1227 | 0.0% | 0.0% | 95,494.21 |
| 2026-04-30 | 637.16 | 633.33 | 202604 | +1.91 | -7.39 | +3.86 | +1.05 | +3.66 | -1.15 | +1.87 | 0 | 0.0% | 0.1234 | 0.1230 | 0.0% | 0.0% | 95,494.21 |
| 2026-05-04 | 638.94 | 641.76 | 202605 | +1.59 | -7.27 | +4.01 | +1.33 | +2.20 | -1.01 | +2.32 | 0 | 0.0% | 0.1097 | 0.1229 | 0.0% | 0.0% | 95,494.21 |
| 2026-05-05 | 643.41 | 641.18 | 202605 | +5.96 | -7.27 | +3.69 | +1.21 | +1.75 | -0.88 | +7.46 | 0 | 0.0% | 0.1099 | 0.1218 | 0.0% | 0.0% | 95,494.21 |
| 2026-05-06 | 650.83 | 645.95 | 202605 | +1.80 | -7.27 | +3.53 | +1.74 | +4.33 | -0.51 | -0.02 | 0 | 0.0% | 0.1079 | 0.1226 | 0.0% | 0.0% | 95,494.21 |
| 2026-05-07 | 651.36 | 653.33 | 202605 | -2.90 | -7.27 | +3.67 | +1.86 | +4.96 | -0.62 | -5.51 | 0 | 0.0% | 0.0747 | 0.1222 | 0.0% | 0.0% | 95,494.21 |
| 2026-05-08 | 650.65 | 650.60 | 202605 | -4.44 | -7.27 | +3.79 | +1.86 | +4.79 | -1.04 | -6.57 | 0 | 0.0% | 0.0758 | 0.1223 | 0.0% | 0.0% | 95,494.21 |
| 2026-05-11 | 653.08 | 650.65 | 202605 | -5.82 | -7.27 | +3.53 | +1.93 | +5.12 | -1.13 | -8.00 | 0 | 0.0% | 0.0759 | 0.1224 | 0.0% | 0.0% | 95,494.21 |
| 2026-05-12 | 648.90 | 650.13 | 202605 | -2.98 | -7.27 | +3.40 | +1.44 | +2.55 | -1.45 | -1.65 | 0 | 0.0% | 0.0822 | 0.1214 | 0.0% | 0.0% | 95,494.21 |
| 2026-05-13 | 655.85 | 655.05 | 202605 | -3.11 | -7.27 | +3.03 | +1.66 | +3.61 | -1.28 | -2.86 | 0 | 0.0% | 0.0816 | 0.1230 | 0.0% | 0.0% | 95,494.21 |
| 2026-05-14 | 664.54 | 658.77 | 202605 | -3.28 | -7.27 | +1.96 | +1.91 | +4.87 | -1.67 | -3.08 | 0 | 0.0% | 0.0896 | 0.1252 | 0.0% | 0.0% | 95,494.21 |
| 2026-05-15 | 659.11 | 661.40 | 202605 | -4.56 | -7.27 | +2.97 | +1.68 | +3.60 | -1.74 | -3.80 | 0 | 0.0% | 0.0975 | 0.1267 | 0.0% | 0.0% | 95,494.21 |
| 2026-05-18 | 655.69 | 653.86 | 202605 | -3.54 | -7.27 | +3.60 | +1.79 | +4.13 | -1.77 | -4.02 | 0 | 0.0% | 0.0948 | 0.1258 | 0.0% | 0.0% | 95,494.21 |
| 2026-05-19 | 655.13 | 656.86 | 202605 | -3.83 | -7.27 | +2.56 | +1.65 | +3.54 | -0.86 | -3.45 | 0 | 0.0% | 0.0931 | 0.1257 | 0.0% | 0.0% | 95,494.21 |
| 2026-05-20 | 661.61 | 656.17 | 202605 | -6.43 | -7.27 | +2.60 | +1.92 | +5.08 | -0.90 | -7.86 | 0 | 0.0% | 0.0968 | 0.1270 | 0.0% | 0.0% | 95,494.21 |
| 2026-05-21 | 661.84 | 660.94 | 202605 | -4.72 | -7.27 | +2.35 | +1.62 | +3.68 | -0.67 | -4.43 | 0 | 0.0% | 0.0967 | 0.1258 | 0.0% | 0.0% | 95,494.21 |
| 2026-05-22 | 668.85 | 666.43 | 202605 | -8.54 | -7.27 | +1.85 | +1.96 | +5.52 | -0.75 | -9.85 | 0 | 0.0% | 0.1012 | 0.1270 | 0.0% | 0.0% | 95,494.21 |
| 2026-05-25 | 672.50 | 671.92 | 202605 | -9.35 | -7.27 | +2.38 | +2.18 | +6.94 | -0.88 | -12.70 | 0 | 0.0% | 0.1006 | 0.1268 | 0.0% | 0.0% | 95,494.21 |
| 2026-05-26 | 670.41 | 671.03 | 202605 | -6.49 | -7.27 | +2.45 | +2.02 | +5.88 | -1.05 | -8.52 | 0 | 0.0% | 0.1017 | 0.1270 | 0.0% | 0.0% | 95,494.21 |
| 2026-05-27 | 669.33 | 669.89 | 202605 | -4.65 | -7.27 | +2.22 | +1.81 | +4.64 | -1.09 | -4.96 | 0 | 0.0% | 0.1007 | 0.1266 | 0.0% | 0.0% | 95,494.21 |
| 2026-05-28 | 670.92 | 669.48 | 202605 | -4.14 | -7.27 | +2.57 | +1.81 | +5.01 | -0.42 | -5.82 | 0 | 0.0% | 0.1002 | 0.1266 | 0.0% | 0.0% | 95,494.21 |
| 2026-05-29 | 672.00 | 672.96 | 202605 | -1.66 | -7.27 | +1.82 | +1.42 | +3.17 | -0.23 | -0.58 | 0 | 0.0% | 0.0993 | 0.1239 | 0.0% | 0.0% | 95,494.21 |
| 2026-06-01 | 673.97 | 674.37 | 202606 | +13.08 | -5.84 | -0.51 | +9.27 | +0.40 | -0.20 | +9.96 | 0 | 0.0% | 0.0993 | 0.1223 | 0.0% | 0.0% | 95,494.21 |
| 2026-06-02 | 676.87 | 674.08 | 202606 | +9.17 | -5.84 | -1.58 | +8.72 | +0.21 | -0.40 | +8.06 | 0 | 0.0% | 0.0982 | 0.1217 | 0.0% | 0.0% | 95,494.21 |
| 2026-06-03 | 674.97 | 678.30 | 202606 | +5.95 | -5.84 | -1.65 | +5.71 | -0.45 | -0.16 | +8.35 | 0 | 0.0% | 0.0939 | 0.1191 | 0.0% | 0.0% | 95,494.21 |
| 2026-06-04 | 674.77 | 672.22 | 202606 | +6.92 | -5.84 | -1.41 | +3.74 | -0.58 | +1.63 | +9.38 | 0 | 0.0% | 0.0942 | 0.1185 | 0.0% | 0.0% | 95,494.21 |
| 2026-06-05 | 671.53 | 671.96 | 202606 | +19.85 | -5.84 | +1.43 | +4.58 | -0.50 | +2.03 | +18.15 | 0 | 0.0% | 0.0966 | 0.1165 | 0.0% | 0.0% | 95,494.21 |
| 2026-06-08 | 667.55 | 664.53 | 202606 | +21.69 | -5.84 | +1.27 | +2.29 | -0.58 | +2.90 | +21.67 | 1 | 100.0% | 0.0998 | 0.1170 | 100.0% | 0.0% | 95,494.21 |
| 2026-06-09 | 657.86 | 667.56 | 202606 | +24.36 | -5.84 | +2.23 | -1.87 | +0.09 | +3.48 | +26.28 | 1 | 99.2% | 0.1115 | 0.1209 | 99.4% | 99.4% | 94,022.39 |
| 2026-06-10 | 657.40 | 660.65 | 202606 | +23.85 | -5.84 | +0.89 | -2.95 | +0.38 | +3.73 | +27.64 | 1 | 99.3% | 0.1052 | 0.1208 | 99.4% | 99.4% | 93,957.82 |
| 2026-06-11 | 658.04 | 657.34 | 202606 | +23.82 | -5.84 | +2.11 | -2.70 | +0.31 | +3.85 | +26.08 | 1 | 99.4% | 0.0933 | 0.1208 | 99.4% | 99.4% | 94,048.39 |
| 2026-06-12 | 668.46 | 662.87 | 202606 | +18.21 | -5.84 | +0.08 | +0.29 | -0.38 | +3.25 | +20.81 | 1 | 96.5% | 0.1050 | 0.1244 | 99.4% | 99.4% | 95,528.48 |
| 2026-06-15 | 676.59 | 674.84 | 202606 | +9.06 | -5.84 | -2.62 | +0.60 | -0.46 | +3.84 | +13.54 | 1 | 95.8% | 0.1099 | 0.1252 | 95.8% | 99.4% | 96,682.15 |
| 2026-06-16 | 675.88 | 677.26 | 202606 | -2.83 | -5.84 | -4.65 | -3.64 | +0.58 | +4.20 | +6.51 | 0 | 0.0% | 0.1100 | 0.1192 | 0.0% | 95.9% | 96,584.57 |
| 2026-06-17 | 676.27 | 675.74 | 202606 | -11.73 | -5.84 | -6.00 | -6.14 | +1.74 | +4.14 | +0.37 | 0 | 0.0% | 0.1056 | 0.1167 | 0.0% | 0.0% | 96,472.77 |
| 2026-06-18 | 678.69 | 677.85 | 202606 | -9.54 | -5.84 | -5.55 | -5.67 | +1.44 | +4.34 | +1.73 | 0 | 0.0% | 0.1059 | 0.1166 | 0.0% | 0.0% | 96,472.77 |
| 2026-06-19 | 679.20 | 679.30 | 202606 | -10.89 | -5.84 | -5.61 | -6.15 | +1.77 | +4.04 | +0.90 | 0 | 0.0% | 0.1000 | 0.1166 | 0.0% | 0.0% | 96,472.77 |
| 2026-06-22 | 680.56 | 680.02 | 202606 | -7.61 | -5.84 | -4.89 | -5.09 | +1.21 | +4.11 | +2.89 | 0 | 0.0% | 0.0986 | 0.1159 | 0.0% | 0.0% | 96,472.77 |
| 2026-06-23 | 674.70 | 672.02 | 202606 | -17.54 | -5.84 | -5.28 | -9.25 | +3.86 | +3.69 | -4.73 | 0 | 0.0% | 0.1033 | 0.1150 | 0.0% | 0.0% | 96,472.77 |
| 2026-06-24 | 679.25 | 675.66 | 202606 | -17.14 | -5.84 | -8.27 | -11.15 | +5.56 | +3.19 | -0.63 | 0 | 0.0% | 0.1054 | 0.1104 | 0.0% | 0.0% | 96,472.77 |
| 2026-06-25 | 675.40 | 678.75 | 202606 | -21.73 | -5.84 | -6.56 | -11.83 | +6.16 | +3.17 | -6.82 | 0 | 0.0% | 0.1076 | 0.1113 | 0.0% | 0.0% | 96,472.77 |
| 2026-06-26 | 673.57 | 672.03 | 202606 | -22.79 | -5.84 | -6.16 | -12.83 | +7.36 | +2.53 | -7.85 | 0 | 0.0% | 0.1080 | 0.1117 | 0.0% | 0.0% | 96,472.77 |
| 2026-06-29 | 674.36 | 672.97 | 202606 | -16.63 | -5.84 | -3.33 | -10.10 | +4.81 | +2.71 | -4.88 | 0 | 0.0% | 0.1076 | 0.1060 | 0.0% | 0.0% | 96,472.77 |
| 2026-06-30 | 681.23 | 679.11 | 202606 | -7.27 | -5.84 | -4.63 | -8.83 | +3.92 | +2.36 | +5.76 | 0 | 0.0% | 0.1125 | 0.1073 | 0.0% | 0.0% | 96,472.77 |
| 2026-07-01 | 685.25 | 680.52 | 202607 | +5.72 | -6.24 | -7.54 | -7.85 | +6.45 | +1.40 | +19.50 | 0 | 0.0% | 0.1136 | 0.1063 | 0.0% | 0.0% | 96,472.77 |
| 2026-07-02 | 681.98 | 681.05 | 202607 | -2.47 | -6.24 | -2.79 | -5.60 | +3.47 | +1.43 | +7.26 | 0 | 0.0% | 0.1152 | 0.0959 | 0.0% | 0.0% | 96,472.77 |
| 2026-07-03 | 684.52 | 683.91 | 202607 | -0.30 | -6.24 | -3.15 | -5.27 | +3.27 | +0.92 | +10.16 | 0 | 0.0% | 0.1140 | 0.0960 | 0.0% | 0.0% | 96,472.77 |
| 2026-07-06 | 687.74 | 685.64 | 202607 | +2.57 | -6.24 | -3.66 | -4.70 | +2.70 | +0.82 | +13.64 | 0 | 0.0% | 0.1116 | 0.0962 | 0.0% | 0.0% | 96,472.77 |
| 2026-07-07 | 682.53 | 686.03 | 202607 | -2.17 | -6.24 | -2.56 | -6.31 | +4.60 | +0.64 | +7.70 | 0 | 0.0% | 0.1004 | 0.0980 | 0.0% | 0.0% | 96,472.77 |
| 2026-07-08 | 677.54 | 681.64 | 202607 | -2.98 | -6.24 | +0.10 | -6.22 | +4.50 | +0.56 | +4.33 | 0 | 0.0% | 0.1053 | 0.0978 | 0.0% | 0.0% | 96,472.77 |
| 2026-07-09 | 684.24 | 682.16 | 202607 | -0.02 | -6.24 | -0.89 | -4.63 | +2.77 | +0.27 | +8.70 | 0 | 0.0% | 0.1093 | 0.0992 | 0.0% | 0.0% | 96,472.77 |
| 2026-07-10 | 686.72 | 684.47 | 202607 | +1.09 | -6.24 | -0.79 | -3.56 | +1.86 | -0.23 | +10.04 | 0 | 0.0% | 0.0968 | 0.0988 | 0.0% | 0.0% | 96,472.77 |
| 2026-07-13 | 687.62 | 686.10 | 202607 | +2.61 | -6.24 | +0.13 | -1.99 | +0.72 | -0.60 | +10.60 | 0 | 0.0% | 0.0882 | 0.0966 | 0.0% | 0.0% | 96,472.77 |
| 2026-07-14 | 685.94 | 684.97 | 202607 | +0.73 | -6.24 | -0.00 | -3.26 | +1.71 | -1.23 | +9.75 | 0 | 0.0% | 0.0887 | 0.0963 | 0.0% | 0.0% | 96,472.77 |
| 2026-07-15 | 687.48 | 688.00 | 202607 | +0.38 | -6.24 | -0.35 | -3.32 | +1.90 | -2.11 | +10.51 | 0 | 0.0% | 0.0889 | 0.0962 | 0.0% | 0.0% | 96,472.77 |
| 2026-07-16 | 687.15 | 685.91 | 202607 | -0.11 | -6.24 | +0.27 | -2.93 | +1.75 | -3.26 | +10.30 | 0 | 0.0% | 0.0883 | 0.0961 | 0.0% | 0.0% | 96,472.77 |
| 2026-07-17 | 679.63 | 678.51 | 202607 | -1.12 | -6.24 | +0.81 | -4.67 | +3.21 | -4.24 | +10.02 | 0 | 0.0% | 0.0975 | 0.0992 | 0.0% | 0.0% | 96,472.77 |
| 2026-07-20 | 681.47 | 678.94 | 202607 | -3.59 | -6.24 | -0.04 | -4.86 | +3.38 | -4.91 | +9.08 | 0 | 0.0% | 0.0977 | 0.0991 | 0.0% | 0.0% | 96,472.77 |
| 2026-07-21 | 684.28 | 682.11 | 202607 | -4.47 | -6.24 | -1.02 | -4.72 | +3.32 | -6.14 | +10.34 | 0 | 0.0% | 0.0930 | 0.0992 | 0.0% | 0.0% | 96,472.77 |
| 2026-07-22 | 685.96 | 682.47 | 202607 | -3.94 | -6.24 | -2.02 | -5.16 | +3.86 | -7.51 | +13.14 | 0 | 0.0% | 0.0905 | 0.0988 | 0.0% | 0.0% | 96,472.77 |
| 2026-07-23 | 677.10 | 681.99 | 202607 | -8.80 | -6.24 | -0.06 | -7.66 | +6.72 | -7.55 | +5.99 | 0 | 0.0% | 0.1004 | 0.1030 | 0.0% | 0.0% | 96,472.77 |
| 2026-07-24 | 681.65 | 678.04 | 202607 | -5.60 | -6.24 | -0.11 | -5.79 | +4.59 | -8.22 | +10.17 | 0 | 0.0% | 0.1024 | 0.1030 | 0.0% | 0.0% | 96,472.77 |
| 2026-07-27 | 678.83 | 684.32 | 202607 | -5.97 | -6.24 | +0.97 | -6.36 | +5.23 | -8.20 | +8.64 | 0 | 0.0% | 0.1037 | 0.1035 | 0.0% | 0.0% | 96,472.77 |
| 2026-07-28 | 681.09 | 679.18 | 202607 | -3.79 | -6.24 | +1.45 | -4.98 | +3.76 | -8.49 | +10.71 | 0 | 0.0% | 0.0978 | 0.1029 | 0.0% | 0.0% | 96,472.77 |
| 2026-07-29 | 676.78 | 682.16 | 202607 | +0.82 | -6.24 | +3.18 | -4.53 | +3.20 | -6.98 | +12.18 | 0 | 0.0% | 0.0977 | 0.1016 | 0.0% | 0.0% | 96,472.77 |
| 2026-07-30 | 672.88 | 672.38 | 202607 | +1.13 | -6.24 | +3.82 | -5.45 | +4.21 | -7.02 | +11.81 | 0 | 0.0% | 0.0983 | 0.1025 | 0.0% | 0.0% | 96,472.77 |
| 2026-07-31 | 675.91 | 678.75 | 202607 | -2.03 | -6.24 | +3.48 | -5.01 | +3.83 | -8.35 | +10.26 | 0 | 0.0% | 0.0988 | 0.1027 | 0.0% | 0.0% | 96,472.77 |
| 2026-08-03 | 686.23 | 682.22 | 202608 | -0.18 | -2.60 | +1.54 | -2.06 | +1.86 | -6.41 | +7.49 | 0 | 0.0% | 0.1123 | 0.1068 | 0.0% | 0.0% | 96,472.77 |
| 2026-08-04 | 695.21 | 690.00 | 202608 | +5.68 | -2.60 | -0.72 | -1.32 | +1.16 | -7.18 | +16.35 | 0 | 0.0% | 0.1178 | 0.1086 | 0.0% | 0.0% | 96,472.77 |
| 2026-08-05 | 697.77 | 699.89 | 202608 | +2.82 | -2.60 | -0.30 | +0.42 | -0.12 | -7.35 | +12.77 | 0 | 0.0% | 0.1140 | 0.1069 | 0.0% | 0.0% | 96,472.77 |
| 2026-08-06 | 697.07 | 697.66 | 202608 | +0.18 | -2.60 | +1.21 | +2.03 | -0.55 | -8.62 | +8.70 | 0 | 0.0% | 0.1098 | 0.1039 | 0.0% | 0.0% | 96,472.77 |
| 2026-08-07 | 699.77 | 697.95 | 202608 | +0.70 | -2.60 | -0.30 | +1.25 | -0.37 | -9.42 | +12.13 | 0 | 0.0% | 0.1099 | 0.1024 | 0.0% | 0.0% | 96,472.77 |
| 2026-08-10 | 700.40 | 700.62 | 202608 | +2.61 | -2.60 | -0.64 | +0.28 | +0.05 | -9.08 | +14.59 | 0 | 0.0% | 0.1099 | 0.1016 | 0.0% | 0.0% | 96,472.77 |
| 2026-08-11 | 700.18 | 700.56 | 202608 | +4.75 | -2.60 | +0.47 | -0.49 | +0.36 | -6.52 | +13.53 | 0 | 0.0% | 0.1093 | 0.1015 | 0.0% | 0.0% | 96,472.77 |
| 2026-08-12 | 700.83 | 700.32 | 202608 | +1.88 | -2.60 | +1.27 | +0.74 | -0.31 | -7.03 | +9.82 | 0 | 0.0% | 0.1092 | 0.0999 | 0.0% | 0.0% | 96,472.77 |
| 2026-08-13 | 703.89 | 702.81 | 202608 | +3.02 | -2.60 | +1.09 | +1.12 | -0.44 | -7.19 | +11.02 | 0 | 0.0% | 0.1097 | 0.1001 | 0.0% | 0.0% | 96,472.77 |
| 2026-08-14 | 700.98 | 704.51 | 202608 | +1.84 | -2.60 | +3.15 | +1.72 | -0.55 | -7.38 | +7.51 | 0 | 0.0% | 0.1020 | 0.0987 | 0.0% | 0.0% | 96,472.77 |
| 2026-08-17 | 700.14 | 701.89 | 202608 | +2.60 | -2.60 | +3.25 | +2.14 | -0.57 | -7.69 | +8.06 | 0 | 0.0% | 0.1024 | 0.0983 | 0.0% | 0.0% | 96,472.77 |
| 2026-08-18 | 693.39 | 696.14 | 202608 | +4.20 | -2.60 | +3.73 | +0.30 | -0.06 | -7.92 | +10.74 | 0 | 0.0% | 0.1089 | 0.1002 | 0.0% | 0.0% | 96,472.77 |
| 2026-08-19 | 690.81 | 691.64 | 202608 | +4.64 | -2.60 | +4.10 | -0.58 | +0.54 | -7.43 | +10.60 | 0 | 0.0% | 0.1098 | 0.1005 | 0.0% | 0.0% | 96,472.77 |
| 2026-08-20 | 686.31 | 689.30 | 202608 | +7.06 | -2.60 | +4.61 | -1.29 | +1.18 | -6.49 | +11.66 | 0 | 0.0% | 0.1014 | 0.1015 | 0.0% | 0.0% | 96,472.77 |
| 2026-08-21 | 688.01 | 684.63 | 202608 | +6.25 | -2.60 | +4.29 | -0.84 | +0.75 | -7.09 | +11.75 | 0 | 0.0% | 0.0992 | 0.1015 | 0.0% | 0.0% | 96,472.77 |
| 2026-08-24 | 686.16 | 686.22 | 202608 | +7.73 | -2.60 | +4.54 | -0.91 | +0.80 | -7.03 | +12.92 | 0 | 0.0% | 0.0984 | 0.1016 | 0.0% | 0.0% | 96,472.77 |
| 2026-08-25 | 687.92 | 689.07 | 202608 | +7.80 | -2.60 | +4.27 | -0.08 | +0.13 | -6.86 | +12.93 | 0 | 0.0% | 0.0982 | 0.1014 | 0.0% | 0.0% | 96,472.77 |
| 2026-08-26 | 688.75 | 688.68 | 202608 | +6.18 | -2.60 | +4.18 | -0.36 | +0.34 | -7.20 | +11.81 | 0 | 0.0% | 0.0948 | 0.1012 | 0.0% | 0.0% | 96,472.77 |
| 2026-08-27 | 691.31 | 690.95 | 202608 | +6.15 | -2.60 | +4.55 | -0.04 | +0.09 | -6.29 | +10.44 | 0 | 0.0% | 0.0919 | 0.1014 | 0.0% | 0.0% | 96,472.77 |
| 2026-08-28 | 697.27 | 693.63 | 202608 | +2.52 | -2.60 | +4.11 | +0.31 | -0.12 | -6.32 | +7.14 | 0 | 0.0% | 0.0949 | 0.1022 | 0.0% | 0.0% | 96,472.77 |
| 2026-08-31 | 689.52 | 693.79 | 202608 | +3.85 | -2.60 | +5.00 | -2.11 | +2.11 | -4.78 | +6.23 | 0 | 0.0% | 0.0907 | 0.1042 | 0.0% | 0.0% | 96,472.77 |
| 2026-09-01 | 688.41 | 691.77 | 202609 | +1.40 | -2.57 | +3.70 | -6.32 | +7.22 | -1.83 | +1.20 | 0 | 0.0% | 0.0773 | 0.0994 | 0.0% | 0.0% | 96,472.77 |
| 2026-09-02 | 689.74 | 687.80 | 202609 | +2.39 | -2.57 | +3.90 | -6.37 | +7.31 | -1.41 | +1.53 | 0 | 0.0% | 0.0763 | 0.0994 | 0.0% | 0.0% | 96,472.77 |
| 2026-09-03 | 695.20 | 689.37 | 202609 | +5.87 | -2.57 | +3.48 | -5.14 | +5.36 | -1.34 | +6.08 | 0 | 0.0% | 0.0820 | 0.1004 | 0.0% | 0.0% | 96,472.77 |
| 2026-09-04 | 693.06 | 694.61 | 202609 | +5.27 | -2.57 | +5.10 | -3.16 | +2.76 | -1.46 | +4.60 | 0 | 0.0% | 0.0812 | 0.0959 | 0.0% | 0.0% | 96,472.77 |
| 2026-09-07 | 692.52 | 694.27 | 202609 | +8.86 | -2.57 | +5.91 | -1.48 | +0.86 | -0.63 | +6.77 | 0 | 0.0% | 0.0810 | 0.0929 | 0.0% | 0.0% | 96,472.77 |
| 2026-09-08 | 691.68 | 692.03 | 202609 | +8.25 | -2.57 | +5.50 | -2.08 | +1.37 | -0.40 | +6.43 | 0 | 0.0% | 0.0811 | 0.0929 | 0.0% | 0.0% | 96,472.77 |
| 2026-09-09 | 685.59 | 689.70 | 202609 | +10.08 | -2.57 | +5.62 | -3.69 | +3.11 | -0.41 | +8.03 | 0 | 0.0% | 0.0859 | 0.0948 | 0.0% | 0.0% | 96,472.77 |
| 2026-09-10 | 682.51 | 686.71 | 202609 | +12.10 | -2.57 | +5.68 | -3.92 | +3.38 | -0.47 | +10.00 | 0 | 0.0% | 0.0841 | 0.0950 | 0.0% | 0.0% | 96,472.77 |
| 2026-09-11 | 688.92 | 685.07 | 202609 | +9.31 | -2.57 | +5.58 | -2.14 | +1.43 | -0.71 | +7.71 | 0 | 0.0% | 0.0919 | 0.0969 | 0.0% | 0.0% | 96,472.77 |
| 2026-09-14 | 687.71 | 686.07 | 202609 | +10.77 | -2.57 | +5.95 | -2.18 | +1.46 | -0.39 | +8.49 | 0 | 0.0% | 0.0919 | 0.0969 | 0.0% | 0.0% | 96,472.77 |
| 2026-09-15 | 684.26 | 685.34 | 202609 | +7.95 | -2.57 | +5.73 | -4.72 | +4.42 | -0.00 | +5.09 | 0 | 0.0% | 0.0874 | 0.0958 | 0.0% | 0.0% | 96,472.77 |
| 2026-09-16 | 687.56 | 686.34 | 202609 | +9.05 | -2.57 | +5.64 | -2.73 | +2.01 | -0.02 | +6.72 | 0 | 0.0% | 0.0887 | 0.0953 | 0.0% | 0.0% | 96,472.77 |
| 2026-09-17 | 692.87 | 691.17 | 202609 | +6.02 | -2.57 | +5.40 | -2.47 | +1.75 | -0.09 | +4.00 | 0 | 0.0% | 0.0896 | 0.0957 | 0.0% | 0.0% | 96,472.77 |
| 2026-09-18 | 691.06 | 694.51 | 202609 | +5.28 | -2.57 | +5.47 | -3.53 | +2.98 | -0.38 | +3.30 | 0 | 0.0% | 0.0900 | 0.0957 | 0.0% | 0.0% | 96,472.77 |
| 2026-09-21 | 699.57 | 696.00 | 202609 | +7.51 | -2.57 | +4.99 | -1.33 | +0.70 | -0.34 | +6.07 | 0 | 0.0% | 0.0987 | 0.0987 | 0.0% | 0.0% | 96,472.77 |
| 2026-09-22 | 703.73 | 702.72 | 202609 | +6.86 | -2.57 | +4.89 | +1.36 | -1.06 | -0.28 | +4.53 | 0 | 0.0% | 0.1002 | 0.0973 | 0.0% | 0.0% | 96,472.77 |
| 2026-09-23 | 702.27 | 705.82 | 202609 | +6.68 | -2.57 | +5.35 | +1.87 | -1.28 | -0.23 | +3.55 | 0 | 0.0% | 0.1008 | 0.0968 | 0.0% | 0.0% | 96,472.77 |
| 2026-09-24 | 698.18 | 697.68 | 202609 | +6.32 | -2.57 | +5.17 | -0.18 | -0.18 | -0.31 | +4.40 | 0 | 0.0% | 0.1030 | 0.0971 | 0.0% | 0.0% | 96,472.77 |
| 2026-09-25 | 701.13 | 702.24 | 202609 | +6.34 | -2.57 | +5.15 | +1.17 | -0.94 | -0.55 | +4.08 | 0 | 0.0% | 0.0996 | 0.0972 | 0.0% | 0.0% | 96,472.77 |
| 2026-09-28 | 699.27 | 701.73 | 202609 | +8.70 | -2.57 | +5.79 | +1.33 | -1.06 | -0.15 | +5.36 | 0 | 0.0% | 0.0908 | 0.0970 | 0.0% | 0.0% | 96,472.77 |
| 2026-09-29 | 699.54 | 700.15 | 202609 | +7.22 | -2.57 | +5.76 | -0.11 | -0.25 | +0.02 | +4.38 | 0 | 0.0% | 0.0904 | 0.0955 | 0.0% | 0.0% | 96,472.77 |
| 2026-09-30 | 702.09 | 701.56 | 202609 | +6.92 | -2.57 | +5.48 | -0.97 | +0.37 | +0.17 | +4.44 | 0 | 0.0% | 0.0909 | 0.0944 | 0.0% | 0.0% | 96,472.77 |
| 2026-10-01 | 700.42 | 701.45 | 202610 | +4.05 | -1.91 | +6.26 | +1.24 | -0.67 | +0.07 | -0.95 | 0 | 0.0% | 0.0877 | 0.0926 | 0.0% | 0.0% | 96,472.77 |
| 2026-10-02 | 706.96 | 704.17 | 202610 | +4.25 | -1.91 | +6.58 | +3.32 | -1.46 | +0.14 | -2.41 | 0 | 0.0% | 0.0921 | 0.0941 | 0.0% | 0.0% | 96,472.77 |
| 2026-10-05 | 713.40 | 711.56 | 202610 | +4.53 | -1.91 | +6.17 | +4.97 | -1.45 | +0.20 | -3.45 | 0 | 0.0% | 0.0961 | 0.0958 | 0.0% | 0.0% | 96,472.77 |
| 2026-10-06 | 717.11 | 716.17 | 202610 | +5.07 | -1.91 | +5.96 | +5.24 | -1.41 | +0.18 | -2.99 | 0 | 0.0% | 0.0964 | 0.0960 | 0.0% | 0.0% | 96,472.77 |
| 2026-10-07 | 714.98 | 716.72 | 202610 | +3.56 | -1.91 | +5.81 | +4.84 | -1.47 | +0.20 | -3.91 | 0 | 0.0% | 0.0899 | 0.0962 | 0.0% | 0.0% | 96,472.77 |
| 2026-10-08 | 712.18 | 712.20 | 202610 | +3.36 | -1.91 | +5.68 | +3.78 | -1.52 | +0.23 | -2.91 | 0 | 0.0% | 0.0893 | 0.0967 | 0.0% | 0.0% | 96,472.77 |
| 2026-10-09 | 715.80 | 713.45 | 202610 | +3.83 | -1.91 | +5.18 | +2.38 | -1.28 | +0.25 | -0.80 | 0 | 0.0% | 0.0860 | 0.0940 | 0.0% | 0.0% | 96,472.77 |
