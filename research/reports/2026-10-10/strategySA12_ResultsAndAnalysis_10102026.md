# SA12 - ARIMA GARCH — résultats et analyse

Période commune 2021-04-01 → 2026-10-09 · capital 100 000 EUR · commission 5 pb (minimum 1 EUR), demi-spread 3 pb, slippage 2 pb · quantités fixées à la décision, exécution à l'ouverture suivante · cash non rémunéré · 252 séances par an.

Source : commit `10f6d902af68` (CLEAN), magasin `750c23dfffc3`, données à jour au 2026-10-09. Évaluation rétrospective : l'historique d'ETF_WORLD a déjà été regardé dans les exercices précédents, ce n'est pas un échantillon vierge.

Étude dédiée (`scripts/run_arima_garch_study.py`) : les livres de la comparaison, le témoin EWMA de SA11 et trois contrôles de SA12 sans code de catalogue (D0, D1, D2), exécutés par le même moteur. L'ARIMA et le GARCH sont réestimés chaque soir sur 756 rendements d'ouverture à ouverture, avec un seul fil de calcul. L'hypothèse `sa12_arima_garch`, ses contrôles et ses statuts ont été écrits avant le premier ajustement.

## 1. Indicateurs de résultat globaux

| Indicateur | Stratégie | Fonds détenu (buy & hold ETF_WORLD) |
|---|---:|---:|
| Période mesurée | 2021-04-01 → 2026-10-09 (1416 séances) | idem |
| Rang au classement commun (QUALITY_V1) | 10 | n/a |
| Score de qualité QUALITY_V1 (0-100 %) | 0.0% | n/a |
| - bloc marché (IR et alpha contre le fonds détenu) | 0.22 | n/a |
| - bloc significativité (Sharpe déflaté) | 0.02 | n/a |
| - bloc risque (drawdown relatif) | 1.00 | n/a |
| - bloc robustesse (sous-périodes ; stress approché des coûts) | 0.00 | n/a |
| - bloc implémentation (poids des coûts) | 0.00 | n/a |
| Rendement net total | -1.72% | +94.79% |
| Rendement brut total (mêmes ordres, sans coûts) | +2.30% | +94.89% |
| Rendement net annualisé | -0.31% | +12.83% |
| Volatilité annualisée | 2.12% | 13.79% |
| Ratio de Sharpe net (taux sans risque 0) | -0.14 | +0.93 |
| Ratio de Sortino net (taux sans risque 0) | -0.17 | +1.30 |
| Perte maximale (max drawdown) | -6.99% | -21.64% |
| Alpha annualisé contre le fonds détenu | -0.63% | n/a |
| Bêta contre le fonds détenu | 0.03 | n/a |
| Ratio d'information contre le fonds détenu | -0.97 | n/a |
| Alpha annualisé contre SA1 (MA20) | -0.49% | +9.12% |
| Bêta contre SA1 (MA20) | 0.05 | 1.00 |
| Exposition moyenne (part investie) | 4.0% | 99.9% |
| Ordres exécutés | 75 | 1 |
| Coûts payés (EUR) | 4,022 | 100 |
| Rotation annuelle (multiple de l'actif moyen) | 7.20 | 0.13 |
| Rendement net, deux premiers tiers | +0.00% | +57.42% |
| Rendement net, dernier tiers | -1.72% | +23.74% |
| Rendement net, second run réel à coûts doublés | -5.70% | n/a |
| Sharpe net, second run réel à coûts doublés | -0.47 | n/a |

Le score QUALITY_V1 est une **moyenne géométrique pondérée** de cinq blocs bornés entre 0 et 1 (marché 30 %, significativité 25 %, risque 15 %, robustesse 20 %, implémentation 10 %) : un seul bloc à zéro donne un score nul. Un score nul n'est donc ni une probabilité de gain nulle, ni une égalité économique entre deux stratégies ; le bloc implémentation, par exemple, tombe à zéro dès que les coûts atteignent 30 % du gain brut. Le bloc robustesse contient un **stress approché** des coûts, `net - (brut - net)` sur les mêmes ordres ; les deux dernières lignes du tableau viennent d'un **second run réel** à coûts doublés, où les quantités et la trajectoire changent, et n'entrent pas dans le score. Le score est déflaté par les essais de cette étude seulement, pas par la recherche antérieure : le classement est exploratoire, et un écart de quelques points entre deux scores n'est pas un test de supériorité. Les alphas sont des estimations ponctuelles sans intervalle, avec un taux sans risque nul ; l'alpha contre SA1 compare à une règle active, ce n'est pas un alpha de marché. Le fonds détenu est l'étalon du score et n'est pas noté. « n/a » : la mesure n'existe pas ; elle n'est jamais remplacée par zéro.

### Classement de tous les livres de l'étude, sur la même période

| Livre | Rang | Score | Net | Net, coûts x2 | Sharpe | Perte max. | Alpha/an | Exposition | Coûts (EUR) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 50/50 rebalanced | 1 | 74.0% | +103.35% | +102.72% | +0.96 | -22.47% | +0.51% | 100% | 736 |
| EWMA 0.94 control | 2 | 50.7% | +73.37% | +70.88% | +0.93 | -15.45% | +0.39% | 88% | 1,519 |
| SA6 - vol control | 3 | 49.0% | +67.43% | +65.50% | +0.90 | -15.72% | +0.03% | 85% | 1,445 |
| SA10 - ensemble | 4 | 47.8% | +32.06% | +29.55% | +0.86 | -11.76% | -0.12% | 42% | 1,986 |
| SA11 - GARCH vol control | 5 | 45.6% | +65.98% | +61.30% | +0.87 | -16.50% | -0.39% | 87% | 3,749 |
| SA3 - smooth MA | 6 | 45.4% | +57.88% | +56.88% | +0.79 | -21.64% | +0.39% | 71% | 680 |
| D0 - same risk no filter | 7 | 43.4% | +64.07% | +56.33% | +0.85 | -17.77% | -0.46% | 86% | 5,788 |
| SA2 - dual momentum | 8 | 40.7% | +69.19% | +62.36% | +0.78 | -22.78% | -1.03% | 86% | 4,629 |
| SA5 - relative tilt | 9 | 27.0% | +72.83% | +46.36% | +0.76 | -22.86% | -2.40% | 100% | 20,517 |
| D1 - ARIMA EWMA | 10 | 0.0% | -2.46% | -6.52% | -0.20 | -7.32% | -0.77% | 4% | 4,126 |
| D2 - constant mean GARCH | 10 | 0.0% | +0.00% | +0.00% | n/a | 0.00% | +0.00% | 0% | 0 |
| SA1 - std MA20 | 10 | 0.0% | +20.45% | +4.41% | +0.42 | -18.95% | -1.61% | 66% | 15,730 |
| **SA12 - ARIMA GARCH** | 10 | 0.0% | -1.72% | -5.70% | -0.14 | -6.99% | -0.63% | 4% | 4,022 |
| SA4 - pullback | 10 | 0.0% | +4.43% | -0.16% | +0.41 | -3.42% | +0.18% | 4% | 4,572 |
| SA9 - VIX relief | 10 | 0.0% | -0.70% | -2.77% | -0.04 | -8.00% | -0.71% | 4% | 2,041 |
| buy & hold World | n/a | n/a | +94.79% | +94.34% | +0.93 | -21.64% | n/a | 100% | 100 |

Tous ces livres sont exécutés par le même moteur, sur la même période, avec les mêmes coûts. Les contrôles (noms commençant par D ou C) et les deux références ne sont pas des candidats. Ces chiffres ne se comparent pas à ceux d'une autre étude, mesurés depuis une autre date ; un rang n'est pas une probabilité de succès.

## 2. Analyse

### Faits mesurés

| Période | Du | Au | Valorisations | Rendements | Stratégie | ETF_WORLD (clôture) | Fonds détenu (net) | Écart relatif | Poids de clôture moyen | Poids de clôture min. | Poids de clôture max. |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Plus forte baisse (sommet → creux) | 2025-05-13 | 2026-03-26 | 225 | 224 | -6.99% | +8.47% | +8.47% | -14.25% | 13% | 0% | 100% |
| Plus forte hausse (creux → sommet ultérieur, durée libre) | 2026-03-26 | 2026-08-05 | 92 | 91 | +5.46% | +17.56% | +17.55% | -10.29% | 26% | 0% | 100% |
| Pires 63 rendements consécutifs | 2026-01-07 | 2026-04-08 | 64 | 63 | -4.77% | -0.92% | -0.92% | -3.88% | 13% | 0% | 100% |
| Meilleurs 63 rendements consécutifs | 2026-03-19 | 2026-06-19 | 64 | 63 | +3.75% | +13.50% | +13.50% | -8.58% | 30% | 0% | 99% |
| Plus fort retard relatif sur le fonds détenu | 2021-05-19 | 2026-10-06 | 1381 | 1380 | -1.72% | +100.27% | +100.17% | -50.90% | 4% | 0% | 100% |
| Plus forte avance relative sur le fonds détenu | 2025-02-19 | 2025-04-09 | 36 | 35 | +0.00% | -21.66% | -21.64% | +27.62% | 0% | 0% | 0% |
| Plus forte baisse du fonds détenu | 2025-02-19 | 2025-04-09 | 36 | 35 | +0.00% | -21.66% | -21.64% | +27.62% | 0% | 0% | 0% |
| Plus forte hausse du fonds détenu | 2021-05-19 | 2026-10-06 | 1381 | 1380 | -1.72% | +100.27% | +100.17% | -50.90% | 4% | 0% | 100% |

Chaque ligne va de la valeur de la séance « Du » à celle de la séance « Au » : N valorisations, donc N - 1 rendements. « Plus forte hausse » est la plus grande hausse d'un creux à un sommet ultérieur, de durée libre : ce n'est ni une position ni un trade. Les deux périodes relatives sont choisies sur le rapport de la stratégie au fonds détenu, dont l'« écart relatif » `(1 + stratégie) / (1 + fonds) - 1` est la variation. Le « poids de clôture » est la part de l'actif net détenue en fonds à la valorisation du soir, le reste étant du cash non rémunéré : il a pu dériver avec les cours, et le multiplier par le rendement du fonds ne reconstitue pas le résultat. Une décision prise le soir de t (signal et poids cible de la ligne t) est exécutée à l'ouverture de t + 1 et n'apparaît dans le poids détenu qu'à la ligne t + 1.

### Baisses sous un sommet et retour à ce sommet

| Rang | Sommet | Creux | Profondeur | Retour au sommet | Jours calendaires |
|---:|---|---|---:|---|---:|
| 1 | 2025-05-13 | 2026-03-26 | -6.99% | non récupéré au 2026-10-09 | 514 (en cours) |
| 2 | 2025-04-15 | 2025-04-16 | -0.38% | 2025-04-25 | 10 |
| 3 | 2025-05-05 | 2025-05-06 | -0.23% | 2025-05-13 | 8 |

Drawdown au 2026-10-09 : **-2.36%** sous le plus haut de la période.
Plus longue période sous un sommet : **514 jours calendaires**, du 2025-05-13 au 2026-10-09 (en cours, creux à -6.99%).

### Par année et par mois

| Année | Stratégie | Fonds détenu | 50/50 rebalancé | Séances |
|---|---:|---:|---:|---:|
| 2021 (partielle, depuis le 2021-04-01) | +0.00% | +18.40% | +20.74% | 195 |
| 2022 | +0.00% | -13.73% | -14.00% | 257 |
| 2023 | +0.00% | +19.61% | +20.88% | 255 |
| 2024 | +0.00% | +27.07% | +30.19% | 256 |
| 2025 | -2.94% | +6.61% | +5.02% | 255 |
| 2026 (partielle, au 2026-10-09) | +1.26% | +17.68% | +18.49% | 198 |

Mois : **8 positifs, 8 négatifs, 51 sans variation** sur 67 (mois incomplets : 2026-10 s'arrête au 2026-10-09). Pire mois : **2026-03** (-4.03%, fonds détenu -4.72%). Meilleur mois : **2026-04** (+2.49%, fonds détenu +8.13%).

Activité : une position est détenue à la clôture de **69 valorisations sur 1416** ; le poids total détenu y va de 16.8% à 100.0% (moyenne sur toutes les valorisations : 4.0%).

### Qualité opérationnelle et prévisions (étude SA12)

- **Couverture.** 1416 décisions ; fenêtre de 757 ouvertures servie 1416 fois ; prévision jointe utilisable 1415 fois (99.93%). Moyennes ARIMA acceptées : 1415. Ajustements de variance tentés : 1415, dont GARCH accepté 1415 et repli EWMA 0 (0.00%). Échecs par étape : {'ARIMA:ARIMA_NOT_CONVERGED': 1}.
- **Paires évaluables.** 1413 prévisions sur 1416 ont une cible connue (rendement de l'ouverture t+1 à l'ouverture t+2) ; exclues : {'no_forecast': 1, 'target_pending': 2, 'target_missing': 0}.
- **Moyenne prévue.** MSE 9.2497e-05 pour ARIMA, 9.2133e-05 pour la prévision nulle et 9.2002e-05 pour la moyenne de la fenêtre. Corrélation prévision/réalisation +0.018. Signe juste 56.1%, contre 56.7% pour « toujours en hausse » ; justesse équilibrée 50.4%.
- **Signaux d'entrée.** La prévision dépasse 20 pb sur 31 origines sur 1413 (2.19%) et est positive sur 1309 (92.6%). Rendement réalisé moyen après un signal d'entrée : +0.046%, contre +0.047% sur toutes les origines.
- **Épisodes de position.** 29 épisodes, dont 29 terminés ; 10 gagnants ; net moyen -0.05%.

### SA12 contre ses contrôles

| Coûts | Contrôle | Sharpe SA12 | Sharpe contrôle | Écart | Intervalle 95 % | Perte max. SA12 | Perte max. contrôle |
|---|---|---:|---:|---:|---|---:|---:|
| x1 | D0 - same risk no filter | -0.136 | +0.852 | -0.987 | [-2.101 ; +0.252] | -6.99% | -17.77% |
| x1 | D1 - ARIMA EWMA | -0.136 | -0.196 | +0.061 | [-0.037 ; +0.170] | -6.99% | -7.32% |
| x1 | D2 - constant mean GARCH | -0.136 | n/a | n/a | [n/a ; n/a] | -6.99% | 0.00% |
| x1 | SA11 - GARCH vol control | -0.136 | +0.866 | -1.001 | [-2.094 ; +0.223] | -6.99% | -16.50% |
| x1 | SA6 - vol control | -0.136 | +0.899 | -1.034 | [-2.087 ; +0.161] | -6.99% | -15.72% |
| x1 | EWMA 0.94 control | -0.136 | +0.934 | -1.070 | [-2.142 ; +0.138] | -6.99% | -15.45% |
| x2 | D0 - same risk no filter | -0.468 | +0.774 | -1.241 | [-2.335 ; -0.032] | -9.46% | -17.84% |
| x2 | D1 - ARIMA EWMA | -0.468 | -0.531 | +0.063 | [-0.038 ; +0.180] | -9.46% | -9.94% |
| x2 | D2 - constant mean GARCH | -0.468 | n/a | n/a | [n/a ; n/a] | -9.46% | 0.00% |
| x2 | SA11 - GARCH vol control | -0.468 | +0.820 | -1.288 | [-2.359 ; -0.093] | -9.46% | -16.59% |
| x2 | SA6 - vol control | -0.468 | +0.880 | -1.347 | [-2.376 ; -0.176] | -9.46% | -15.78% |
| x2 | EWMA 0.94 control | -0.468 | +0.912 | -1.380 | [-2.423 ; -0.193] | -9.46% | -15.51% |

D0 : même ARIMA, même variance, filtre de direction toujours actif. D1 : même ARIMA, variance EWMA. D2 : moyenne constante et GARCH. Ce sont des contrôles de recherche, sans code de catalogue, et aucun n'est candidat. Bootstrap apparié par blocs de 20 séances, 5000 tirages, graine 20261010.

Écart de perte jointe `log(v) + e²/v` SA12 moins D1 (même moyenne, donc une comparaison de variances) : -0.0111, intervalle [-0.0646 ; +0.0452].

### Statut de l'hypothèse préinscrite `sa12_arima_garch` : **INSUFFICIENT_EVIDENCE**

- 29 completed position episodes, under 30

Ce statut répond à une seule question, écrite avant le run : le filtre de direction améliore-t-il le même dimensionnement de risque sans lui (D0) ? Il ne dit pas « ARIMA-GARCH ne fonctionne jamais », et l'apport de GARCH se lit à part, contre D1.

### En résumé

Détenir ETF_WORLD seulement quand un ARIMA(1,0,1), réestimé chaque soir sur 756 rendements d'ouverture à ouverture, prévoit plus de 20 pb pour le rendement de l'ouverture de t + 1 à l'ouverture de t + 2 (la position est gardée tant que la prévision reste strictement positive), au poids min(1, 12 % / max(σ, 5 %)) où σ vient d'un GARCH(1,1) ajusté sur les innovations de l'ARIMA. Sur cet historique la prévision ne franchit le seuil que 31 soirs sur 1 413, tous à partir du 10 avril 2025 : le livre reste en cash pendant quatre ans, puis prend 29 positions courtes qui, ensemble, perdent 1,72 % net, quand le même dimensionnement sans filtre (D0) gagne 64,07 %. Le statut préinscrit est INSUFFICIENT_EVIDENCE parce qu'il manque un épisode terminé (29 pour 30 requis) ; l'écart de Sharpe mesuré contre D0 est de -0,99. Cela ne dit rien des modèles ARIMA-GARCH en général.

### Points forts

- **Fait.** La chaîne de calcul fonctionne : prévision jointe utilisable à 1 415 décisions sur 1 416 (99,93 %), un seul ARIMA non convergé, aucun repli EWMA de la variance.
- **Fait.** Perte maximale de -6,99 % contre -21,64 % pour le fonds et -17,77 % pour D0, volatilité de 2,1 %. **Lecture.** C'est la conséquence d'une exposition moyenne de 4,0 % (une position à la clôture de 69 valorisations sur 1 416), pas d'un choix heureux des séances.
- **Fait.** Le livre est en cash pendant toute la baisse du fonds du 2025-02-19 au 2025-04-09 (-21,64 %). **Lecture.** Ce n'est pas une protection décidée par le modèle : avant le 10 avril 2025 la prévision n'a jamais dépassé 18,2 pb (13,5 pb de 2021 à 2024), quel que soit le marché, et aucune position n'avait encore été prise.
- **Fait.** Brut de coûts, les 29 épisodes rapportent +2,30 %.
- **Fait.** Sur la même moyenne, la variance GARCH a une perte jointe moyenne un peu plus basse que la variance EWMA (-8,4848 contre -8,4737) ; l'écart apparié, -0,011, a un intervalle à 95 % de [-0,065 ; +0,045], qui contient zéro.

### Points faibles

- **Fait.** -1,72 % net sur la période, contre +64,07 % pour D0, +67,43 % pour SA6 et +94,79 % pour le fonds ; Sharpe -0,14. Dans le second run à coûts doublés : -5,70 %, Sharpe -0,47.
- **Fait.** La prévision de la moyenne n'est pas meilleure que deux prévisions naïves : erreur quadratique moyenne de 9,2497e-05, contre 9,2133e-05 pour la prévision nulle et 9,2002e-05 pour la moyenne de la fenêtre (les intervalles des deux écarts contiennent zéro) ; corrélation avec le rendement réalisé +0,018 ; signe juste 56,1 % contre 56,7 % pour « toujours en hausse ».
- **Fait.** Les 31 signaux d'entrée ne sélectionnent pas de meilleures séances : le rendement réalisé moyen après un signal est de +0,046 %, contre +0,047 % sur toutes les origines, et 15 signaux sur 31 sont suivis d'une hausse.
- **Fait.** 22 épisodes sur 29 ne durent qu'une valorisation : achat à l'ouverture, prévision redevenue négative ou nulle le soir même, vente à l'ouverture suivante. 75 ordres et 4 022 EUR de coûts pour environ 2 300 EUR de gain brut : les coûts dépassent le gain brut.
- **Fait.** 10 épisodes gagnants sur 29, résultat net moyen de -0,05 % par épisode.
- **Fait.** Le sommet du 2025-05-13 n'est pas retrouvé au 2026-10-09, 514 jours plus tard (-2,36 % sous ce sommet).
- **Fait.** Score nul au classement de l'étude : les blocs robustesse et implémentation sont à zéro. Un score nul n'est pas une égalité économique avec les autres livres à zéro.

### Ce qui s'est passé pendant la période où la stratégie a le plus perdu

**Fait.** La plus forte baisse va du sommet du 2025-05-13 (100 648,6 EUR) au creux du 2026-03-26 (93 610,0 EUR) : -6,99 %, pendant que le fonds gagne +8,47 %. Elle n'est pas continue : c'est la somme de 16 épisodes, dont 3 gagnants, qui coûtent 2 443 EUR de frais. Les plus lourds : le soir du 2025-07-31 la prévision vaut +20,6 pb et la cible 89,5 % ; l'achat est exécuté à l'ouverture du 2025-08-01 (568,04), le fonds clôture à 556,13, la prévision du soir tombe à -21,4 pb et la vente est exécutée à l'ouverture du 2025-08-04 (557,91) : -1,75 % sur le livre. Le soir du 2026-03-05 la prévision vaut +21,2 pb et la cible 98,8 % ; 156 parts sont achetées à l'ouverture du 2026-03-06 (617,43) ; la prévision du soir est de -6,3 pb et la vente est exécutée à l'ouverture du lundi 2026-03-09 (601,27), 2,65 % plus bas : -2,78 % sur le livre, le plus mauvais épisode. Le soir du 2026-03-18 (+21,7 pb, cible 96,1 %) conduit de même à un achat à l'ouverture du 19 et à une vente à celle du 20 (-0,87 %). Les 31 signaux d'entrée de la période suivent tous un rendement d'ouverture à ouverture positif, de +1,73 % en moyenne quand l'amplitude moyenne de ce rendement est de 0,65 % sur l'ensemble des séances ; depuis le 10 avril 2025 la corrélation entre ce dernier rendement et la prévision est de +0,82. **Lecture.** Le livre achète donc au lendemain d'une forte hausse à l'ouverture et revend le plus souvent une séance plus tard ; que ce mécanisme explique la perte, plutôt que le hasard de 16 épisodes, n'est pas établi.

### Ce qui s'est passé pendant la période où la stratégie a le plus gagné

**Fait.** La plus forte hausse d'un creux à un sommet ultérieur va du 2026-03-26 au 2026-08-05 : +5,46 %, contre +17,56 % pour le fonds, avec un poids de clôture moyen de 26 %. Elle tient à six épisodes dont quatre gagnants. Le principal : le soir du 2026-04-14 la prévision vaut +22,2 pb et la cible 84,8 % ; l'achat est exécuté à l'ouverture du 2026-04-15 (622,67) ; la prévision reste ensuite strictement positive treize soirs de suite (entre +0,6 et +23,3 pb) et la position est gardée, entre 80 % et 99 % du livre ; le soir du 2026-05-05 elle passe à -3,8 pb et la vente est exécutée à l'ouverture du 2026-05-06 (645,95) : +3,13 % sur le livre en 14 valorisations, l'épisode le plus long. Puis le soir du 2026-07-31 (+29,6 pb, cible 89,6 %) : achat à l'ouverture du 2026-08-03 (682,22), vente à l'ouverture du 2026-08-07 (697,95) après une prévision de -2,6 pb le soir du 6 : +1,91 %. **Lecture.** Les gains viennent des rares épisodes tenus plusieurs séances dans une hausse du fonds ; le livre n'en capte qu'une fraction.

### Situations de marché les plus risquées pour cette stratégie

- **Observé.** Marché heurté, où un fort rendement d'ouverture à ouverture est suivi d'un mouvement contraire : la prévision change de signe d'un soir à l'autre (+148,7 pb le 2025-04-10, -183,9 pb le 2025-04-11, +125,0 pb le 2025-04-14, -46,0 pb le 2025-04-15) ; le livre achète et revend à chaque fois et paie deux fois les coûts.
- **Observé.** Entrée la veille d'un gap baissier : acheté à l'ouverture du 2026-03-06, revendu à celle du 2026-03-09, 2,65 % plus bas, avec 98,8 % du livre.
- **Observé.** Hausse régulière du fonds avec des rendements quotidiens modestes (2021, 2023, 2024) : la prévision reste sous le seuil et le livre reste en cash pendant que le fonds gagne +18,4 %, +19,6 % et +27,1 %.
- **Plausible.** Coefficients ARIMA qui changent d'une fenêtre à l'autre : la moyenne annuelle du coefficient autorégressif estimé passe de -0,17 en 2021 et 2022 à -0,44 en 2025 et -0,67 en 2026, celle du coefficient de moyenne mobile de +0,09 à +0,48. Les prévisions deviennent alors plus amples, ce qui coïncide avec l'apparition des signaux ; l'effet sur la décision n'est pas isolé ici.

### Mesures complémentaires (voir SA12_study_10102026.md)

- **Fait.** SA12 contre D0 (même ARIMA, même variance, filtre toujours ouvert) : écart de Sharpe de -0,987, intervalle bootstrap à 95 % [-2,101 ; +0,252] aux coûts de base ; -1,241, intervalle [-2,335 ; -0,032], dans le second run à coûts doublés.
- **Fait.** SA12 contre D1 (même ARIMA, variance EWMA) : écart de Sharpe de +0,061, intervalle [-0,037 ; +0,170] ; D1 fait -2,46 % net. GARCH et EWMA ne sont pas départagés.
- **Fait.** D2 (moyenne constante et GARCH) n'a pris aucune position : une moyenne constante estimée sur 756 rendements ne dépasse jamais 20 pb par séance.
- **Fait.** Résidus standardisés de la prévision jointe : écart-type 1,04, kurtosis 11,1, autocorrélation de leurs carrés +0,24. La variance prévue ne rend compte ni de toutes les queues ni de toute la persistance.
- **Lecture.** Le filtre de direction a surtout retiré de l'exposition : D0, investi à 86 % en moyenne, a suivi la hausse du fonds ; SA12, investi à 4 %, ne l'a pas suivie. Avec un intervalle aussi large aux coûts de base, cet écart reste une mesure sur ce chemin.

### Ce que ces résultats n'établissent pas, et ce qui reste à mesurer

- Le statut INSUFFICIENT_EVIDENCE est celui des critères écrits avant le run : 29 épisodes terminés pour 30 requis. Le seuil n'a pas été modifié après lecture. Il ne dit ni que le filtre est utile ni qu'il est nuisible ; l'écart mesuré contre D0 est négatif, et son intervalle aux coûts de base contient zéro.
- Le seuil d'entrée de 20 pb reprend un coût aller-retour de référence ; il a laissé la stratégie inactive pendant quatre ans. L'abaisser après avoir lu ce résultat serait une nouvelle variante, à préinscrire.
- L'évolution des coefficients ARIMA dans le temps est exportée (`sa12_forecasts.csv`) mais n'est pas analysée au-delà des moyennes annuelles citées.
- La moyenne et la variance sont estimées en deux étapes, et la variance à deux pas ignore l'incertitude des paramètres.
- La vérification prospective, configuration figée, commence à la première séance XPAR après le 2026-10-10.

## 3. Historique : sous-jacent, indicateurs utilisés et valeur de la stratégie

Une ligne par séance. Les indicateurs sont ceux que la stratégie a lus à sa décision du soir (23:00 Paris), recalculés par ses propres signaux sur le magasin tel que le run l'a lu. Le poids cible de la ligne t est décidé ce soir-là et exécuté à l'ouverture de t + 1 ; le poids détenu de la ligne t est celui du portefeuille à la valorisation de t. Une case vide est un indicateur sans valeur ce jour-là. Les ordres, les prix d'exécution et les coûts de chaque séance ne sont pas dans ce tableau : ils sont dans `fills.csv` de l'étude.

Colonnes propres à SA12 : la prévision `mu_2`, en points de base, du rendement de l'ouverture de t + 1 à l'ouverture de t + 2 ; la volatilité annualisée prévue pour ce rendement ; le repli éventuel de la variance sur l'EWMA ; le filtre, lu sur le poids détenu ce soir-là ; le poids avant application de la bande de 3 points. Le détail de chaque ajustement est dans `sa12_forecasts.csv` de l'étude.

| Séance | Clôture ETF_WORLD | Ouverture ETF_WORLD | Prévision mu_2 (pb) | Volatilité prévue (annualisée) | Repli EWMA (1 = oui) | Filtre (1 = ouvert) | Poids avant bande | Poids cible ETF_WORLD | Poids détenu ETF_WORLD | Valeur nette (EUR) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2021-04-01 | 363.45 | 362.70 | +5.89 | 11.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-04-06 | 366.90 | 366.95 | +6.66 | 12.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-04-07 | 365.06 | 365.67 | +4.63 | 12.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-04-08 | 367.00 | 367.17 | +5.86 | 11.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-04-09 | 368.02 | 367.52 | +5.29 | 10.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-04-12 | 368.00 | 368.49 | +5.74 | 10.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-04-13 | 368.64 | 369.11 | +5.56 | 9.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-04-14 | 368.64 | 368.66 | +4.96 | 9.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-04-15 | 370.54 | 368.59 | +5.12 | 9.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-04-16 | 371.71 | 370.73 | +5.95 | 9.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-04-19 | 369.37 | 371.77 | +5.55 | 9.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-04-20 | 364.36 | 368.36 | +3.86 | 11.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-04-21 | 367.25 | 365.84 | +4.09 | 11.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-04-22 | 369.77 | 368.44 | +5.92 | 11.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-04-23 | 368.62 | 367.12 | +4.23 | 11.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-04-26 | 369.63 | 368.21 | +5.19 | 10.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-04-27 | 369.11 | 369.83 | +5.30 | 10.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-04-28 | 368.99 | 370.00 | +4.77 | 9.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-04-29 | 368.14 | 370.16 | +4.84 | 9.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-04-30 | 369.03 | 368.94 | +4.26 | 9.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-05-03 | 369.95 | 369.98 | +5.09 | 9.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-05-04 | 365.20 | 370.14 | +4.69 | 8.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-05-05 | 370.45 | 368.99 | +4.13 | 8.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-05-06 | 368.58 | 369.79 | +4.89 | 8.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-05-07 | 371.06 | 370.41 | +4.81 | 8.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-05-10 | 370.46 | 371.07 | +4.85 | 8.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-05-11 | 363.34 | 366.23 | +2.69 | 12.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-05-12 | 362.02 | 363.90 | +3.68 | 12.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-05-13 | 362.32 | 357.97 | +2.03 | 16.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-05-14 | 365.69 | 363.82 | +6.84 | 18.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-05-17 | 364.27 | 366.17 | +5.13 | 17.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-05-18 | 364.50 | 366.58 | +4.63 | 16.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-05-19 | 358.08 | 359.26 | +1.55 | 20.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-05-20 | 364.52 | 361.28 | +5.22 | 18.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-05-21 | 366.31 | 364.74 | +5.49 | 18.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-05-24 | 367.97 | 366.31 | +4.86 | 16.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-05-25 | 366.41 | 368.00 | +5.06 | 15.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-05-26 | 368.08 | 367.80 | +4.36 | 14.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-05-27 | 369.15 | 367.59 | +4.32 | 13.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-05-28 | 370.43 | 370.00 | +5.33 | 13.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-05-31 | 367.87 | 369.90 | +4.46 | 12.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-06-01 | 368.80 | 369.15 | +4.02 | 11.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-06-02 | 370.56 | 369.66 | +4.59 | 10.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-06-03 | 371.19 | 370.61 | +4.87 | 10.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-06-04 | 372.23 | 371.51 | +4.74 | 9.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-06-07 | 372.05 | 372.80 | +4.92 | 9.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-06-08 | 372.25 | 372.95 | +4.65 | 9.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-06-09 | 372.93 | 372.79 | +4.55 | 9.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-06-10 | 373.89 | 372.89 | +4.87 | 8.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-06-11 | 376.37 | 373.75 | +5.14 | 8.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-06-14 | 375.95 | 377.76 | +6.27 | 11.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-06-15 | 376.30 | 377.84 | +4.81 | 10.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-06-16 | 377.23 | 377.11 | +4.79 | 10.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-06-17 | 380.82 | 377.45 | +5.10 | 9.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-06-18 | 377.41 | 380.84 | +6.24 | 11.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-06-21 | 379.22 | 374.97 | +2.78 | 15.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-06-22 | 381.34 | 380.31 | +7.21 | 16.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-06-23 | 379.91 | 381.87 | +5.32 | 15.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-06-24 | 382.55 | 381.03 | +4.56 | 14.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-06-25 | 383.27 | 382.52 | +5.57 | 13.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-06-28 | 383.01 | 383.53 | +5.28 | 12.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-06-29 | 384.92 | 384.15 | +5.07 | 11.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-06-30 | 384.97 | 385.10 | +5.27 | 10.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-07-01 | 386.05 | 386.36 | +5.48 | 10.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-07-02 | 388.41 | 387.76 | +5.43 | 10.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-07-05 | 389.55 | 388.67 | +5.25 | 9.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-07-06 | 388.37 | 388.41 | +4.89 | 9.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-07-07 | 391.12 | 389.93 | +5.70 | 9.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-07-08 | 385.70 | 388.96 | +4.60 | 9.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-07-09 | 390.02 | 387.31 | +4.39 | 9.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-07-12 | 391.41 | 390.39 | +6.16 | 10.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-07-13 | 393.55 | 391.74 | +5.31 | 10.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-07-14 | 391.84 | 392.18 | +5.18 | 9.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-07-15 | 390.66 | 390.81 | +4.59 | 9.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-07-16 | 389.25 | 390.26 | +4.85 | 9.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-07-19 | 381.57 | 386.12 | +3.44 | 12.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-07-20 | 386.76 | 383.92 | +4.11 | 12.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-07-21 | 389.65 | 388.47 | +6.49 | 14.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-07-22 | 391.46 | 391.43 | +5.70 | 14.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-07-23 | 395.78 | 393.73 | +5.67 | 13.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-07-26 | 395.10 | 394.56 | +5.19 | 12.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-07-27 | 391.41 | 394.74 | +4.98 | 11.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-07-28 | 394.28 | 393.35 | +4.40 | 11.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-07-29 | 394.37 | 393.81 | +5.11 | 10.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-07-30 | 392.38 | 390.58 | +3.60 | 11.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-08-02 | 393.93 | 394.53 | +6.47 | 12.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-08-03 | 393.20 | 393.25 | +4.25 | 11.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-08-04 | 395.17 | 394.91 | +5.58 | 11.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-08-05 | 396.69 | 395.28 | +5.05 | 10.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-08-06 | 399.04 | 397.41 | +5.86 | 10.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-08-09 | 399.57 | 398.92 | +5.59 | 10.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-08-10 | 400.94 | 399.99 | +5.51 | 9.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-08-11 | 401.22 | 401.43 | +5.63 | 9.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-08-12 | 401.87 | 401.37 | +5.09 | 9.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-08-13 | 401.45 | 402.85 | +5.72 | 9.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-08-16 | 400.03 | 399.98 | +4.05 | 10.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-08-17 | 401.28 | 400.15 | +5.32 | 9.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-08-18 | 401.38 | 401.63 | +5.63 | 9.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-08-19 | 397.26 | 395.36 | +2.61 | 15.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-08-20 | 399.80 | 396.90 | +5.88 | 13.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-08-23 | 402.55 | 401.14 | +6.72 | 14.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-08-24 | 402.94 | 403.59 | +6.11 | 14.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-08-25 | 403.31 | 403.65 | +5.30 | 12.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-08-26 | 401.92 | 402.03 | +4.78 | 12.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-08-27 | 403.14 | 401.41 | +5.11 | 11.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-08-30 | 405.06 | 403.34 | +6.01 | 10.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-08-31 | 404.25 | 404.99 | +5.85 | 10.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-09-01 | 404.04 | 405.57 | +5.50 | 9.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-09-02 | 404.83 | 404.03 | +4.82 | 9.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-09-03 | 404.41 | 404.64 | +5.55 | 9.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-09-06 | 406.91 | 405.56 | +5.59 | 9.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-09-07 | 404.94 | 405.97 | +5.40 | 8.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-09-08 | 403.43 | 404.13 | +4.62 | 9.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-09-09 | 404.18 | 401.91 | +4.51 | 10.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-09-10 | 402.12 | 403.68 | +5.91 | 10.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-09-13 | 401.57 | 403.66 | +5.14 | 9.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-09-14 | 401.00 | 401.75 | +4.44 | 10.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-09-15 | 399.98 | 400.78 | +4.74 | 9.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-09-16 | 401.98 | 402.67 | +5.70 | 9.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-09-17 | 400.77 | 403.93 | +5.43 | 9.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-09-20 | 393.58 | 396.38 | +2.26 | 17.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-09-21 | 396.41 | 396.17 | +5.10 | 15.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-09-22 | 398.61 | 397.03 | +5.29 | 13.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-09-23 | 402.33 | 400.42 | +6.24 | 14.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-09-24 | 401.49 | 400.98 | +5.28 | 12.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-09-27 | 401.71 | 404.16 | +6.86 | 12.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-09-28 | 394.36 | 400.67 | +4.45 | 13.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-09-29 | 397.51 | 395.75 | +4.12 | 16.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-09-30 | 396.40 | 399.62 | +7.19 | 15.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-10-01 | 394.10 | 390.66 | +1.71 | 23.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-10-04 | 389.70 | 393.46 | +6.72 | 19.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-10-05 | 396.18 | 391.65 | +4.43 | 17.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-10-06 | 393.58 | 392.95 | +6.00 | 15.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-10-07 | 402.20 | 398.98 | +7.96 | 18.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-10-08 | 400.41 | 401.76 | +6.70 | 17.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-10-11 | 401.45 | 398.68 | +4.81 | 16.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-10-12 | 398.66 | 395.03 | +4.64 | 16.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-10-13 | 397.44 | 396.75 | +6.58 | 14.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-10-14 | 403.90 | 400.39 | +7.17 | 14.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-10-15 | 407.05 | 405.32 | +7.46 | 16.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-10-18 | 407.27 | 406.60 | +6.22 | 14.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-10-19 | 409.45 | 407.64 | +6.13 | 13.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-10-20 | 410.78 | 409.19 | +6.46 | 12.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-10-21 | 410.05 | 409.19 | +5.90 | 11.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-10-22 | 411.07 | 411.35 | +6.63 | 10.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-10-25 | 413.46 | 411.50 | +5.76 | 10.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-10-26 | 416.44 | 415.45 | +7.13 | 12.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-10-27 | 414.56 | 415.17 | +5.64 | 10.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-10-28 | 413.27 | 414.00 | +5.62 | 10.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-10-29 | 417.15 | 411.65 | +5.31 | 11.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-11-01 | 418.05 | 418.47 | +8.50 | 16.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-11-02 | 419.53 | 417.44 | +5.69 | 14.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-11-03 | 419.55 | 419.49 | +7.03 | 13.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-11-04 | 423.91 | 423.46 | +7.96 | 13.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-11-05 | 426.09 | 424.05 | +6.88 | 12.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-11-08 | 425.04 | 424.83 | +7.03 | 11.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-11-09 | 423.61 | 423.73 | +6.42 | 10.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-11-10 | 425.13 | 424.25 | +6.88 | 10.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-11-11 | 425.49 | 424.71 | +6.68 | 9.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-11-12 | 428.23 | 426.12 | +7.00 | 9.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-11-15 | 430.01 | 428.85 | +7.39 | 10.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-11-16 | 433.82 | 431.36 | +7.35 | 10.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-11-17 | 433.50 | 434.27 | +7.28 | 11.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-11-18 | 432.03 | 433.17 | +6.10 | 10.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-11-19 | 433.60 | 434.41 | +7.27 | 10.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-11-22 | 435.97 | 435.43 | +7.29 | 9.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-11-23 | 430.03 | 431.68 | +5.71 | 11.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-11-24 | 433.74 | 432.38 | +7.55 | 10.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-11-25 | 434.90 | 435.37 | +8.22 | 11.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-11-26 | 420.29 | 424.72 | +2.95 | 23.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-11-29 | 425.02 | 425.70 | +7.41 | 19.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-11-30 | 419.74 | 420.02 | +4.63 | 20.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-12-01 | 424.23 | 420.62 | +7.23 | 17.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-12-02 | 416.79 | 415.88 | +5.15 | 18.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-12-03 | 415.68 | 420.23 | +8.89 | 17.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-12-06 | 420.42 | 418.61 | +6.58 | 15.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-12-07 | 431.66 | 424.56 | +10.06 | 17.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-12-08 | 427.16 | 430.83 | +9.99 | 19.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-12-09 | 429.72 | 429.33 | +7.02 | 17.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-12-10 | 427.29 | 427.56 | +7.07 | 15.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-12-13 | 426.59 | 430.41 | +8.70 | 14.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-12-14 | 422.70 | 428.45 | +6.95 | 13.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-12-15 | 422.85 | 424.89 | +6.36 | 14.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-12-16 | 428.41 | 430.87 | +9.84 | 16.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-12-17 | 425.42 | 425.58 | +5.29 | 17.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-12-20 | 415.89 | 417.59 | +4.43 | 23.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-12-21 | 423.07 | 420.91 | +8.21 | 20.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-12-22 | 427.20 | 425.62 | +8.61 | 19.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-12-23 | 431.91 | 428.85 | +8.09 | 18.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-12-24 | 431.57 | 430.00 | +7.58 | 16.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-12-27 | 434.45 | 430.69 | +7.39 | 14.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-12-28 | 436.80 | 436.02 | +8.74 | 15.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-12-29 | 434.91 | 437.46 | +7.65 | 14.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-12-30 | 437.04 | 436.15 | +6.70 | 13.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2021-12-31 | 434.98 | 435.43 | +6.78 | 12.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-01-03 | 435.99 | 435.54 | +7.05 | 11.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-01-04 | 437.96 | 439.12 | +8.27 | 11.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-01-05 | 436.60 | 437.44 | +6.59 | 11.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-01-06 | 429.91 | 430.11 | +4.70 | 18.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-01-07 | 426.77 | 428.90 | +6.58 | 16.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-01-10 | 420.92 | 428.07 | +6.68 | 14.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-01-11 | 426.14 | 426.33 | +6.27 | 13.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-01-12 | 428.35 | 429.80 | +7.85 | 13.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-01-13 | 427.07 | 426.41 | +5.46 | 13.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-01-14 | 421.10 | 421.53 | +4.98 | 16.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-01-17 | 424.55 | 422.97 | +6.88 | 14.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-01-18 | 419.90 | 421.98 | +5.91 | 13.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-01-19 | 418.14 | 416.81 | +4.52 | 15.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-01-20 | 421.56 | 417.15 | +6.42 | 14.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-01-21 | 411.83 | 412.44 | +4.48 | 15.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-01-24 | 395.13 | 407.88 | +4.40 | 17.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-01-25 | 399.55 | 401.17 | +3.29 | 21.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-01-26 | 407.55 | 403.74 | +6.43 | 18.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-01-27 | 409.74 | 400.45 | +4.32 | 17.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-01-28 | 405.31 | 405.73 | +7.36 | 18.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-01-31 | 413.27 | 410.56 | +7.07 | 18.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-02-01 | 416.32 | 414.75 | +7.03 | 18.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-02-02 | 417.49 | 419.01 | +7.11 | 18.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-02-03 | 409.62 | 417.08 | +5.14 | 16.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-02-04 | 405.07 | 410.28 | +3.50 | 20.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-02-07 | 408.07 | 408.83 | +5.23 | 18.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-02-08 | 409.99 | 408.89 | +5.61 | 15.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-02-09 | 415.63 | 412.67 | +6.84 | 15.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-02-10 | 413.08 | 416.78 | +6.90 | 16.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-02-11 | 410.51 | 410.51 | +3.53 | 18.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-02-14 | 406.28 | 405.81 | +4.18 | 19.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-02-15 | 409.82 | 405.79 | +5.45 | 17.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-02-16 | 408.01 | 409.43 | +6.61 | 16.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-02-17 | 406.25 | 409.73 | +5.65 | 14.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-02-18 | 401.26 | 404.81 | +4.08 | 16.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-02-21 | 396.90 | 402.45 | +4.68 | 15.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-02-22 | 398.09 | 394.15 | +2.67 | 22.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-02-23 | 395.56 | 398.85 | +6.61 | 20.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-02-24 | 390.42 | 384.26 | -0.95 | 34.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-02-25 | 402.69 | 395.32 | +10.35 | 35.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-02-28 | 404.66 | 401.05 | +6.82 | 33.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-03-01 | 402.21 | 405.99 | +6.93 | 30.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-03-02 | 406.31 | 400.99 | +3.19 | 27.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-03-03 | 405.84 | 408.21 | +8.16 | 27.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-03-04 | 401.97 | 404.81 | +3.68 | 23.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-03-07 | 400.00 | 398.89 | +2.96 | 24.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-03-08 | 391.44 | 392.78 | +2.62 | 25.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-03-09 | 397.35 | 394.72 | +5.79 | 21.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-03-10 | 394.46 | 398.39 | +6.18 | 20.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-03-11 | 398.59 | 398.42 | +4.69 | 17.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-03-14 | 394.43 | 398.01 | +4.55 | 15.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-03-15 | 398.11 | 390.04 | +1.42 | 22.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-03-16 | 405.80 | 403.80 | +10.61 | 33.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-03-17 | 407.35 | 408.24 | +6.13 | 30.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-03-18 | 413.77 | 409.93 | +5.50 | 26.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-03-21 | 416.69 | 415.24 | +7.02 | 24.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-03-22 | 421.01 | 418.91 | +6.48 | 22.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-03-23 | 420.22 | 421.79 | +6.31 | 20.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-03-24 | 419.98 | 420.42 | +4.84 | 17.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-03-25 | 422.34 | 421.75 | +5.87 | 15.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-03-28 | 423.53 | 424.33 | +6.28 | 14.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-03-29 | 426.36 | 426.93 | +6.32 | 13.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-03-30 | 424.70 | 426.87 | +5.46 | 12.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-03-31 | 423.98 | 424.27 | +4.50 | 12.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-04-01 | 422.68 | 422.54 | +4.71 | 12.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-04-04 | 427.55 | 424.32 | +5.88 | 11.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-04-05 | 429.04 | 429.27 | +6.99 | 14.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-04-06 | 420.80 | 427.11 | +4.46 | 13.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-04-07 | 419.43 | 421.64 | +3.45 | 16.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-04-08 | 425.48 | 425.76 | +6.75 | 16.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-04-11 | 419.20 | 422.64 | +4.08 | 15.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-04-12 | 421.27 | 415.98 | +3.20 | 19.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-04-13 | 419.08 | 419.27 | +6.29 | 17.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-04-14 | 421.95 | 419.51 | +5.33 | 15.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-04-19 | 422.12 | 420.00 | +5.58 | 13.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-04-20 | 422.66 | 421.38 | +5.91 | 12.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-04-21 | 422.99 | 421.98 | +5.75 | 11.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-04-22 | 412.63 | 417.11 | +4.09 | 14.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-04-25 | 405.82 | 405.11 | +1.71 | 28.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-04-26 | 406.01 | 411.62 | +7.34 | 26.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-04-27 | 409.47 | 405.89 | +2.87 | 25.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-04-28 | 412.01 | 412.83 | +7.80 | 25.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-04-29 | 412.66 | 415.87 | +6.13 | 22.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-05-02 | 404.16 | 406.62 | +1.98 | 27.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-05-03 | 410.08 | 407.66 | +5.60 | 23.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-05-04 | 404.77 | 409.61 | +5.81 | 20.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-05-05 | 405.57 | 415.36 | +7.17 | 20.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-05-06 | 399.94 | 404.78 | +1.48 | 27.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-05-09 | 389.55 | 398.62 | +3.34 | 28.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-05-10 | 387.01 | 390.83 | +2.34 | 30.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-05-11 | 391.75 | 390.00 | +4.69 | 25.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-05-12 | 388.41 | 383.51 | +2.36 | 26.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-05-13 | 397.27 | 392.00 | +8.41 | 28.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-05-16 | 395.78 | 396.15 | +6.14 | 26.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-05-17 | 398.28 | 397.75 | +5.34 | 22.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-05-18 | 392.40 | 399.40 | +5.42 | 19.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-05-19 | 384.64 | 387.81 | +0.24 | 30.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-05-20 | 383.99 | 386.86 | +4.28 | 26.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-05-23 | 388.35 | 388.71 | +5.10 | 22.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-05-24 | 379.52 | 382.76 | +2.13 | 23.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-05-25 | 386.44 | 386.18 | +5.67 | 20.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-05-26 | 392.02 | 387.46 | +4.63 | 18.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-05-27 | 399.58 | 392.81 | +6.30 | 19.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-05-30 | 402.28 | 403.80 | +8.10 | 29.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-05-31 | 396.24 | 400.68 | +3.25 | 25.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-06-01 | 397.94 | 400.93 | +4.68 | 21.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-06-02 | 398.91 | 398.85 | +3.84 | 19.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-06-03 | 397.70 | 402.31 | +5.94 | 18.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-06-06 | 401.15 | 400.29 | +3.94 | 16.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-06-07 | 399.89 | 398.13 | +3.92 | 15.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-06-08 | 400.56 | 401.61 | +5.87 | 15.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-06-09 | 396.83 | 397.87 | +3.04 | 15.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-06-10 | 384.93 | 392.31 | +2.48 | 18.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-06-13 | 375.49 | 379.74 | -0.33 | 33.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-06-14 | 372.66 | 377.50 | +3.08 | 29.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-06-15 | 375.52 | 372.14 | +1.42 | 27.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-06-16 | 364.69 | 374.51 | +4.51 | 24.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-06-17 | 364.61 | 364.70 | -0.94 | 30.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-06-20 | 366.40 | 364.37 | +3.40 | 26.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-06-21 | 370.51 | 367.88 | +4.53 | 23.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-06-22 | 369.81 | 366.78 | +2.61 | 20.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-06-23 | 370.52 | 367.38 | +3.44 | 18.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-06-24 | 379.15 | 373.32 | +5.55 | 20.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-06-27 | 380.60 | 382.00 | +6.49 | 26.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-06-28 | 380.55 | 382.33 | +3.63 | 23.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-06-29 | 377.26 | 375.98 | +1.46 | 24.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-06-30 | 373.44 | 373.26 | +2.73 | 22.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-07-01 | 375.25 | 369.96 | +2.21 | 21.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-07-04 | 377.25 | 376.97 | +5.78 | 23.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-07-05 | 376.12 | 379.15 | +3.86 | 21.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-07-06 | 384.76 | 383.16 | +4.85 | 20.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-07-07 | 392.33 | 387.58 | +4.98 | 20.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-07-08 | 394.33 | 392.38 | +5.25 | 20.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-07-11 | 392.08 | 391.11 | +3.38 | 18.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-07-12 | 393.03 | 391.48 | +4.10 | 16.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-07-13 | 386.83 | 391.32 | +4.04 | 14.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-07-14 | 383.70 | 388.07 | +3.18 | 14.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-07-15 | 390.71 | 386.46 | +4.03 | 14.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-07-18 | 392.44 | 392.85 | +6.67 | 17.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-07-19 | 392.81 | 388.58 | +2.76 | 17.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-07-20 | 398.21 | 395.74 | +7.24 | 20.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-07-21 | 399.33 | 397.66 | +4.94 | 18.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-07-22 | 398.90 | 400.09 | +5.56 | 17.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-07-25 | 398.93 | 398.46 | +3.97 | 15.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-07-26 | 398.17 | 398.12 | +4.71 | 14.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-07-27 | 402.37 | 400.15 | +5.49 | 13.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-07-28 | 407.71 | 403.46 | +5.74 | 13.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-07-29 | 411.23 | 409.56 | +6.80 | 17.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-08-01 | 412.20 | 412.51 | +5.75 | 16.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-08-02 | 412.39 | 410.07 | +3.89 | 15.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-08-03 | 416.49 | 411.99 | +5.64 | 14.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-08-04 | 414.94 | 416.50 | +6.73 | 15.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-08-05 | 414.08 | 415.56 | +4.74 | 14.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-08-08 | 417.00 | 417.59 | +5.98 | 13.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-08-09 | 412.50 | 415.62 | +4.38 | 12.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-08-10 | 416.20 | 411.98 | +3.66 | 13.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-08-11 | 418.90 | 419.26 | +7.59 | 18.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-08-12 | 422.70 | 418.84 | +4.57 | 16.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-08-15 | 427.54 | 425.26 | +7.42 | 18.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-08-16 | 429.61 | 429.53 | +6.34 | 18.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-08-17 | 425.84 | 430.65 | +5.39 | 16.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-08-18 | 429.19 | 425.93 | +3.34 | 17.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-08-19 | 426.63 | 428.75 | +6.24 | 15.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-08-22 | 424.02 | 426.09 | +3.90 | 15.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-08-23 | 421.20 | 422.96 | +3.78 | 15.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-08-24 | 422.79 | 421.07 | +4.18 | 14.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-08-25 | 424.56 | 424.89 | +6.27 | 14.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-08-26 | 418.73 | 427.29 | +5.56 | 13.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-08-29 | 411.41 | 413.34 | -0.25 | 29.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-08-30 | 407.11 | 412.67 | +4.75 | 25.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-08-31 | 403.58 | 408.63 | +2.81 | 23.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-09-01 | 400.98 | 400.50 | +1.37 | 26.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-09-02 | 406.62 | 403.29 | +5.36 | 23.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-09-05 | 403.99 | 404.38 | +4.48 | 21.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-09-06 | 403.70 | 403.03 | +3.64 | 18.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-09-07 | 401.96 | 400.42 | +3.15 | 17.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-09-08 | 407.73 | 405.00 | +5.81 | 17.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-09-09 | 410.77 | 405.97 | +4.25 | 16.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-09-12 | 413.66 | 408.71 | +5.41 | 15.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-09-13 | 406.45 | 414.58 | +6.83 | 17.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-09-14 | 403.30 | 404.32 | +0.57 | 25.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-09-15 | 400.98 | 404.97 | +5.12 | 21.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-09-16 | 393.44 | 396.27 | +0.42 | 25.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-09-19 | 394.61 | 394.08 | +3.79 | 23.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-09-20 | 394.10 | 397.75 | +5.79 | 21.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-09-21 | 398.68 | 395.08 | +2.76 | 19.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-09-22 | 390.16 | 390.50 | +2.12 | 20.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-09-23 | 385.60 | 389.80 | +3.65 | 18.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-09-26 | 386.48 | 385.89 | +1.98 | 18.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-09-27 | 386.39 | 388.00 | +4.76 | 16.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-09-28 | 387.67 | 384.98 | +2.20 | 16.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-09-29 | 378.19 | 386.14 | +4.33 | 14.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-09-30 | 380.84 | 379.26 | +0.29 | 18.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-10-03 | 380.66 | 374.32 | +1.53 | 20.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-10-04 | 388.17 | 384.47 | +7.85 | 26.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-10-05 | 387.58 | 387.16 | +4.12 | 24.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-10-06 | 390.57 | 390.10 | +4.68 | 22.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-10-07 | 382.61 | 389.04 | +2.96 | 19.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-10-10 | 380.81 | 381.04 | +0.26 | 24.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-10-11 | 378.38 | 377.28 | +2.06 | 23.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-10-12 | 377.08 | 378.24 | +3.69 | 20.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-10-13 | 377.63 | 375.45 | +1.82 | 19.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-10-14 | 378.59 | 384.72 | +7.05 | 24.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-10-17 | 382.35 | 379.33 | +0.27 | 23.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-10-18 | 383.50 | 385.57 | +6.32 | 23.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-10-19 | 384.81 | 385.99 | +2.95 | 21.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-10-20 | 385.46 | 383.35 | +1.95 | 19.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-10-21 | 383.76 | 381.02 | +2.07 | 18.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-10-24 | 388.18 | 387.90 | +6.26 | 20.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-10-25 | 392.04 | 390.76 | +4.09 | 19.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-10-26 | 392.62 | 390.04 | +2.80 | 18.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-10-27 | 391.53 | 389.25 | +2.87 | 16.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-10-28 | 394.56 | 386.82 | +2.10 | 16.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-10-31 | 397.14 | 396.72 | +7.77 | 21.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-11-01 | 398.28 | 399.82 | +4.37 | 20.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-11-02 | 395.76 | 398.64 | +2.98 | 18.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-11-03 | 391.52 | 392.18 | +0.74 | 20.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-11-04 | 388.14 | 390.91 | +2.92 | 19.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-11-07 | 389.82 | 388.43 | +2.00 | 18.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-11-08 | 393.56 | 390.06 | +3.85 | 17.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-11-09 | 389.17 | 391.72 | +3.71 | 16.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-11-10 | 397.96 | 386.88 | +0.94 | 16.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-11-11 | 396.93 | 400.80 | +10.03 | 25.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-11-14 | 398.36 | 398.78 | +1.98 | 23.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-11-15 | 400.64 | 397.06 | +2.93 | 21.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-11-16 | 395.12 | 398.62 | +4.22 | 20.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-11-17 | 393.39 | 396.48 | +2.36 | 19.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-11-18 | 396.23 | 394.07 | +2.42 | 18.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-11-21 | 397.61 | 397.79 | +5.05 | 17.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-11-22 | 400.46 | 398.12 | +3.39 | 16.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-11-23 | 401.66 | 400.91 | +4.57 | 16.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-11-24 | 402.30 | 401.50 | +3.51 | 15.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-11-25 | 401.79 | 401.91 | +3.53 | 14.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-11-28 | 398.78 | 399.85 | +2.46 | 13.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-11-29 | 396.31 | 398.82 | +2.94 | 12.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-11-30 | 398.85 | 398.31 | +3.04 | 12.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-12-01 | 402.63 | 406.39 | +6.67 | 16.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-12-02 | 401.19 | 401.68 | +0.89 | 16.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-12-05 | 397.69 | 400.00 | +2.71 | 15.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-12-06 | 392.28 | 396.59 | +1.71 | 15.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-12-07 | 389.79 | 392.58 | +1.51 | 16.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-12-08 | 390.71 | 390.24 | +2.08 | 15.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-12-09 | 392.60 | 392.05 | +3.82 | 15.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-12-12 | 391.15 | 390.13 | +2.00 | 14.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-12-13 | 396.70 | 393.88 | +4.65 | 14.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-12-14 | 396.03 | 394.85 | +3.23 | 13.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-12-15 | 382.18 | 390.27 | +0.76 | 14.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-12-16 | 379.27 | 382.08 | -0.77 | 18.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-12-19 | 377.61 | 379.76 | +1.76 | 17.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-12-20 | 376.29 | 373.99 | -0.29 | 19.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-12-21 | 382.91 | 378.20 | +4.42 | 18.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-12-22 | 377.12 | 382.72 | +4.02 | 19.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-12-23 | 377.76 | 377.89 | -0.07 | 19.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-12-27 | 378.15 | 381.38 | +3.95 | 18.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-12-28 | 376.07 | 378.97 | +0.93 | 17.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-12-29 | 378.99 | 374.54 | +0.23 | 17.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2022-12-30 | 375.19 | 377.48 | +3.47 | 17.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-01-02 | 383.75 | 385.28 | +5.13 | 19.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-01-03 | 380.01 | 381.83 | +0.72 | 19.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-01-04 | 383.49 | 381.05 | +2.24 | 18.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-01-05 | 381.18 | 381.42 | +2.46 | 16.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-01-06 | 384.86 | 381.66 | +2.53 | 15.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-01-09 | 387.15 | 385.07 | +3.69 | 15.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-01-10 | 382.92 | 382.80 | +1.65 | 14.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-01-11 | 386.85 | 384.89 | +3.33 | 14.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-01-12 | 387.70 | 388.88 | +3.85 | 14.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-01-13 | 388.78 | 388.11 | +1.87 | 13.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-01-16 | 390.84 | 390.60 | +3.30 | 13.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-01-17 | 391.90 | 390.12 | +2.12 | 12.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-01-18 | 389.60 | 391.53 | +2.80 | 12.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-01-19 | 383.95 | 386.94 | +0.39 | 13.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-01-20 | 386.80 | 384.83 | +1.40 | 13.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-01-23 | 392.68 | 387.67 | +3.07 | 13.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-01-24 | 391.72 | 392.10 | +3.59 | 14.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-01-25 | 388.71 | 391.22 | +1.74 | 13.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-01-26 | 393.32 | 392.23 | +2.53 | 12.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-01-27 | 396.75 | 394.50 | +2.94 | 12.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-01-30 | 394.93 | 394.66 | +2.31 | 12.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-01-31 | 394.63 | 393.99 | +2.43 | 11.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-02-01 | 393.93 | 395.84 | +3.43 | 11.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-02-02 | 403.47 | 397.22 | +3.56 | 11.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-02-03 | 405.81 | 401.45 | +4.74 | 12.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-02-06 | 403.61 | 402.30 | +4.59 | 11.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-02-07 | 404.46 | 403.58 | +4.64 | 11.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-02-08 | 403.79 | 406.92 | +5.15 | 11.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-02-09 | 404.51 | 406.50 | +4.22 | 11.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-02-10 | 402.25 | 400.92 | +2.24 | 13.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-02-13 | 405.17 | 402.56 | +5.50 | 13.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-02-14 | 403.23 | 405.66 | +7.03 | 13.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-02-15 | 406.83 | 403.86 | +4.45 | 12.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-02-16 | 406.70 | 408.83 | +8.47 | 13.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-02-17 | 401.82 | 403.14 | +5.75 | 15.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-02-20 | 402.19 | 402.73 | +6.44 | 14.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-02-21 | 398.51 | 401.77 | +8.03 | 13.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-02-22 | 398.38 | 397.81 | +9.36 | 14.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-02-23 | 398.28 | 399.56 | +7.29 | 13.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-02-24 | 396.07 | 400.42 | +7.48 | 12.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-02-27 | 398.14 | 399.11 | +9.58 | 12.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-02-28 | 397.06 | 396.58 | +5.61 | 12.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-03-01 | 392.76 | 396.69 | +8.35 | 12.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-03-02 | 394.72 | 391.58 | +0.72 | 13.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-03-03 | 401.16 | 397.71 | +13.54 | 15.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-03-06 | 402.78 | 402.68 | +8.05 | 16.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-03-07 | 400.39 | 401.45 | +6.36 | 15.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-03-08 | 399.48 | 400.02 | +6.36 | 14.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-03-09 | 399.92 | 400.00 | +6.50 | 13.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-03-10 | 391.28 | 390.00 | +2.88 | 19.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-03-13 | 381.81 | 387.24 | +5.82 | 19.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-03-14 | 387.55 | 382.90 | +2.81 | 18.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-03-15 | 384.32 | 385.85 | +12.77 | 17.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-03-16 | 389.30 | 387.42 | +9.41 | 16.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-03-17 | 386.23 | 391.55 | +3.73 | 16.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-03-20 | 386.00 | 384.57 | +12.01 | 18.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-03-21 | 389.63 | 388.88 | +5.25 | 18.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-03-22 | 390.27 | 390.45 | +3.61 | 17.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-03-23 | 387.22 | 384.94 | +10.41 | 17.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-03-24 | 386.12 | 386.30 | +7.54 | 17.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-03-27 | 389.20 | 390.61 | +1.96 | 17.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-03-28 | 387.16 | 389.97 | +3.91 | 16.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-03-29 | 391.18 | 390.50 | +3.55 | 15.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-03-30 | 393.05 | 393.39 | +0.80 | 15.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-03-31 | 397.34 | 394.17 | +0.90 | 14.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-04-03 | 398.57 | 400.23 | -4.83 | 15.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-04-04 | 396.21 | 399.73 | -1.68 | 15.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-04-05 | 395.23 | 396.29 | +3.33 | 14.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-04-06 | 395.59 | 396.03 | +5.23 | 14.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-04-11 | 398.27 | 399.41 | +6.35 | 14.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-04-12 | 396.65 | 398.11 | +4.65 | 13.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-04-13 | 395.95 | 396.43 | +4.60 | 13.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-04-14 | 398.74 | 397.64 | +5.14 | 12.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-04-17 | 400.68 | 400.25 | +5.41 | 12.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-04-18 | 401.21 | 402.32 | +4.76 | 12.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-04-19 | 400.61 | 400.84 | +3.89 | 11.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-04-20 | 399.43 | 400.52 | +5.04 | 11.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-04-21 | 399.35 | 399.91 | +4.50 | 10.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-04-24 | 397.69 | 398.37 | +4.00 | 10.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-04-25 | 396.91 | 396.74 | +3.83 | 10.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-04-26 | 392.95 | 395.01 | +3.88 | 10.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-04-27 | 394.94 | 392.72 | +3.59 | 11.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-04-28 | 398.59 | 397.32 | +6.54 | 12.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-05-02 | 394.73 | 400.92 | +5.39 | 12.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-05-03 | 395.10 | 396.49 | +3.96 | 13.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-05-04 | 392.24 | 392.86 | +3.88 | 14.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-05-05 | 397.43 | 393.22 | +3.98 | 13.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-05-08 | 399.08 | 397.83 | +4.43 | 13.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-05-09 | 400.35 | 399.48 | +2.01 | 12.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-05-10 | 399.62 | 399.80 | +2.23 | 12.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-05-11 | 400.76 | 402.64 | +4.31 | 12.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-05-12 | 402.15 | 402.06 | +1.44 | 12.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-05-15 | 403.29 | 403.89 | +0.47 | 11.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-05-16 | 402.71 | 402.76 | +3.91 | 11.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-05-17 | 403.73 | 401.86 | +3.50 | 11.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-05-18 | 409.46 | 406.25 | +5.39 | 12.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-05-19 | 409.29 | 410.91 | -2.35 | 12.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-05-22 | 410.80 | 409.72 | +4.22 | 12.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-05-23 | 409.86 | 409.61 | +5.03 | 12.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-05-24 | 403.39 | 405.68 | +2.41 | 12.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-05-25 | 405.22 | 405.81 | +4.54 | 12.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-05-26 | 410.83 | 406.57 | +4.50 | 11.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-05-29 | 412.36 | 412.43 | +6.79 | 13.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-05-30 | 410.20 | 412.70 | +4.09 | 12.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-05-31 | 407.88 | 409.46 | +2.86 | 13.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-06-01 | 408.12 | 409.97 | +4.95 | 12.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-06-02 | 417.46 | 412.00 | +5.26 | 12.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-06-05 | 418.70 | 418.71 | +6.09 | 14.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-06-06 | 419.21 | 417.40 | +4.29 | 13.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-06-07 | 418.45 | 419.21 | +5.42 | 13.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-06-08 | 416.24 | 416.70 | +3.87 | 12.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-06-09 | 418.32 | 417.08 | +4.75 | 12.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-06-12 | 419.49 | 419.95 | +5.17 | 12.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-06-13 | 423.37 | 421.34 | +4.79 | 11.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-06-14 | 423.40 | 423.58 | +5.18 | 11.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-06-15 | 421.95 | 422.40 | +4.31 | 11.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-06-16 | 423.83 | 422.82 | +4.80 | 11.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-06-19 | 421.31 | 422.18 | +4.70 | 10.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-06-20 | 419.36 | 420.55 | +4.40 | 10.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-06-21 | 417.26 | 419.37 | +6.53 | 10.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-06-22 | 416.35 | 414.46 | +4.11 | 12.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-06-23 | 415.81 | 415.93 | +7.04 | 11.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-06-26 | 414.91 | 415.55 | +6.59 | 11.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-06-27 | 414.42 | 414.71 | +6.88 | 10.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-06-28 | 418.51 | 416.84 | +4.53 | 10.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-06-29 | 420.05 | 418.59 | +3.48 | 10.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-06-30 | 423.63 | 421.46 | +1.89 | 10.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-07-03 | 424.61 | 425.49 | +0.22 | 11.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-07-04 | 425.23 | 425.01 | +2.07 | 10.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-07-05 | 424.96 | 424.13 | +3.61 | 10.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-07-06 | 417.90 | 422.83 | +5.08 | 10.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-07-07 | 417.80 | 418.12 | +8.40 | 11.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-07-10 | 416.21 | 415.03 | +9.60 | 12.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-07-11 | 417.91 | 416.86 | +7.16 | 11.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-07-12 | 419.85 | 418.87 | +5.15 | 11.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-07-13 | 420.00 | 419.84 | +4.45 | 11.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-07-14 | 419.96 | 420.11 | +4.48 | 10.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-07-17 | 419.40 | 418.19 | +5.93 | 10.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-07-18 | 421.86 | 419.01 | +5.02 | 10.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-07-19 | 425.60 | 424.12 | +1.28 | 11.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-07-20 | 425.76 | 423.42 | +2.71 | 11.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-07-21 | 426.19 | 425.08 | +2.11 | 10.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-07-24 | 428.03 | 424.64 | +3.15 | 10.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-07-25 | 430.14 | 428.63 | +0.94 | 10.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-07-26 | 428.55 | 430.10 | +1.07 | 10.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-07-27 | 434.76 | 430.49 | +1.91 | 10.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-07-28 | 433.39 | 432.32 | +1.63 | 10.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-07-31 | 433.30 | 433.01 | +2.13 | 9.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-08-01 | 433.32 | 434.96 | +4.73 | 9.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-08-02 | 428.63 | 429.67 | +6.15 | 10.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-08-03 | 426.36 | 427.33 | +7.37 | 10.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-08-04 | 425.74 | 427.55 | +6.47 | 10.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-08-07 | 424.95 | 425.39 | +7.50 | 10.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-08-08 | 424.01 | 425.16 | +6.84 | 10.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-08-09 | 423.71 | 427.21 | +4.38 | 10.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-08-10 | 425.61 | 424.66 | +3.20 | 10.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-08-11 | 422.83 | 423.85 | +3.83 | 10.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-08-14 | 425.31 | 423.66 | +3.96 | 9.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-08-15 | 422.28 | 425.87 | +5.80 | 9.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-08-16 | 421.69 | 421.17 | +1.21 | 10.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-08-17 | 418.95 | 420.17 | +5.01 | 10.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-08-18 | 415.57 | 416.49 | +2.37 | 11.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-08-21 | 415.88 | 416.36 | +4.83 | 10.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-08-22 | 419.83 | 417.87 | +4.58 | 10.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-08-23 | 422.53 | 420.31 | +5.05 | 10.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-08-24 | 420.70 | 426.04 | +6.03 | 11.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-08-25 | 420.82 | 420.29 | +4.33 | 12.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-08-28 | 424.20 | 422.64 | +6.24 | 12.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-08-29 | 427.73 | 425.56 | +4.89 | 12.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-08-30 | 427.60 | 428.54 | +5.94 | 12.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-08-31 | 430.82 | 429.31 | +4.45 | 11.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-09-01 | 432.80 | 430.68 | +5.53 | 11.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-09-04 | 432.96 | 434.16 | +6.00 | 11.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-09-05 | 434.50 | 432.56 | +3.39 | 11.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-09-06 | 430.96 | 432.50 | +5.20 | 10.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-09-07 | 430.10 | 430.05 | +3.55 | 10.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-09-08 | 431.12 | 430.58 | +5.25 | 10.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-09-11 | 430.88 | 431.36 | +4.60 | 10.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-09-12 | 431.16 | 432.42 | +5.02 | 10.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-09-13 | 431.05 | 429.95 | +3.40 | 10.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-09-14 | 436.46 | 432.00 | +5.86 | 10.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-09-15 | 434.67 | 439.02 | +6.19 | 11.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-09-18 | 432.62 | 434.42 | +4.43 | 11.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-09-19 | 430.71 | 432.55 | +4.34 | 11.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-09-20 | 431.88 | 431.97 | +3.62 | 11.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-09-21 | 424.99 | 429.11 | +3.37 | 11.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-09-22 | 424.81 | 423.33 | +2.41 | 12.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-09-25 | 424.75 | 423.41 | +4.97 | 12.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-09-26 | 421.42 | 423.51 | +3.41 | 11.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-09-27 | 422.47 | 421.92 | +3.76 | 11.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-09-28 | 422.93 | 423.19 | +4.80 | 11.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-09-29 | 423.77 | 423.44 | +4.10 | 11.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-10-02 | 423.67 | 423.38 | +4.36 | 10.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-10-03 | 417.94 | 423.17 | +4.18 | 10.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-10-04 | 416.94 | 415.61 | +1.65 | 12.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-10-05 | 416.76 | 418.90 | +6.91 | 12.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-10-06 | 419.23 | 418.34 | +3.06 | 12.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-10-09 | 422.10 | 420.30 | +6.36 | 11.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-10-10 | 427.87 | 425.46 | +5.91 | 12.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-10-11 | 426.18 | 426.44 | +4.63 | 12.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-10-12 | 429.45 | 429.14 | +4.64 | 12.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-10-13 | 426.89 | 428.30 | +1.92 | 11.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-10-16 | 428.77 | 426.63 | +3.70 | 11.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-10-17 | 427.69 | 428.27 | +2.65 | 11.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-10-18 | 425.47 | 426.44 | +4.25 | 11.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-10-19 | 420.80 | 422.14 | +7.28 | 11.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-10-20 | 413.24 | 416.35 | +10.47 | 12.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-10-23 | 411.75 | 413.08 | +11.00 | 12.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-10-24 | 414.21 | 410.59 | +3.14 | 12.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-10-25 | 412.31 | 413.04 | +3.22 | 12.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-10-26 | 409.03 | 407.97 | +3.05 | 13.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-10-27 | 405.38 | 408.14 | +3.16 | 12.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-10-30 | 405.86 | 407.32 | +3.12 | 12.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-10-31 | 409.76 | 406.11 | +3.01 | 12.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-11-01 | 414.12 | 411.01 | +3.15 | 12.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-11-02 | 420.29 | 415.98 | +3.23 | 13.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-11-03 | 422.35 | 421.40 | +3.42 | 13.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-11-06 | 421.22 | 421.95 | +2.79 | 13.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-11-07 | 423.82 | 421.21 | +3.45 | 13.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-11-08 | 422.35 | 422.79 | +3.43 | 12.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-11-09 | 424.29 | 423.27 | +3.53 | 12.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-11-10 | 423.27 | 422.70 | +3.51 | 12.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-11-13 | 425.86 | 424.78 | +3.57 | 11.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-11-14 | 428.88 | 426.02 | +3.53 | 11.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-11-15 | 430.05 | 429.23 | +3.65 | 11.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-11-16 | 427.81 | 429.64 | +3.11 | 11.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-11-17 | 429.37 | 430.74 | +4.26 | 11.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-11-20 | 429.58 | 428.51 | +2.51 | 11.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-11-21 | 429.89 | 430.09 | +4.74 | 11.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-11-22 | 433.53 | 430.76 | +3.34 | 11.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-11-23 | 433.03 | 432.67 | +3.71 | 10.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-11-24 | 432.22 | 432.52 | +3.65 | 10.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-11-27 | 431.76 | 431.24 | +3.41 | 10.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-11-28 | 430.83 | 430.68 | +3.68 | 10.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-11-29 | 431.37 | 430.49 | +3.72 | 10.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-11-30 | 432.99 | 432.57 | +4.41 | 10.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-12-01 | 438.07 | 435.37 | +3.78 | 10.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-12-04 | 437.29 | 438.04 | +3.80 | 10.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-12-05 | 439.49 | 437.38 | +3.68 | 9.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-12-06 | 440.33 | 441.20 | +5.53 | 10.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-12-07 | 440.66 | 439.45 | +3.85 | 10.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-12-08 | 443.27 | 441.20 | +5.14 | 9.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-12-11 | 445.15 | 444.27 | +4.32 | 9.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-12-12 | 444.87 | 445.73 | +4.36 | 9.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-12-13 | 446.76 | 446.87 | +4.10 | 9.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-12-14 | 446.57 | 450.67 | +4.97 | 9.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-12-15 | 449.70 | 448.12 | +2.13 | 10.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-12-18 | 449.78 | 449.17 | +4.89 | 9.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-12-19 | 450.26 | 450.46 | +3.60 | 9.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-12-20 | 451.81 | 451.58 | +4.24 | 9.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-12-21 | 448.19 | 448.79 | +2.33 | 9.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-12-22 | 449.72 | 448.52 | +4.35 | 9.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-12-27 | 448.33 | 450.31 | +4.03 | 9.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-12-28 | 450.13 | 449.94 | +3.42 | 8.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2023-12-29 | 448.84 | 451.18 | +4.07 | 8.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-01-02 | 451.01 | 452.22 | +3.77 | 8.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-01-03 | 449.04 | 450.74 | +3.18 | 8.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-01-04 | 448.80 | 448.85 | +3.64 | 8.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-01-05 | 447.83 | 446.85 | +3.61 | 8.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-01-08 | 448.72 | 447.28 | +3.93 | 8.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-01-09 | 452.00 | 451.68 | +4.08 | 8.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-01-10 | 452.09 | 452.39 | +4.07 | 8.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-01-11 | 450.25 | 454.73 | +4.84 | 8.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-01-12 | 453.65 | 452.45 | +3.60 | 8.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-01-15 | 453.83 | 454.28 | +3.73 | 8.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-01-16 | 454.94 | 452.00 | +3.46 | 8.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-01-17 | 451.87 | 451.13 | +3.42 | 8.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-01-18 | 453.79 | 450.98 | +3.15 | 8.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-01-19 | 455.44 | 455.53 | +3.58 | 8.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-01-22 | 460.55 | 459.77 | +3.72 | 9.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-01-23 | 461.10 | 460.13 | +3.70 | 9.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-01-24 | 463.46 | 463.40 | +3.68 | 9.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-01-25 | 465.71 | 462.09 | +2.57 | 9.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-01-26 | 466.03 | 465.09 | +5.13 | 9.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-01-29 | 468.08 | 466.58 | +3.46 | 9.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-01-30 | 469.16 | 469.77 | +5.20 | 9.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-01-31 | 466.39 | 469.54 | +3.30 | 9.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-02-01 | 464.23 | 466.12 | +3.90 | 9.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-02-02 | 472.01 | 468.45 | +4.09 | 9.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-02-05 | 472.52 | 472.36 | +1.48 | 9.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-02-06 | 473.77 | 473.74 | +4.44 | 9.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-02-07 | 475.79 | 473.86 | +4.23 | 9.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-02-08 | 475.87 | 476.38 | +4.18 | 9.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-02-09 | 476.64 | 476.56 | +4.19 | 9.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-02-12 | 480.52 | 477.87 | +4.88 | 8.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-02-13 | 475.72 | 479.11 | +4.56 | 8.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-02-14 | 476.61 | 476.18 | +3.46 | 8.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-02-15 | 479.06 | 479.86 | +5.61 | 9.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-02-16 | 480.99 | 481.73 | +4.25 | 8.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-02-19 | 479.99 | 479.04 | +3.45 | 8.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-02-20 | 475.32 | 478.89 | +4.27 | 8.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-02-21 | 474.77 | 475.43 | +2.80 | 8.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-02-22 | 482.96 | 479.43 | +3.91 | 9.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-02-23 | 484.61 | 483.96 | +4.32 | 9.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-02-26 | 482.89 | 483.65 | +4.03 | 9.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-02-27 | 482.20 | 482.24 | +4.08 | 9.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-02-28 | 482.50 | 483.19 | +4.16 | 9.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-02-29 | 483.56 | 482.25 | +4.07 | 8.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-03-01 | 487.10 | 486.53 | +5.52 | 9.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-03-04 | 486.97 | 487.50 | +4.25 | 9.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-03-05 | 483.56 | 486.49 | +4.08 | 9.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-03-06 | 485.09 | 484.00 | +3.28 | 9.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-03-07 | 487.16 | 483.62 | +4.07 | 9.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-03-08 | 487.35 | 488.41 | +4.04 | 9.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-03-11 | 484.22 | 483.91 | +1.93 | 9.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-03-12 | 488.23 | 486.25 | +5.24 | 9.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-03-13 | 488.37 | 489.32 | +3.87 | 9.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-03-14 | 488.48 | 489.82 | +3.81 | 9.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-03-15 | 485.49 | 488.90 | +3.77 | 9.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-03-18 | 489.80 | 487.65 | +3.70 | 9.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-03-19 | 490.82 | 489.50 | +3.74 | 9.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-03-20 | 491.86 | 491.34 | +3.81 | 8.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-03-21 | 498.91 | 496.39 | +3.96 | 9.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-03-22 | 498.76 | 499.06 | +3.94 | 9.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-03-25 | 497.05 | 498.26 | +3.87 | 9.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-03-26 | 498.27 | 497.41 | +3.84 | 9.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-03-27 | 497.83 | 497.97 | +4.08 | 8.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-03-28 | 501.00 | 500.77 | +4.64 | 8.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-04-02 | 496.87 | 502.60 | +4.16 | 8.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-04-03 | 497.37 | 497.39 | +3.95 | 9.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-04-04 | 497.81 | 497.19 | +4.54 | 9.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-04-05 | 494.22 | 491.54 | +3.72 | 10.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-04-08 | 495.40 | 494.60 | +5.67 | 10.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-04-09 | 492.47 | 495.25 | +3.07 | 9.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-04-10 | 494.97 | 496.11 | +4.52 | 9.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-04-11 | 495.50 | 495.91 | +3.42 | 9.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-04-12 | 498.14 | 500.87 | +4.07 | 9.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-04-15 | 496.93 | 497.85 | +2.13 | 9.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-04-16 | 489.20 | 489.78 | +3.65 | 11.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-04-17 | 486.37 | 488.24 | +3.62 | 11.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-04-18 | 487.57 | 486.52 | +3.75 | 11.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-04-19 | 483.15 | 482.50 | +3.71 | 11.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-04-22 | 483.89 | 484.04 | +3.99 | 11.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-04-23 | 489.26 | 487.08 | +3.87 | 10.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-04-24 | 489.57 | 491.75 | +3.92 | 11.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-04-25 | 483.50 | 486.74 | +3.73 | 11.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-04-26 | 492.37 | 489.76 | +5.56 | 11.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-04-29 | 492.11 | 493.15 | +4.23 | 11.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-04-30 | 490.90 | 493.41 | +3.95 | 11.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-05-02 | 486.30 | 487.35 | +3.74 | 11.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-05-03 | 491.23 | 489.56 | +3.79 | 11.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-05-06 | 494.79 | 493.40 | +4.23 | 11.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-05-07 | 498.43 | 497.57 | +4.02 | 11.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-05-08 | 498.45 | 498.93 | +3.96 | 11.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-05-09 | 499.40 | 498.49 | +3.86 | 11.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-05-10 | 501.09 | 501.29 | +4.06 | 11.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-05-13 | 500.35 | 501.73 | +4.04 | 11.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-05-14 | 500.03 | 500.65 | +3.81 | 10.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-05-15 | 503.55 | 501.67 | +4.24 | 10.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-05-16 | 505.86 | 505.60 | +4.74 | 10.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-05-17 | 504.15 | 504.48 | +3.36 | 10.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-05-20 | 507.00 | 505.24 | +4.45 | 10.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-05-21 | 505.96 | 505.44 | +3.82 | 10.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-05-22 | 506.12 | 505.87 | +4.00 | 9.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-05-23 | 506.23 | 508.10 | +4.31 | 9.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-05-24 | 504.47 | 502.85 | +3.75 | 10.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-05-27 | 505.62 | 504.67 | +3.86 | 9.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-05-28 | 503.44 | 505.19 | +3.85 | 9.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-05-29 | 501.66 | 502.60 | +3.66 | 9.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-05-30 | 500.18 | 500.09 | +3.80 | 9.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-05-31 | 497.00 | 499.71 | +3.61 | 9.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-06-03 | 500.55 | 504.27 | +3.69 | 9.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-06-04 | 499.63 | 500.37 | +2.32 | 9.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-06-05 | 505.37 | 502.64 | +3.62 | 9.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-06-06 | 507.38 | 507.56 | +3.72 | 10.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-06-07 | 510.08 | 507.81 | +3.69 | 9.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-06-10 | 512.14 | 510.11 | +3.72 | 9.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-06-11 | 511.34 | 511.77 | +3.72 | 9.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-06-12 | 513.98 | 512.90 | +3.70 | 9.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-06-13 | 514.05 | 514.67 | +3.72 | 9.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-06-14 | 515.54 | 516.41 | +3.77 | 9.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-06-17 | 515.31 | 516.60 | +3.63 | 9.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-06-18 | 518.34 | 518.29 | +3.80 | 8.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-06-19 | 519.13 | 519.78 | +3.89 | 8.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-06-20 | 521.32 | 520.77 | +3.81 | 8.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-06-21 | 519.28 | 519.75 | +3.74 | 8.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-06-24 | 520.15 | 519.02 | +3.70 | 8.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-06-25 | 519.90 | 518.31 | +3.56 | 8.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-06-26 | 519.98 | 521.85 | +4.57 | 8.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-06-27 | 519.67 | 520.52 | +3.25 | 8.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-06-28 | 521.62 | 522.60 | +4.81 | 8.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-07-01 | 518.64 | 519.07 | +2.65 | 8.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-07-02 | 519.46 | 518.15 | +4.01 | 8.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-07-03 | 521.09 | 521.35 | +3.73 | 8.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-07-04 | 522.27 | 522.89 | +3.73 | 8.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-07-05 | 522.52 | 522.85 | +3.72 | 7.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-07-08 | 523.43 | 522.72 | +3.72 | 7.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-07-09 | 524.06 | 524.38 | +4.11 | 7.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-07-10 | 526.27 | 524.27 | +3.89 | 7.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-07-11 | 525.44 | 528.64 | +4.73 | 7.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-07-12 | 527.95 | 525.74 | +2.87 | 7.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-07-15 | 527.99 | 527.89 | +4.66 | 7.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-07-16 | 528.66 | 526.94 | +3.20 | 7.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-07-17 | 523.14 | 527.26 | +4.03 | 7.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-07-18 | 520.00 | 524.09 | +2.77 | 7.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-07-19 | 517.14 | 520.00 | +2.97 | 8.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-07-22 | 519.27 | 518.14 | +3.19 | 8.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-07-23 | 524.16 | 520.85 | +3.45 | 8.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-07-24 | 515.06 | 519.04 | +3.35 | 8.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-07-25 | 512.44 | 512.18 | +3.24 | 9.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-07-26 | 513.30 | 511.33 | +3.24 | 8.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-07-29 | 514.43 | 516.79 | +3.36 | 9.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-07-30 | 514.74 | 516.09 | +3.52 | 9.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-07-31 | 522.54 | 519.46 | +3.57 | 9.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-08-01 | 517.22 | 523.00 | +3.52 | 9.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-08-02 | 496.61 | 509.50 | +3.02 | 12.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-08-05 | 485.47 | 484.08 | +2.40 | 24.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-08-06 | 489.76 | 489.57 | +2.61 | 24.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-08-07 | 496.77 | 492.41 | +7.53 | 22.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-08-08 | 496.49 | 487.49 | +7.38 | 22.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-08-09 | 498.75 | 497.63 | +3.44 | 23.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-08-12 | 499.47 | 500.61 | +2.57 | 22.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-08-13 | 504.48 | 502.06 | +2.47 | 21.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-08-14 | 505.70 | 505.67 | +5.37 | 21.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-08-15 | 514.47 | 507.50 | +4.80 | 20.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-08-16 | 515.18 | 517.03 | +3.20 | 21.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-08-19 | 516.53 | 514.56 | +2.87 | 20.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-08-20 | 515.33 | 518.22 | +3.36 | 20.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-08-21 | 515.88 | 515.76 | +3.24 | 19.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-08-22 | 516.93 | 516.86 | +3.27 | 18.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-08-23 | 516.96 | 516.04 | +3.31 | 18.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-08-26 | 516.77 | 517.16 | +3.37 | 18.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-08-27 | 516.89 | 517.45 | +3.32 | 17.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-08-28 | 516.95 | 518.80 | +3.31 | 16.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-08-29 | 523.04 | 517.47 | +3.52 | 16.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-08-30 | 521.02 | 521.43 | +3.64 | 16.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-09-02 | 524.20 | 523.56 | +3.66 | 15.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-09-03 | 519.02 | 524.83 | +3.58 | 15.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-09-04 | 512.73 | 511.69 | +3.20 | 17.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-09-05 | 509.46 | 511.37 | +3.11 | 17.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-09-06 | 502.54 | 507.60 | +3.12 | 17.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-09-09 | 508.67 | 506.09 | +3.25 | 16.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-09-10 | 509.54 | 508.09 | +3.18 | 16.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-09-11 | 507.14 | 509.45 | +3.51 | 15.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-09-12 | 516.61 | 518.15 | +3.64 | 16.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-09-13 | 520.37 | 518.30 | +3.71 | 16.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-09-16 | 518.10 | 518.71 | +3.67 | 15.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-09-17 | 521.13 | 519.84 | +3.50 | 15.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-09-18 | 518.63 | 520.16 | +3.42 | 15.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-09-19 | 525.76 | 523.22 | +3.60 | 14.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-09-20 | 522.58 | 524.01 | +3.74 | 14.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-09-23 | 526.03 | 523.71 | +3.67 | 14.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-09-24 | 525.81 | 527.88 | +3.66 | 14.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-09-25 | 526.13 | 523.38 | +3.38 | 14.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-09-26 | 527.29 | 530.00 | +3.51 | 14.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-09-27 | 529.33 | 529.43 | +3.46 | 13.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-09-30 | 528.02 | 527.92 | +3.37 | 13.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-10-01 | 529.18 | 530.74 | +3.44 | 13.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-10-02 | 531.22 | 529.06 | +3.33 | 13.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-10-03 | 529.87 | 529.80 | +3.34 | 13.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-10-04 | 533.28 | 529.17 | +3.20 | 12.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-10-07 | 534.82 | 535.49 | +3.37 | 12.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-10-08 | 534.63 | 529.97 | +3.26 | 12.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-10-09 | 537.91 | 534.27 | +3.45 | 12.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-10-10 | 539.43 | 539.38 | +3.36 | 12.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-10-11 | 541.46 | 538.53 | +3.37 | 12.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-10-14 | 545.74 | 542.36 | +3.40 | 12.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-10-15 | 544.15 | 547.76 | +3.41 | 12.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-10-16 | 544.19 | 543.22 | +3.27 | 12.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-10-17 | 549.26 | 547.12 | +3.35 | 12.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-10-18 | 548.29 | 548.08 | +3.40 | 12.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-10-21 | 546.55 | 548.61 | +3.40 | 12.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-10-22 | 547.09 | 547.31 | +3.35 | 11.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-10-23 | 545.07 | 548.43 | +3.34 | 11.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-10-24 | 544.43 | 546.24 | +3.19 | 11.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-10-25 | 546.30 | 544.25 | +3.07 | 11.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-10-28 | 545.96 | 546.95 | +3.06 | 11.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-10-29 | 546.47 | 546.72 | +3.08 | 11.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-10-30 | 543.65 | 546.39 | +3.03 | 11.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-10-31 | 534.42 | 538.33 | +2.79 | 11.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-11-01 | 538.40 | 533.85 | +2.80 | 11.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-11-04 | 533.80 | 534.84 | +2.81 | 11.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-11-05 | 536.46 | 534.09 | +2.71 | 10.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-11-06 | 553.01 | 553.67 | +3.53 | 12.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-11-07 | 556.53 | 555.18 | +3.51 | 12.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-11-08 | 560.52 | 558.60 | +3.77 | 12.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-11-11 | 566.61 | 564.47 | +3.89 | 12.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-11-12 | 564.78 | 565.64 | +4.07 | 12.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-11-13 | 566.69 | 563.30 | +3.88 | 12.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-11-14 | 566.34 | 566.86 | +4.01 | 12.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-11-15 | 559.35 | 561.94 | +3.70 | 12.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-11-18 | 560.71 | 559.16 | +3.45 | 12.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-11-19 | 560.09 | 560.83 | +3.53 | 12.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-11-20 | 560.66 | 562.58 | +3.63 | 12.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-11-21 | 568.08 | 562.67 | +3.54 | 12.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-11-22 | 574.33 | 569.08 | +3.76 | 12.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-11-25 | 573.38 | 575.59 | +4.01 | 12.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-11-26 | 573.95 | 572.03 | +3.75 | 12.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-11-27 | 569.07 | 573.38 | +3.94 | 12.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-11-28 | 571.92 | 572.10 | +4.16 | 12.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-11-29 | 574.01 | 571.00 | +4.03 | 12.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-12-02 | 578.81 | 575.77 | +4.00 | 13.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-12-03 | 578.41 | 579.03 | +3.97 | 13.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-12-04 | 580.20 | 579.69 | +3.95 | 12.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-12-05 | 579.68 | 580.59 | +3.95 | 12.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-12-06 | 579.87 | 577.90 | +3.72 | 12.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-12-09 | 578.00 | 580.94 | +3.75 | 12.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-12-10 | 578.96 | 577.54 | +3.71 | 12.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-12-11 | 582.35 | 578.17 | +3.75 | 12.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-12-12 | 581.33 | 581.18 | +3.82 | 12.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-12-13 | 578.19 | 581.36 | +3.71 | 11.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-12-16 | 579.18 | 577.64 | +3.68 | 11.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-12-17 | 577.58 | 577.66 | +3.90 | 11.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-12-18 | 578.75 | 578.10 | +3.95 | 11.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-12-19 | 569.49 | 568.11 | +3.74 | 11.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-12-20 | 570.29 | 564.06 | +3.70 | 11.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-12-23 | 569.57 | 570.88 | +3.76 | 11.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-12-24 | 574.28 | 573.91 | +3.93 | 11.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-12-27 | 572.50 | 575.94 | +4.13 | 11.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-12-30 | 570.06 | 570.91 | +3.97 | 11.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2024-12-31 | 570.45 | 567.84 | +3.93 | 11.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-01-02 | 576.46 | 571.86 | +4.18 | 11.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-01-03 | 575.33 | 573.38 | +4.21 | 11.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-01-06 | 579.09 | 576.22 | +4.43 | 11.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-01-07 | 574.80 | 574.70 | +4.54 | 11.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-01-08 | 575.18 | 574.92 | +4.76 | 10.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-01-09 | 575.26 | 574.00 | +2.86 | 10.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-01-10 | 569.98 | 574.50 | +4.77 | 10.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-01-13 | 569.04 | 569.11 | +4.56 | 10.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-01-14 | 568.28 | 572.43 | +3.63 | 10.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-01-15 | 577.60 | 568.61 | +4.77 | 10.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-01-16 | 579.05 | 580.99 | +1.25 | 11.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-01-17 | 584.05 | 580.04 | +1.71 | 11.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-01-20 | 581.18 | 583.45 | +4.67 | 11.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-01-21 | 581.60 | 581.09 | +4.64 | 11.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-01-22 | 586.63 | 584.79 | +4.74 | 11.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-01-23 | 587.63 | 585.98 | +4.64 | 11.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-01-24 | 584.92 | 586.80 | +4.53 | 11.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-01-27 | 575.48 | 577.47 | +4.47 | 11.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-01-28 | 582.85 | 581.23 | +5.62 | 11.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-01-29 | 584.73 | 586.81 | +4.90 | 11.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-01-30 | 586.22 | 586.87 | +4.76 | 11.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-01-31 | 592.14 | 590.65 | +5.37 | 11.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-02-03 | 586.88 | 584.79 | +4.83 | 11.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-02-04 | 586.74 | 585.00 | +4.95 | 11.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-02-05 | 584.88 | 583.31 | +3.31 | 11.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-02-06 | 591.68 | 590.00 | +1.50 | 11.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-02-07 | 590.67 | 591.17 | +5.70 | 11.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-02-10 | 593.81 | 592.04 | +1.55 | 11.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-02-11 | 592.31 | 592.80 | +1.51 | 11.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-02-12 | 588.39 | 591.19 | +2.09 | 10.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-02-13 | 591.41 | 589.12 | +5.09 | 11.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-02-14 | 590.03 | 592.47 | +4.93 | 11.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-02-17 | 593.16 | 592.05 | +5.03 | 11.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-02-18 | 593.40 | 594.49 | +1.97 | 10.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-02-19 | 595.37 | 595.14 | +5.50 | 10.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-02-20 | 589.40 | 594.18 | +2.41 | 10.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-02-21 | 590.06 | 590.35 | +5.20 | 10.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-02-24 | 583.19 | 584.66 | +5.07 | 10.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-02-25 | 574.60 | 580.87 | +5.00 | 10.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-02-26 | 582.23 | 580.04 | +5.25 | 10.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-02-27 | 583.14 | 581.64 | +4.83 | 10.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-02-28 | 576.57 | 575.39 | +4.54 | 10.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-03-03 | 578.19 | 584.06 | +4.68 | 11.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-03-04 | 559.33 | 570.96 | +4.20 | 11.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-03-05 | 551.27 | 560.08 | +3.84 | 11.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-03-06 | 552.67 | 555.72 | +3.65 | 12.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-03-07 | 542.16 | 548.00 | +3.51 | 12.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-03-10 | 538.31 | 546.54 | +3.43 | 12.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-03-11 | 526.86 | 533.96 | +3.04 | 12.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-03-12 | 532.62 | 529.94 | +2.86 | 12.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-03-13 | 528.73 | 530.60 | +2.88 | 12.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-03-14 | 534.81 | 530.37 | +2.95 | 13.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-03-17 | 537.10 | 534.80 | +3.12 | 12.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-03-18 | 534.88 | 537.88 | +3.14 | 13.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-03-19 | 540.73 | 535.43 | +2.92 | 12.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-03-20 | 542.29 | 543.66 | +3.19 | 13.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-03-21 | 540.91 | 541.41 | +3.31 | 13.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-03-24 | 550.55 | 546.15 | +3.29 | 13.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-03-25 | 551.28 | 551.00 | +3.51 | 13.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-03-26 | 548.69 | 553.05 | +3.77 | 13.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-03-27 | 546.60 | 547.35 | +3.52 | 13.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-03-28 | 534.84 | 543.17 | +3.41 | 13.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-03-31 | 530.82 | 529.08 | +2.33 | 14.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-04-01 | 538.11 | 535.93 | +3.18 | 14.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-04-02 | 537.57 | 537.46 | +3.25 | 14.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-04-03 | 511.15 | 518.13 | +2.87 | 19.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-04-04 | 487.88 | 504.05 | +2.82 | 22.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-04-07 | 472.93 | 454.04 | -42.74 | 50.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-04-08 | 489.46 | 482.92 | +18.18 | 64.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-04-09 | 466.43 | 468.56 | -29.74 | 59.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,000.00 |
| 2025-04-10 | 484.89 | 510.77 | +148.65 | 69.6% | 0 | 1 | 17.3% | 17.3% | 0.0% | 100,000.00 |
| 2025-04-11 | 479.93 | 485.72 | -183.92 | 63.6% | 0 | 0 | 0.0% | 0.0% | 16.8% | 99,780.24 |
| 2025-04-14 | 493.72 | 491.92 | +124.95 | 58.1% | 0 | 1 | 20.6% | 20.6% | 0.0% | 100,182.62 |
| 2025-04-15 | 498.57 | 496.02 | -45.99 | 54.5% | 0 | 0 | 0.0% | 0.0% | 20.4% | 100,266.88 |
| 2025-04-16 | 492.79 | 489.69 | +9.05 | 50.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 99,882.89 |
| 2025-04-17 | 487.94 | 489.97 | +0.39 | 42.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 99,882.89 |
| 2025-04-22 | 484.14 | 478.83 | -19.94 | 41.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 99,882.89 |
| 2025-04-23 | 498.72 | 495.83 | +49.36 | 42.5% | 0 | 1 | 28.2% | 28.2% | 0.0% | 99,882.89 |
| 2025-04-24 | 502.31 | 495.74 | -19.82 | 37.3% | 0 | 0 | 0.0% | 0.0% | 28.1% | 100,223.00 |
| 2025-04-25 | 505.10 | 508.44 | +41.13 | 36.2% | 0 | 1 | 33.1% | 33.1% | 0.0% | 100,537.71 |
| 2025-04-28 | 506.32 | 508.92 | -14.90 | 31.5% | 0 | 0 | 0.0% | 0.0% | 32.8% | 100,335.79 |
| 2025-04-29 | 508.33 | 509.18 | +12.53 | 26.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,488.45 |
| 2025-04-30 | 510.17 | 511.23 | +2.49 | 22.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,488.45 |
| 2025-05-02 | 522.72 | 520.00 | +20.96 | 23.2% | 0 | 1 | 51.6% | 51.6% | 0.0% | 100,488.45 |
| 2025-05-05 | 523.60 | 521.89 | -1.74 | 20.4% | 0 | 0 | 0.0% | 0.0% | 51.5% | 100,605.97 |
| 2025-05-06 | 520.83 | 521.77 | +6.16 | 17.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,372.57 |
| 2025-05-07 | 518.30 | 519.69 | -1.78 | 15.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,372.57 |
| 2025-05-08 | 526.60 | 525.34 | +17.79 | 15.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,372.57 |
| 2025-05-09 | 526.26 | 527.31 | +0.51 | 14.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,372.57 |
| 2025-05-12 | 543.51 | 540.09 | +30.50 | 20.2% | 0 | 1 | 59.5% | 59.5% | 0.0% | 100,372.57 |
| 2025-05-13 | 547.17 | 544.09 | -2.13 | 19.4% | 0 | 0 | 0.0% | 0.0% | 59.3% | 100,648.57 |
| 2025-05-14 | 545.69 | 546.26 | +10.97 | 17.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-05-15 | 547.75 | 543.65 | -4.94 | 16.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-05-16 | 551.59 | 547.90 | +16.46 | 15.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-05-19 | 548.41 | 546.14 | -6.01 | 13.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-05-20 | 549.82 | 548.69 | +13.83 | 12.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-05-21 | 545.61 | 544.69 | -9.16 | 12.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-05-22 | 541.09 | 541.01 | +3.42 | 13.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-05-23 | 535.21 | 540.22 | +2.34 | 12.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-05-26 | 540.15 | 538.99 | +2.05 | 11.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-05-27 | 544.20 | 540.91 | +8.72 | 11.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-05-28 | 545.29 | 545.77 | +11.54 | 12.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-05-29 | 542.49 | 551.54 | +12.28 | 13.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-05-30 | 543.03 | 543.40 | -14.92 | 15.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-06-02 | 539.98 | 540.00 | +7.75 | 15.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-06-03 | 546.54 | 542.20 | +7.52 | 14.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-06-04 | 546.86 | 547.56 | +14.07 | 14.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-06-05 | 547.43 | 546.70 | -1.41 | 13.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-06-06 | 549.23 | 546.11 | +6.97 | 12.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-06-09 | 548.99 | 548.75 | +8.96 | 12.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-06-10 | 549.27 | 549.94 | +4.97 | 11.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-06-11 | 548.98 | 550.59 | +5.65 | 11.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-06-12 | 544.25 | 545.26 | -6.83 | 12.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-06-13 | 542.39 | 539.53 | -1.41 | 14.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-06-16 | 544.19 | 541.90 | +12.35 | 13.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-06-17 | 542.91 | 541.67 | +0.33 | 12.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-06-18 | 542.88 | 542.71 | +8.70 | 11.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-06-19 | 538.18 | 541.51 | -0.16 | 11.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-06-20 | 539.80 | 539.56 | +2.50 | 11.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-06-23 | 538.75 | 537.97 | +1.59 | 11.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-06-24 | 543.79 | 544.71 | +18.90 | 12.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-06-25 | 543.04 | 545.45 | -1.79 | 12.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-06-26 | 543.26 | 542.56 | +1.07 | 12.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-06-27 | 547.86 | 545.76 | +11.98 | 12.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-06-30 | 546.77 | 548.41 | +5.64 | 11.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-07-01 | 545.72 | 547.10 | +0.91 | 11.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-07-02 | 547.21 | 548.02 | +7.55 | 11.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-07-03 | 552.81 | 548.47 | +3.38 | 10.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-07-04 | 549.17 | 550.28 | +8.01 | 10.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-07-07 | 550.96 | 550.19 | +1.84 | 10.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-07-08 | 551.21 | 550.09 | +4.77 | 10.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-07-09 | 552.74 | 550.69 | +4.72 | 10.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-07-10 | 556.65 | 552.54 | +7.28 | 10.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-07-11 | 553.24 | 555.14 | +7.49 | 10.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-07-14 | 553.92 | 551.83 | -4.42 | 10.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-07-15 | 556.95 | 556.55 | +17.23 | 11.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-07-16 | 549.19 | 553.13 | -9.87 | 11.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,489.96 |
| 2025-07-17 | 559.83 | 558.67 | +21.58 | 11.9% | 0 | 1 | 100.0% | 100.0% | 0.0% | 100,489.96 |
| 2025-07-18 | 558.34 | 560.77 | -0.84 | 11.8% | 0 | 0 | 0.0% | 0.0% | 100.0% | 99,955.34 |
| 2025-07-21 | 558.89 | 559.72 | +3.83 | 11.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,102.20 |
| 2025-07-22 | 555.14 | 557.15 | -1.62 | 11.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,102.20 |
| 2025-07-23 | 559.76 | 558.51 | +8.86 | 10.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,102.20 |
| 2025-07-24 | 560.99 | 561.34 | +6.69 | 11.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,102.20 |
| 2025-07-25 | 562.08 | 560.96 | +1.53 | 10.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,102.20 |
| 2025-07-28 | 566.78 | 566.01 | +14.67 | 11.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,102.20 |
| 2025-07-29 | 569.06 | 570.65 | +7.32 | 12.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,102.20 |
| 2025-07-30 | 571.81 | 568.94 | -1.52 | 11.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 100,102.20 |
| 2025-07-31 | 573.04 | 576.37 | +20.56 | 13.4% | 0 | 1 | 89.5% | 89.5% | 0.0% | 100,102.20 |
| 2025-08-01 | 556.13 | 568.04 | -21.39 | 14.6% | 0 | 0 | 0.0% | 0.0% | 88.4% | 98,156.54 |
| 2025-08-04 | 562.60 | 557.91 | -4.44 | 19.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,347.12 |
| 2025-08-05 | 561.40 | 566.23 | +23.45 | 18.9% | 0 | 1 | 63.5% | 63.5% | 0.0% | 98,347.12 |
| 2025-08-06 | 562.73 | 564.15 | -10.38 | 16.4% | 0 | 0 | 0.0% | 0.0% | 63.7% | 98,126.02 |
| 2025-08-07 | 563.77 | 562.81 | +7.57 | 14.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-08-08 | 565.40 | 564.46 | +4.80 | 13.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-08-11 | 568.80 | 567.93 | +9.76 | 13.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-08-12 | 568.94 | 568.47 | +1.53 | 12.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-08-13 | 569.68 | 570.25 | +8.47 | 11.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-08-14 | 572.58 | 571.26 | +3.72 | 11.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-08-15 | 571.00 | 574.93 | +11.62 | 11.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-08-18 | 571.83 | 571.44 | -6.20 | 11.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-08-19 | 571.91 | 571.69 | +9.93 | 10.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-08-20 | 568.84 | 570.31 | -1.33 | 10.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-08-21 | 570.73 | 570.97 | +8.29 | 10.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-08-22 | 573.73 | 570.16 | +0.71 | 10.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-08-25 | 573.47 | 572.26 | +10.24 | 10.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-08-26 | 572.25 | 572.84 | +2.39 | 10.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-08-27 | 576.66 | 575.92 | +11.30 | 10.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-08-28 | 575.12 | 576.64 | +1.97 | 10.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-08-29 | 570.93 | 575.89 | +3.88 | 10.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-09-01 | 572.50 | 571.05 | -5.12 | 11.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-09-02 | 565.93 | 571.43 | +9.94 | 11.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-09-03 | 569.83 | 570.67 | +0.28 | 10.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-09-04 | 574.55 | 572.27 | +9.78 | 10.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-09-05 | 570.63 | 577.00 | +11.44 | 11.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-09-08 | 574.28 | 573.91 | -4.86 | 11.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-09-09 | 574.30 | 573.53 | +8.73 | 10.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-09-10 | 577.38 | 578.64 | +13.13 | 11.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-09-11 | 581.07 | 579.28 | +2.10 | 11.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-09-12 | 581.38 | 580.81 | +9.42 | 10.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-09-15 | 581.84 | 581.88 | +4.92 | 10.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-09-16 | 577.10 | 581.45 | +4.41 | 10.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-09-17 | 576.53 | 577.27 | -2.72 | 11.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-09-18 | 583.05 | 580.56 | +15.66 | 11.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-09-19 | 583.71 | 581.84 | +2.24 | 10.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-09-22 | 584.93 | 584.95 | +12.55 | 10.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-09-23 | 585.32 | 585.80 | +2.96 | 10.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-09-24 | 584.38 | 583.63 | +1.82 | 10.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-09-25 | 583.71 | 582.79 | +5.22 | 10.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-09-26 | 584.19 | 583.69 | +7.20 | 10.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-09-29 | 585.74 | 586.38 | +9.94 | 10.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-09-30 | 585.07 | 584.89 | -0.05 | 10.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-10-01 | 589.41 | 582.62 | +3.32 | 10.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,072.81 |
| 2025-10-02 | 591.48 | 591.07 | +22.82 | 13.4% | 0 | 1 | 89.4% | 89.4% | 0.0% | 98,072.81 |
| 2025-10-03 | 593.99 | 594.01 | +2.23 | 13.1% | 0 | 1 | 91.8% | 89.7% | 89.7% | 97,982.27 |
| 2025-10-06 | 595.94 | 595.96 | +10.71 | 12.0% | 0 | 1 | 99.6% | 99.6% | 89.8% | 98,271.15 |
| 2025-10-07 | 595.10 | 595.86 | +2.60 | 11.3% | 0 | 1 | 100.0% | 99.5% | 99.5% | 98,123.87 |
| 2025-10-08 | 600.36 | 597.47 | +9.85 | 10.7% | 0 | 1 | 100.0% | 99.5% | 99.5% | 98,987.29 |
| 2025-10-09 | 600.60 | 600.84 | +9.52 | 11.0% | 0 | 1 | 100.0% | 99.5% | 99.5% | 99,026.74 |
| 2025-10-10 | 588.75 | 600.17 | +1.81 | 10.5% | 0 | 1 | 100.0% | 99.5% | 99.5% | 97,083.35 |
| 2025-10-13 | 593.54 | 590.56 | -12.00 | 15.1% | 0 | 0 | 0.0% | 0.0% | 99.5% | 97,868.21 |
| 2025-10-14 | 590.64 | 588.73 | +10.05 | 14.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,983.36 |
| 2025-10-15 | 594.28 | 593.37 | +11.59 | 13.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,983.36 |
| 2025-10-16 | 593.58 | 594.09 | +2.92 | 12.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,983.36 |
| 2025-10-17 | 587.38 | 582.34 | -17.76 | 17.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,983.36 |
| 2025-10-20 | 597.46 | 594.18 | +40.36 | 18.9% | 0 | 1 | 63.5% | 63.5% | 0.0% | 96,983.36 |
| 2025-10-21 | 599.81 | 598.02 | -4.45 | 17.8% | 0 | 0 | 0.0% | 0.0% | 63.6% | 97,106.91 |
| 2025-10-22 | 596.32 | 599.65 | +13.41 | 15.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,027.76 |
| 2025-10-23 | 598.82 | 598.47 | -1.30 | 13.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,027.76 |
| 2025-10-24 | 603.31 | 601.07 | +13.70 | 12.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,027.76 |
| 2025-10-27 | 607.16 | 607.62 | +13.93 | 13.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,027.76 |
| 2025-10-28 | 608.42 | 607.21 | +0.05 | 12.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,027.76 |
| 2025-10-29 | 609.35 | 611.14 | +15.31 | 12.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,027.76 |
| 2025-10-30 | 610.19 | 609.88 | -2.30 | 11.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,027.76 |
| 2025-10-31 | 609.37 | 611.09 | +11.37 | 10.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,027.76 |
| 2025-11-03 | 610.50 | 610.20 | +0.39 | 10.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,027.76 |
| 2025-11-04 | 608.19 | 605.12 | -2.09 | 12.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,027.76 |
| 2025-11-05 | 609.18 | 604.16 | +6.96 | 11.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,027.76 |
| 2025-11-06 | 600.58 | 606.08 | +7.88 | 11.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,027.76 |
| 2025-11-07 | 592.78 | 602.24 | -3.85 | 11.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,027.76 |
| 2025-11-10 | 604.55 | 603.58 | +12.03 | 10.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,027.76 |
| 2025-11-11 | 606.74 | 607.83 | +9.66 | 11.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,027.76 |
| 2025-11-12 | 610.27 | 611.21 | +9.29 | 11.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,027.76 |
| 2025-11-13 | 602.58 | 610.50 | +1.76 | 11.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,027.76 |
| 2025-11-14 | 601.04 | 598.09 | -17.31 | 17.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,027.76 |
| 2025-11-17 | 598.46 | 602.25 | +24.03 | 15.4% | 0 | 1 | 78.1% | 78.1% | 0.0% | 97,027.76 |
| 2025-11-18 | 590.65 | 590.76 | -27.83 | 17.6% | 0 | 0 | 0.0% | 0.0% | 76.8% | 96,939.35 |
| 2025-11-19 | 592.15 | 589.74 | +19.03 | 16.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,750.01 |
| 2025-11-20 | 596.24 | 600.41 | +18.93 | 19.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,750.01 |
| 2025-11-21 | 589.45 | 585.08 | -32.67 | 23.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,750.01 |
| 2025-11-24 | 597.29 | 593.68 | +40.78 | 20.2% | 0 | 1 | 59.3% | 59.3% | 0.0% | 96,750.01 |
| 2025-11-25 | 598.75 | 598.08 | -3.01 | 19.1% | 0 | 0 | 0.0% | 0.0% | 58.8% | 96,756.82 |
| 2025-11-26 | 605.95 | 603.70 | +20.31 | 17.1% | 0 | 1 | 70.0% | 70.0% | 0.0% | 97,170.23 |
| 2025-11-27 | 605.40 | 605.42 | +1.38 | 15.2% | 0 | 1 | 79.2% | 79.2% | 69.8% | 97,099.22 |
| 2025-11-28 | 607.69 | 607.54 | +11.21 | 13.4% | 0 | 1 | 89.8% | 89.8% | 78.7% | 97,349.90 |
| 2025-12-01 | 605.22 | 604.04 | -4.45 | 12.6% | 0 | 0 | 0.0% | 0.0% | 89.2% | 97,048.14 |
| 2025-12-02 | 605.26 | 604.17 | +10.48 | 11.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,812.34 |
| 2025-12-03 | 605.13 | 605.93 | +6.86 | 11.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,812.34 |
| 2025-12-04 | 606.88 | 606.74 | +6.97 | 10.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,812.34 |
| 2025-12-05 | 609.09 | 608.50 | +8.76 | 10.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,812.34 |
| 2025-12-08 | 608.05 | 608.95 | +5.12 | 10.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,812.34 |
| 2025-12-09 | 608.69 | 608.31 | +4.78 | 10.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,812.34 |
| 2025-12-10 | 607.32 | 606.72 | +2.99 | 10.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,812.34 |
| 2025-12-11 | 605.21 | 603.69 | +0.93 | 11.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,812.34 |
| 2025-12-12 | 601.42 | 608.45 | +17.70 | 11.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,812.34 |
| 2025-12-15 | 602.47 | 604.64 | -7.84 | 11.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,812.34 |
| 2025-12-16 | 598.38 | 598.94 | +0.33 | 13.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,812.34 |
| 2025-12-17 | 595.78 | 601.75 | +13.69 | 12.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,812.34 |
| 2025-12-18 | 602.35 | 595.98 | -10.29 | 13.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,812.34 |
| 2025-12-19 | 605.00 | 601.64 | +24.76 | 12.7% | 0 | 1 | 94.4% | 94.4% | 0.0% | 96,812.34 |
| 2025-12-22 | 606.16 | 605.86 | +4.90 | 13.3% | 0 | 1 | 90.5% | 90.5% | 94.6% | 96,767.45 |
| 2025-12-23 | 607.70 | 606.12 | +6.40 | 12.0% | 0 | 1 | 100.0% | 100.0% | 90.9% | 96,986.59 |
| 2025-12-24 | 608.01 | 607.50 | +7.94 | 11.2% | 0 | 1 | 100.0% | 99.6% | 99.6% | 97,030.40 |
| 2025-12-29 | 608.36 | 609.08 | +7.60 | 10.8% | 0 | 1 | 100.0% | 99.6% | 99.6% | 97,085.47 |
| 2025-12-30 | 609.64 | 608.07 | +2.41 | 10.5% | 0 | 1 | 100.0% | 99.6% | 99.6% | 97,289.27 |
| 2025-12-31 | 608.19 | 608.54 | +7.86 | 10.2% | 0 | 1 | 100.0% | 99.6% | 99.6% | 97,058.40 |
| 2026-01-02 | 606.75 | 608.83 | +4.82 | 10.1% | 0 | 1 | 100.0% | 99.6% | 99.6% | 96,830.01 |
| 2026-01-05 | 614.32 | 611.54 | +11.13 | 10.3% | 0 | 1 | 100.0% | 99.6% | 99.6% | 98,033.80 |
| 2026-01-06 | 616.42 | 614.03 | +7.67 | 10.6% | 0 | 1 | 100.0% | 99.6% | 99.6% | 98,367.26 |
| 2026-01-07 | 618.31 | 618.34 | +13.18 | 11.3% | 0 | 1 | 100.0% | 99.6% | 99.6% | 98,668.12 |
| 2026-01-08 | 617.37 | 615.73 | -3.08 | 11.1% | 0 | 0 | 0.0% | 0.0% | 99.6% | 98,518.27 |
| 2026-01-09 | 622.32 | 618.25 | +14.92 | 10.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,559.49 |
| 2026-01-12 | 622.16 | 618.61 | +1.79 | 10.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,559.49 |
| 2026-01-13 | 623.00 | 622.82 | +15.80 | 10.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,559.49 |
| 2026-01-14 | 619.55 | 622.74 | +0.52 | 10.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,559.49 |
| 2026-01-15 | 626.62 | 622.85 | +8.22 | 10.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,559.49 |
| 2026-01-16 | 625.24 | 626.51 | +11.54 | 10.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,559.49 |
| 2026-01-19 | 616.35 | 617.93 | -14.42 | 14.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,559.49 |
| 2026-01-20 | 611.35 | 611.66 | +2.34 | 16.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,559.49 |
| 2026-01-21 | 611.38 | 608.50 | +0.27 | 14.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,559.49 |
| 2026-01-22 | 615.62 | 616.24 | +23.05 | 15.0% | 0 | 1 | 79.9% | 79.9% | 0.0% | 98,559.49 |
| 2026-01-23 | 614.56 | 615.81 | -4.31 | 13.2% | 0 | 0 | 0.0% | 0.0% | 79.4% | 98,322.25 |
| 2026-01-26 | 612.36 | 611.41 | +0.83 | 13.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,844.49 |
| 2026-01-27 | 611.03 | 614.91 | +14.02 | 12.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,844.49 |
| 2026-01-28 | 612.51 | 612.44 | -4.30 | 11.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,844.49 |
| 2026-01-29 | 606.86 | 611.82 | +8.39 | 11.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,844.49 |
| 2026-01-30 | 611.11 | 606.70 | -7.04 | 12.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,844.49 |
| 2026-02-02 | 617.80 | 606.62 | +10.53 | 11.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,844.49 |
| 2026-02-03 | 615.15 | 620.40 | +29.93 | 19.5% | 0 | 1 | 61.7% | 61.7% | 0.0% | 97,844.49 |
| 2026-02-04 | 613.58 | 614.54 | -18.59 | 16.8% | 0 | 0 | 0.0% | 0.0% | 61.6% | 97,690.48 |
| 2026-02-05 | 608.06 | 612.81 | +13.05 | 15.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,555.61 |
| 2026-02-06 | 613.74 | 604.85 | -14.99 | 16.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,555.61 |
| 2026-02-09 | 617.00 | 615.40 | +36.54 | 17.0% | 0 | 1 | 70.7% | 70.7% | 0.0% | 97,555.61 |
| 2026-02-10 | 618.06 | 616.34 | -7.94 | 15.0% | 0 | 0 | 0.0% | 0.0% | 70.2% | 97,678.56 |
| 2026-02-11 | 618.22 | 617.40 | +13.81 | 13.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,536.33 |
| 2026-02-12 | 612.37 | 620.41 | +7.16 | 12.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,536.33 |
| 2026-02-13 | 611.81 | 609.62 | -17.40 | 17.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,536.33 |
| 2026-02-16 | 610.52 | 611.36 | +19.54 | 14.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,536.33 |
| 2026-02-17 | 611.92 | 610.68 | -3.01 | 13.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,536.33 |
| 2026-02-18 | 618.70 | 614.33 | +16.77 | 12.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,536.33 |
| 2026-02-19 | 617.93 | 618.37 | +8.02 | 12.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,536.33 |
| 2026-02-20 | 619.57 | 619.28 | +5.76 | 11.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,536.33 |
| 2026-02-23 | 614.99 | 616.44 | -0.75 | 11.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,536.33 |
| 2026-02-24 | 617.69 | 615.27 | +5.71 | 11.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,536.33 |
| 2026-02-25 | 622.04 | 619.51 |  |  | 0 |  |  | 0.0% | 0.0% | 97,536.33 |
| 2026-02-26 | 620.98 | 622.51 | +7.71 | 11.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,536.33 |
| 2026-02-27 | 618.43 | 620.62 | +0.95 | 11.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,536.33 |
| 2026-03-02 | 620.10 | 613.00 | -7.43 | 14.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,536.33 |
| 2026-03-03 | 613.15 | 616.00 | +17.90 | 13.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,536.33 |
| 2026-03-04 | 620.03 | 614.20 | -3.93 | 11.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,536.33 |
| 2026-03-05 | 616.96 | 619.70 | +21.20 | 12.1% | 0 | 1 | 98.8% | 98.8% | 0.0% | 97,536.33 |
| 2026-03-06 | 610.03 | 617.43 | -6.31 | 11.4% | 0 | 0 | 0.0% | 0.0% | 98.8% | 96,285.48 |
| 2026-03-09 | 607.34 | 601.27 | -21.75 | 23.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 94,826.01 |
| 2026-03-10 | 615.79 | 614.00 | +44.69 | 22.5% | 0 | 1 | 53.3% | 53.3% | 0.0% | 94,826.01 |
| 2026-03-11 | 613.53 | 613.14 | -14.42 | 18.6% | 0 | 0 | 0.0% | 0.0% | 53.1% | 94,807.11 |
| 2026-03-12 | 610.62 | 612.81 | +14.20 | 16.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 94,698.19 |
| 2026-03-13 | 609.54 | 607.97 | -8.71 | 14.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 94,698.19 |
| 2026-03-16 | 611.16 | 611.07 | +18.47 | 13.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 94,698.19 |
| 2026-03-17 | 612.33 | 609.61 | -3.78 | 12.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 94,698.19 |
| 2026-03-18 | 608.62 | 615.43 | +21.72 | 12.5% | 0 | 1 | 96.1% | 96.1% | 0.0% | 94,698.19 |
| 2026-03-19 | 598.40 | 604.59 | -25.35 | 16.3% | 0 | 0 | 0.0% | 0.0% | 95.2% | 93,685.09 |
| 2026-03-20 | 592.57 | 600.28 | +10.13 | 16.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 93,876.70 |
| 2026-03-23 | 594.90 | 584.46 | -32.01 | 24.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 93,876.70 |
| 2026-03-24 | 595.05 | 595.28 | +46.73 | 21.8% | 0 | 1 | 54.9% | 54.9% | 0.0% | 93,876.70 |
| 2026-03-25 | 599.96 | 599.06 | -6.60 | 20.0% | 0 | 0 | 0.0% | 0.0% | 54.9% | 93,902.80 |
| 2026-03-26 | 593.53 | 597.16 | +6.30 | 17.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 93,609.99 |
| 2026-03-27 | 585.37 | 592.81 | -5.18 | 15.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 93,609.99 |
| 2026-03-30 | 589.28 | 584.05 | -9.30 | 18.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 93,609.99 |
| 2026-03-31 | 589.23 | 587.17 | +18.12 | 15.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 93,609.99 |
| 2026-04-01 | 600.57 | 600.41 | +26.36 | 22.6% | 0 | 1 | 53.1% | 53.1% | 0.0% | 93,609.99 |
| 2026-04-02 | 600.71 | 593.81 | -19.48 | 19.7% | 0 | 0 | 0.0% | 0.0% | 52.3% | 94,127.18 |
| 2026-04-07 | 597.32 | 602.12 | +34.17 | 18.0% | 0 | 1 | 66.6% | 66.6% | 0.0% | 94,193.29 |
| 2026-04-08 | 612.60 | 614.19 | +16.15 | 23.6% | 0 | 1 | 50.8% | 50.8% | 67.8% | 93,964.27 |
| 2026-04-09 | 613.30 | 613.27 | -1.88 | 19.4% | 0 | 0 | 0.0% | 0.0% | 50.9% | 94,020.20 |
| 2026-04-10 | 615.00 | 615.05 | +12.20 | 16.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 94,108.20 |
| 2026-04-13 | 614.72 | 611.33 | -5.53 | 14.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 94,108.20 |
| 2026-04-14 | 621.58 | 617.12 | +22.24 | 14.2% | 0 | 1 | 84.8% | 84.8% | 0.0% | 94,108.20 |
| 2026-04-15 | 623.91 | 622.67 | +8.71 | 15.1% | 0 | 1 | 79.5% | 79.5% | 84.8% | 94,187.67 |
| 2026-04-16 | 627.67 | 627.21 | +13.05 | 14.3% | 0 | 1 | 83.8% | 83.8% | 80.2% | 94,660.69 |
| 2026-04-17 | 634.99 | 627.67 | +2.78 | 12.8% | 0 | 1 | 93.5% | 93.5% | 83.7% | 95,580.36 |
| 2026-04-20 | 632.60 | 632.17 | +15.82 | 12.7% | 0 | 1 | 94.8% | 93.0% | 93.0% | 95,276.44 |
| 2026-04-21 | 631.99 | 634.36 | +5.30 | 12.1% | 0 | 1 | 99.1% | 99.1% | 92.9% | 95,190.83 |
| 2026-04-22 | 634.78 | 633.63 | +4.55 | 11.4% | 0 | 1 | 100.0% | 98.9% | 98.9% | 95,585.87 |
| 2026-04-23 | 636.73 | 634.03 | +7.02 | 10.8% | 0 | 1 | 100.0% | 99.0% | 99.0% | 95,876.74 |
| 2026-04-24 | 635.73 | 635.73 | +8.31 | 10.6% | 0 | 1 | 100.0% | 99.0% | 99.0% | 95,727.11 |
| 2026-04-27 | 634.90 | 635.99 | +4.85 | 10.3% | 0 | 1 | 100.0% | 98.9% | 98.9% | 95,604.13 |
| 2026-04-28 | 632.86 | 637.40 | +8.69 | 10.2% | 0 | 1 | 100.0% | 98.9% | 98.9% | 95,300.60 |
| 2026-04-29 | 632.93 | 635.66 | +0.63 | 10.4% | 0 | 1 | 100.0% | 98.9% | 98.9% | 95,310.70 |
| 2026-04-30 | 637.16 | 633.33 | +3.19 | 10.9% | 0 | 1 | 100.0% | 99.0% | 99.0% | 95,941.36 |
| 2026-05-04 | 638.94 | 641.76 | +23.27 | 14.2% | 0 | 1 | 84.3% | 84.3% | 99.0% | 96,206.23 |
| 2026-05-05 | 643.41 | 641.18 | -3.82 | 12.7% | 0 | 0 | 0.0% | 0.0% | 84.4% | 96,808.57 |
| 2026-05-06 | 650.83 | 645.95 | +19.51 | 12.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,049.30 |
| 2026-05-07 | 651.36 | 653.33 | +13.37 | 15.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,049.30 |
| 2026-05-08 | 650.65 | 650.60 | -3.32 | 13.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,049.30 |
| 2026-05-11 | 653.08 | 650.65 | +9.90 | 12.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,049.30 |
| 2026-05-12 | 648.90 | 650.13 | +2.69 | 11.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,049.30 |
| 2026-05-13 | 655.85 | 655.05 | +16.67 | 12.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,049.30 |
| 2026-05-14 | 664.54 | 658.77 | +7.82 | 12.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,049.30 |
| 2026-05-15 | 659.11 | 661.40 | +9.78 | 11.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,049.30 |
| 2026-05-18 | 655.69 | 653.86 | -10.82 | 14.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,049.30 |
| 2026-05-19 | 655.13 | 656.86 | +19.19 | 12.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,049.30 |
| 2026-05-20 | 661.61 | 656.17 | -1.96 | 11.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,049.30 |
| 2026-05-21 | 661.84 | 660.94 | +18.53 | 11.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,049.30 |
| 2026-05-22 | 668.85 | 666.43 | +10.10 | 13.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,049.30 |
| 2026-05-25 | 672.50 | 671.92 | +13.99 | 13.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,049.30 |
| 2026-05-26 | 670.41 | 671.03 | +0.14 | 12.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,049.30 |
| 2026-05-27 | 669.33 | 669.89 | +6.24 | 11.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,049.30 |
| 2026-05-28 | 670.92 | 669.48 | +4.71 | 11.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,049.30 |
| 2026-05-29 | 672.00 | 672.96 | +12.71 | 11.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,049.30 |
| 2026-06-01 | 673.97 | 674.37 | +4.99 | 10.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,049.30 |
| 2026-06-02 | 676.87 | 674.08 | +5.42 | 10.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,049.30 |
| 2026-06-03 | 674.97 | 678.30 | +13.68 | 11.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,049.30 |
| 2026-06-04 | 674.77 | 672.22 | -9.52 | 12.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,049.30 |
| 2026-06-05 | 671.53 | 671.96 | +12.27 | 11.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,049.30 |
| 2026-06-08 | 667.55 | 664.53 | -11.67 | 13.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,049.30 |
| 2026-06-09 | 657.86 | 667.56 | +19.56 | 12.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,049.30 |
| 2026-06-10 | 657.40 | 660.65 | -14.28 | 13.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,049.30 |
| 2026-06-11 | 658.04 | 657.34 | +8.53 | 13.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,049.30 |
| 2026-06-12 | 668.46 | 662.87 | +14.87 | 13.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 97,049.30 |
| 2026-06-15 | 676.59 | 674.84 | +24.05 | 19.0% | 0 | 1 | 63.0% | 63.0% | 0.0% | 97,049.30 |
| 2026-06-16 | 675.88 | 677.26 | +1.73 | 16.5% | 0 | 1 | 72.7% | 72.7% | 62.8% | 96,863.85 |
| 2026-06-17 | 676.27 | 675.74 | +4.94 | 14.5% | 0 | 1 | 82.9% | 82.9% | 72.6% | 96,896.95 |
| 2026-06-18 | 678.69 | 677.85 | +10.08 | 13.0% | 0 | 1 | 92.1% | 92.1% | 82.4% | 97,151.19 |
| 2026-06-19 | 679.20 | 679.30 | +6.28 | 12.0% | 0 | 1 | 100.0% | 100.0% | 91.5% | 97,201.23 |
| 2026-06-22 | 680.56 | 680.02 | +6.73 | 11.2% | 0 | 1 | 100.0% | 99.9% | 99.9% | 97,377.71 |
| 2026-06-23 | 674.70 | 672.02 | -9.80 | 14.4% | 0 | 0 | 0.0% | 0.0% | 99.9% | 96,539.73 |
| 2026-06-24 | 679.25 | 675.66 | +19.80 | 12.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,580.41 |
| 2026-06-25 | 675.40 | 678.75 | +4.97 | 12.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,580.41 |
| 2026-06-26 | 673.57 | 672.03 | -6.32 | 14.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,580.41 |
| 2026-06-29 | 674.36 | 672.97 | +13.27 | 12.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,580.41 |
| 2026-06-30 | 681.23 | 679.11 | +13.77 | 13.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,580.41 |
| 2026-07-01 | 685.25 | 680.52 | +4.72 | 12.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,580.41 |
| 2026-07-02 | 681.98 | 681.05 | +7.35 | 11.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,580.41 |
| 2026-07-03 | 684.52 | 683.91 | +10.53 | 11.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,580.41 |
| 2026-07-06 | 687.74 | 685.64 | +6.97 | 10.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,580.41 |
| 2026-07-07 | 682.53 | 686.03 | +6.05 | 10.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,580.41 |
| 2026-07-08 | 677.54 | 681.64 | -2.44 | 11.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,580.41 |
| 2026-07-09 | 684.24 | 682.16 | +10.55 | 10.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,580.41 |
| 2026-07-10 | 686.72 | 684.47 | +7.75 | 10.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,580.41 |
| 2026-07-13 | 687.62 | 686.10 | +7.75 | 10.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,580.41 |
| 2026-07-14 | 685.94 | 684.97 | +2.58 | 10.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,580.41 |
| 2026-07-15 | 687.48 | 688.00 | +12.67 | 10.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,580.41 |
| 2026-07-16 | 687.15 | 685.91 | -1.55 | 10.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,580.41 |
| 2026-07-17 | 679.63 | 678.51 | -4.86 | 14.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,580.41 |
| 2026-07-20 | 681.47 | 678.94 | +11.04 | 12.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,580.41 |
| 2026-07-21 | 684.28 | 682.11 | +8.81 | 12.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,580.41 |
| 2026-07-22 | 685.96 | 682.47 | +4.82 | 11.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,580.41 |
| 2026-07-23 | 677.10 | 681.99 | +5.16 | 10.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,580.41 |
| 2026-07-24 | 681.65 | 678.04 | -1.45 | 11.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,580.41 |
| 2026-07-27 | 678.83 | 684.32 | +20.75 | 12.2% | 0 | 1 | 98.2% | 98.2% | 0.0% | 96,580.41 |
| 2026-07-28 | 681.09 | 679.18 | -11.03 | 12.2% | 0 | 0 | 0.0% | 0.0% | 97.9% | 96,751.48 |
| 2026-07-29 | 676.78 | 682.16 | +19.09 | 11.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,805.40 |
| 2026-07-30 | 672.88 | 672.38 | -19.29 | 14.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 96,805.40 |
| 2026-07-31 | 675.91 | 678.75 | +29.62 | 13.4% | 0 | 1 | 89.6% | 89.6% | 0.0% | 96,805.40 |
| 2026-08-03 | 686.23 | 682.22 | +1.06 | 13.5% | 0 | 1 | 88.8% | 90.3% | 90.3% | 97,231.34 |
| 2026-08-04 | 695.21 | 690.00 | +22.73 | 14.3% | 0 | 1 | 84.1% | 84.1% | 90.5% | 98,380.78 |
| 2026-08-05 | 697.77 | 699.89 | +16.39 | 17.6% | 0 | 1 | 68.3% | 68.3% | 84.1% | 98,721.24 |
| 2026-08-06 | 697.07 | 697.66 | -2.64 | 15.1% | 0 | 0 | 0.0% | 0.0% | 68.6% | 98,635.58 |
| 2026-08-07 | 699.77 | 697.95 | +10.96 | 13.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,653.25 |
| 2026-08-10 | 700.40 | 700.62 | +8.87 | 12.4% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,653.25 |
| 2026-08-11 | 700.18 | 700.56 | +4.78 | 11.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,653.25 |
| 2026-08-12 | 700.83 | 700.32 | +6.23 | 10.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,653.25 |
| 2026-08-13 | 703.89 | 702.81 | +10.61 | 10.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,653.25 |
| 2026-08-14 | 700.98 | 704.51 | +7.15 | 10.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,653.25 |
| 2026-08-17 | 700.14 | 701.89 | +0.84 | 10.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,653.25 |
| 2026-08-18 | 693.39 | 696.14 | -2.12 | 12.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,653.25 |
| 2026-08-19 | 690.81 | 691.64 | +1.34 | 13.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,653.25 |
| 2026-08-20 | 686.31 | 689.30 | +3.49 | 12.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,653.25 |
| 2026-08-21 | 688.01 | 684.63 | -2.04 | 13.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,653.25 |
| 2026-08-24 | 686.16 | 686.22 | +12.09 | 11.9% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,653.25 |
| 2026-08-25 | 687.92 | 689.07 | +7.78 | 11.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,653.25 |
| 2026-08-26 | 688.75 | 688.68 | +3.96 | 11.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,653.25 |
| 2026-08-27 | 691.31 | 690.95 | +10.69 | 10.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,653.25 |
| 2026-08-28 | 697.27 | 693.63 | +8.26 | 10.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,653.25 |
| 2026-08-31 | 689.52 | 693.79 | +4.82 | 10.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,653.25 |
| 2026-09-01 | 688.41 | 691.77 | +2.51 | 10.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,653.25 |
| 2026-09-02 | 689.74 | 687.80 | -0.18 | 11.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,653.25 |
| 2026-09-03 | 695.20 | 689.37 | +11.09 | 11.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,653.25 |
| 2026-09-04 | 693.06 | 694.61 | +12.59 | 12.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,653.25 |
| 2026-09-07 | 692.52 | 694.27 | +1.81 | 11.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,653.25 |
| 2026-09-08 | 691.68 | 692.03 | +3.47 | 11.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,653.25 |
| 2026-09-09 | 685.59 | 689.70 | +2.52 | 11.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,653.25 |
| 2026-09-10 | 682.51 | 686.71 | +1.84 | 11.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,653.25 |
| 2026-09-11 | 688.92 | 685.07 | +4.67 | 11.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,653.25 |
| 2026-09-14 | 687.71 | 686.07 | +8.24 | 10.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,653.25 |
| 2026-09-15 | 684.26 | 685.34 | +3.36 | 10.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,653.25 |
| 2026-09-16 | 687.56 | 686.34 | +8.89 | 10.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,653.25 |
| 2026-09-17 | 692.87 | 691.17 | +13.41 | 11.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,653.25 |
| 2026-09-18 | 691.06 | 694.51 | +8.54 | 11.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,653.25 |
| 2026-09-21 | 699.57 | 696.00 | +7.55 | 11.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,653.25 |
| 2026-09-22 | 703.73 | 702.72 | +17.85 | 12.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,653.25 |
| 2026-09-23 | 702.27 | 705.82 | +6.39 | 12.3% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,653.25 |
| 2026-09-24 | 698.18 | 697.68 | -8.57 | 14.8% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,653.25 |
| 2026-09-25 | 701.13 | 702.24 | +21.60 | 13.3% | 0 | 1 | 90.2% | 90.2% | 0.0% | 98,653.25 |
| 2026-09-28 | 699.27 | 701.73 | -2.22 | 12.1% | 0 | 0 | 0.0% | 0.0% | 89.7% | 98,254.86 |
| 2026-09-29 | 699.54 | 700.15 | +7.04 | 11.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,277.54 |
| 2026-09-30 | 702.09 | 701.56 | +7.99 | 11.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,277.54 |
| 2026-10-01 | 700.42 | 701.45 | +4.79 | 10.7% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,277.54 |
| 2026-10-02 | 706.96 | 704.17 | +11.55 | 10.6% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,277.54 |
| 2026-10-05 | 713.40 | 711.56 | +16.80 | 13.1% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,277.54 |
| 2026-10-06 | 717.11 | 716.17 | +9.40 | 13.2% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,277.54 |
| 2026-10-07 | 714.98 | 716.72 | +5.89 | 12.0% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,277.54 |
| 2026-10-08 | 712.18 | 712.20 | -1.38 | 12.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,277.54 |
| 2026-10-09 | 715.80 | 713.45 | +12.62 | 11.5% | 0 | 0 | 0.0% | 0.0% | 0.0% | 98,277.54 |
