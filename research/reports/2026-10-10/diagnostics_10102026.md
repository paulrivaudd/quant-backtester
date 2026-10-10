# Diagnostics complémentaires — résultats du 10 octobre 2026

Ce document mesure ce que les analyses de ce dossier listaient comme « restant à
mesurer », à la demande de la revue indépendante du 10 octobre. Il est écrit par
`scripts/run_review_diagnostics.py`, à partir des exports de l'étude et de
quelques runs supplémentaires du même moteur, sur la même période
(2021-04-01 → 2026-10-09), avec le même capital et les mêmes coûts.

**Tout ce qui suit est descriptif.** Un témoin à poids constants construit sur
les poids qu'une règle a détenus en moyenne est choisi après coup : il décrit
le passé de cette règle, ce n'est pas un paramètre qu'on aurait pu fixer à
l'avance. Une ablation de `SA10` ou un autre coefficient d'EWMA est une variante
regardée après un backtest. Aucune n'est candidate : en retenir une serait une
nouvelle hypothèse, à écrire avant son run, et chacune compterait comme un
essai dans le registre qui déflate les Sharpe. Les estimations sont ponctuelles
sauf mention d'un intervalle. Rien ici n'est un échantillon vierge.

Exports de l'étude : commit `788507bfab40` (CLEAN), magasin `750c23dfffc3`. Runs de ce document : commit `822c4320e93d` (CLEAN).

## 1. Résultat par séjour dans le marché (SA1, SA4, SA9)

| Stratégie | Séjours | Gagnants | Perdants | Part gagnante | Net moyen | Net médian | Pire | Meilleur | Composé | Durée moy. (valo.) | Coûts EUR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| SA1 - std MA20 | 72 | 29 | 43 | 40% | +0.31% | -0.28% | -6.14% | +17.48% | +20.45% | 13.1 | 15,730 |
| SA4 - pullback | 71 | 47 | 24 | 66% | +0.06% | +0.04% | -2.92% | +1.85% | +4.43% | 2.8 | 4,572 |
| SA9 - VIX relief | 21 | 9 | 12 | 43% | -0.02% | -0.70% | -2.64% | +3.64% | -0.70% | 5.0 | 2,041 |

Un séjour est une suite de valorisations où une position est détenue. Son résultat net va de la valorisation qui précède l'entrée à la première valorisation revenue en cash : les deux exécutions et leurs coûts sont dedans. « Composé » est le produit des séjours et retrouve le rendement net de la stratégie, puisque le cash ne rapporte rien.

### SA9 : ses 21 séjours regroupés en 7 paniques

| Première entrée | Dernière sortie | Séjours | Net | Coûts EUR |
|---|---:|---:|---:|---:|
| 2021-12-08 | 2022-02-14 | 5 | -2.07% | 493 |
| 2022-03-17 | 2022-04-12 | 3 | +0.30% | 297 |
| 2022-05-17 | 2022-07-13 | 5 | -2.50% | 484 |
| 2022-10-31 | 2022-11-17 | 2 | -2.22% | 190 |
| 2024-08-12 | 2024-09-03 | 2 | +1.75% | 190 |
| 2025-04-15 | 2025-05-21 | 2 | +0.90% | 190 |
| 2026-04-07 | 2026-04-29 | 2 | +3.30% | 197 |

Deux séjours séparés par 20 valorisations ou moins sont rattachés à la même panique.

## 2. Effet du délai entre la clôture de la décision et l'exécution à l'ouverture

| Livre | Ordres | Gaps favorables EUR | Gaps défavorables EUR | Effet net EUR | En % du capital initial |
|---|---:|---:|---:|---:|---:|
| 50/50 rebalanced | 617 | +112 | -1,225 | -1,113 | -1.11% |
| EWMA 0.94 control | 220 | +3,568 | -6,584 | -3,016 | -3.02% |
| SA6 - vol control | 180 | +2,991 | -5,420 | -2,428 | -2.43% |
| SA10 - ensemble | 465 | +4,981 | -5,966 | -985 | -0.99% |
| SA3 - smooth MA | 78 | +2,122 | -2,748 | -626 | -0.63% |
| SA11 - GARCH vol control | 508 | +10,108 | -12,880 | -2,772 | -2.77% |
| SA2 - dual momentum | 317 | +9,457 | -11,305 | -1,848 | -1.85% |
| SA5 - relative tilt | 1904 | +44,472 | -47,103 | -2,631 | -2.63% |
| SA1 - std MA20 | 143 | +28,256 | -42,615 | -14,359 | -14.36% |
| SA4 - pullback | 237 | +14,645 | -12,354 | +2,291 | +2.29% |
| SA9 - VIX relief | 42 | +4,555 | -9,406 | -4,852 | -4.85% |
| buy & hold World | 1 | +0 | -961 | -961 | -0.96% |

Pour chaque ordre : `-signe x montant x (ouverture / clôture précédente - 1)`, signe +1 pour un achat. Positif : le mouvement de la nuit a aidé. C'est une mesure de premier ordre sur les prix cotés ; elle ne rejoue pas les quantités qu'un autre prix d'exécution aurait données.

## 3. SA2 et SA5 contre le panier 50/50 des deux mêmes fonds

| Stratégie | Panier (clôtures) | Exposition totale | Choix entre fonds | Exécution (résidu) | Coûts | = Net de la stratégie | Panier 50/50 exécuté, net |
|---|---:|---:|---:|---:|---:|---:|---:|
| SA2 - dual momentum | +0.7273 | -0.1397 | +0.0044 | -0.0392 | -0.0270 | +0.5258 | +0.7097 |
| SA5 - relative tilt | +0.7273 | -0.0111 | +0.0027 | -0.0596 | -0.1122 | +0.5471 | +0.7097 |

Rendements logarithmiques sur la période, qui s'additionnent ligne à ligne. « Exposition totale » : ce que détenir le poids total de la veille dans le panier ajoute au panier (le timing de l'exposition). « Choix entre fonds » : ce que détenir les poids par fonds de la veille ajoute à cela. Ces trois premières colonnes sont calculées sur des clôtures, pas sur les prix d'exécution : l'écart avec la comptabilité brute du moteur est laissé visible dans « exécution ».

### SA5 : le signal d'inclinaison et ce que les fonds ont fait ensuite

- 1416 décisions avec un résidu non nul ; le résidu change de signe **293 fois**, soit un signe tenu en moyenne 4.8 valorisations.
- Corrélation du résidu (positif quand le fonds monde a pris du retard, donc surpondéré) avec le rendement relatif monde moins S&P 500 :

| Horizon | Pearson | Spearman | Paires |
|---|---:|---:|---:|
| séance suivant la décision (en partie avant l'exécution) | +0.029 | +0.030 | 1414 |
| première séance entière après l'exécution | +0.028 | +0.004 | 1413 |
| cinq séances après l'exécution | +0.063 | +0.005 | 1409 |

Un signal qui prévoirait le rendement relatif sur lequel il mise montrerait une corrélation positive. Ces coefficients sont donnés sans intervalle.

## 4. Chaque règle à exposition variable à côté d'un témoin à poids constants

| Livre | Net | Net/an | Vol. | Sharpe | Perte max. | Retour au sommet (j) | Expo. moy. | Ordres | Coûts EUR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| SA3 - smooth MA | +57.88% | +8.62% | 11.01% | +0.79 | -21.64% | 540 | 71.5% | 78 | 680 |
| ↳ poids constants (ETF_WORLD 71.5%) | +63.15% | +9.27% | 9.88% | +0.93 | -15.86% | 226 | 72.2% | 7 | 94 |
| SA6 - vol control | +67.43% | +9.78% | 10.87% | +0.90 | -15.72% | 330 | 84.7% | 180 | 1,445 |
| ↳ poids constants (ETF_WORLD 84.7%) | +77.98% | +11.00% | 11.83% | +0.93 | -18.53% | 229 | 86.1% | 4 | 97 |
| SA10 - ensemble | +32.06% | +5.16% | 6.00% | +0.86 | -11.76% | 442 | 42.4% | 465 | 1,986 |
| ↳ poids constants (ETF_SP500_PEA 15.3%, ETF_WORLD 27.1%) | +37.08% | +5.88% | 6.23% | +0.93 | -9.99% | 231 | 44.8% | 8 | 61 |
| SA11 - GARCH vol control | +65.98% | +9.61% | 11.14% | +0.87 | -16.50% | 324 | 87.5% | 508 | 3,749 |
| ↳ poids constants (ETF_WORLD 87.5%) | +81.19% | +11.36% | 12.27% | +0.92 | -19.46% | 229 | 89.0% | 3 | 96 |
| EWMA 0.94 control | +73.37% | +10.48% | 11.16% | +0.93 | -15.45% | 321 | 87.8% | 220 | 1,519 |
| ↳ poids constants (ETF_WORLD 87.8%) | +81.59% | +11.41% | 12.31% | +0.92 | -19.51% | 229 | 89.3% | 3 | 97 |

Le témoin détient en permanence les poids que la règle a détenus en moyenne, avec la même bande de 3 points et les mêmes coûts. Une règle qui ne fait pas mieux que lui n'a rien gagné à faire varier son exposition sur cette période. Ces poids étant connus après coup, la comparaison est descriptive.

## 5. SA10 sans chacune de ses règles, et sans son contrôle de risque

| Version | Net | Net/an | Vol. | Sharpe | Perte max. | Retour au sommet (j) | Expo. moy. | Ordres | Coûts EUR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| SA10 - ensemble | +32.06% | +5.16% | 6.00% | +0.86 | -11.76% | 442 | 42.4% | 465 | 1,986 |
| SA10 sans momentum | +18.88% | +3.18% | 3.58% | +0.88 | -7.12% | 449 | 25.3% | 368 | 1,256 |
| SA10 sans trend | +20.39% | +3.42% | 4.10% | +0.83 | -7.51% | 324 | 28.2% | 417 | 1,813 |
| SA10 sans pullback | +31.52% | +5.09% | 5.92% | +0.85 | -11.57% | 441 | 42.0% | 376 | 1,640 |
| SA10 sans relative | +23.85% | +3.95% | 4.80% | +0.82 | -9.56% | 448 | 32.8% | 302 | 1,397 |
| SA10 sans relief | +32.55% | +5.23% | 5.96% | +0.87 | -11.71% | 448 | 42.1% | 428 | 1,816 |
| SA10 sans contrôle de risque | +32.55% | +5.23% | 6.11% | +0.85 | -11.88% | 441 | 42.6% | 441 | 1,973 |

Chaque ligne « sans » remet le budget d'une règle à zéro : ce budget reste en cash, il n'est pas redistribué. « Sans contrôle de risque » fixe la cible de risque à un niveau jamais atteint, donc le facteur de réduction vaut toujours 1. Toutes ces versions sont, comme SA10 ici, sans fonds de style ni monétaire.

## 6. SA6 contre le témoin EWMA, et l'EWMA à d'autres coefficients

Différence de Sharpe SA6 moins EWMA 0,94 : **-0.036**, intervalle bootstrap à 95% [-0.104 ; +0.027] (blocs de 20 séances, 5000 tirages, graine 20261010). L'intervalle inclut zéro : les deux témoins ne sont pas départagés.

| Livre | Net | Net/an | Vol. | Sharpe | Perte max. | Retour au sommet (j) | Expo. moy. | Ordres | Coûts EUR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| EWMA 0.94 control | +73.37% | +10.48% | 11.16% | +0.93 | -15.45% | 321 | 87.8% | 220 | 1,519 |
| SA6 - vol control | +67.43% | +9.78% | 10.87% | +0.90 | -15.72% | 330 | 84.7% | 180 | 1,445 |
| EWMA 0.90 | +69.40% | +10.02% | 11.14% | +0.90 | -14.60% | 251 | 87.9% | 366 | 2,686 |
| EWMA 0.97 | +77.75% | +10.98% | 11.25% | +0.97 | -17.08% | 330 | 87.6% | 127 | 769 |

Les coefficients 0,90 et 0,97 ont été fixés dans le script avant leur run, de part et d'autre de 0,94 ; ils ne sont pas le résultat d'une recherche du meilleur coefficient, et ne doivent pas le devenir sur ce même historique.

## 7. ML1

Période de test prolongée, 2025-01-02 → 2026-10-09, modèle figé `d9bfd125bf69`.

### Contre une allocation constante

| Livre | Net | Net/an | Vol. | Sharpe | Perte max. | Retour au sommet (j) | Expo. moy. | Ordres | Coûts EUR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ML1 - neural allocation | +13.42% | +7.39% | 9.88% | +0.76 | -16.11% | 251 | 66.6% | 270 | 756 |
| ↳ allocation constante (ETF_SP500_PEA 36.3%, ETF_WORLD 30.3%) | +17.16% | +9.38% | 10.01% | +0.93 | -15.20% | 225 | 68.3% | 6 | 76 |
| buy & hold World | +24.54% | +13.23% | 14.31% | +0.93 | -21.51% | 229 | 99.1% | 1 | 99 |

L'allocation constante détient les poids moyens de ML1 sur ces dates, avec la même bande et les mêmes coûts : c'est le témoin exécutable que le produit « 65 % fois le rendement du fonds » ne remplaçait pas. Choisie après coup, elle est descriptive.

Sur ces dates, hors la première séance, le poids total détenu par ML1 va de 47.4% à 87.3% (écart-type 8.3%), et la part du fonds S&P 500 dans ce qui est investi va de 33.1% à 66.2% (moyenne 54.8%).

### Sensibilités annoncées par l'hypothèse (période de test d'origine, 2025-01-02 → 2026-09-30)

| Variante | Score | Net | Sharpe | Sharpe du fonds détenu | Perte max. | Expo. moy. | Coûts EUR |
|---|---:|---:|---:|---:|---:|---:|---:|
| graine 42, coûts x1 (le test préinscrit) | 44.5% | +11.71% | +0.68 | +0.86 | -16.11% | 66.6% | 752 |
| graine 43, coûts x1 | 45.9% | +11.78% | +0.70 | +0.86 | -15.33% | 61.8% | 683 |
| graine 44, coûts x1 | 45.6% | +12.26% | +0.71 | +0.86 | -15.96% | 68.3% | 654 |
| graine 42, coûts x2 | 44.3% | +11.78% | +0.69 | +0.86 | -15.65% | 66.0% | 1,037 |

Les graines 43 et 44 et les coûts doublés sont rapportés à côté de la graine 42 et ne la remplacent pas : une graine n'est jamais choisie sur son résultat de test. Chaque variante est calibrée par `scripts/run_neural_strategy.py` avec son propre artefact, puis testée une fois sur la période d'origine.

### Entrées du réseau

Les 319 caractéristiques lues par le réseau à chacune des 453 décisions sont exportées dans `ml1_inputs.csv` (dossier des diagnostics), avec leur statut : 453 décisions ont un vecteur complet. Elles sont reconstruites par le `NeuralFeatureBuilder` du modèle sur un lecteur figé à l'instant de chaque décision.

