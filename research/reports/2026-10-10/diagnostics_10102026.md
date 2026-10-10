# Diagnostics complémentaires — résultats du 10 octobre 2026

Ce document mesure ce que les analyses de ce dossier listaient comme « restant à
mesurer », à la demande de la revue indépendante du 10 octobre. Il est écrit par
`scripts/run_review_diagnostics.py`, à partir des exports de l'étude et de
quelques runs supplémentaires du même moteur, sur la même période
(2021-04-01 → 2026-10-09), avec le même capital et les mêmes coûts.

**Tout ce qui suit est descriptif.** Un témoin à cible constante, dont la cible
est le poids qu'une règle a détenu en moyenne, est choisi après coup : il décrit
le passé de cette règle, ce n'est pas un paramètre qu'on aurait pu fixer à
l'avance, et son exposition réalisée n'est pas celle de la règle. Une ablation
de `SA10` ou un autre coefficient d'EWMA est une variante
regardée après un backtest. Aucune n'est candidate : en retenir une serait une
nouvelle hypothèse, à écrire avant son run, et chacune compterait comme un
essai dans le registre qui déflate les Sharpe. Les estimations sont ponctuelles
sauf mention d'un intervalle. Rien ici n'est un échantillon vierge.

Version 2 du 10 octobre 2026, après la vérification indépendante faite sur le
commit `ad310bc`. Ont changé : l'écart de prix clôture-ouverture est mesuré à
quantités données, sur le prix de marché et non sur le montant exécuté ; la
colonne « exécution » de l'attribution est renommée en résidu, parce qu'elle
n'isole pas l'exécution ; les séjours clos et le séjour encore ouvert sont
comptés à part ; les corrélations de `SA5` gardent leur première décision et
composent leurs rendements à cinq séances ; les témoins sont dits « à cible
constante » ; `ML1` est rejoué avec son modèle figé à coûts doublés ; un run
n'est comparé aux exports que s'il a lu le même magasin.

Exports de l'étude : commit `788507bfab40` (CLEAN), magasin `750c23dfffc3`. Runs de ce document : commit `08bf2ac77e0c` (CLEAN).

## 1. Résultat par séjour dans le marché (SA1, SA4, SA9)

| Stratégie | Séjours | Clos | Ouvert | Clos gagnants | Clos perdants | Part gagnante (clos) | Net moyen | Net médian | Pire | Meilleur | Composé | Durée moy. (valo.) | Coûts EUR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| SA1 - std MA20 | 72 | 71 | 1 | 28 | 43 | 39.4% | +0.31% | -0.28% | -6.14% | +17.48% | +20.45% | 13.1 | 15,730 |
| SA4 - pullback | 71 | 71 | 0 | 47 | 24 | 66.2% | +0.06% | +0.04% | -2.92% | +1.85% | +4.43% | 2.8 | 4,572 |
| SA9 - VIX relief | 21 | 21 | 0 | 9 | 12 | 42.9% | -0.02% | -0.70% | -2.64% | +3.64% | -0.70% | 5.0 | 2,041 |

Un séjour est une suite de valorisations où une position est détenue. Le résultat net d'un séjour **clos** va de la valorisation qui précède l'entrée à la première valorisation revenue en cash : ses deux exécutions et leurs coûts sont dedans. Un séjour **ouvert** court encore à la dernière séance : il est valorisé au marché à cette séance, sans vente finale ni son coût. Les gagnants et les perdants sont comptés sur les seuls séjours clos. Le net moyen, le médian, le pire, le meilleur et « Composé » portent sur tous les séjours, l'ouvert compris : « Composé » en est le produit et retrouve le rendement net de la stratégie, puisque le cash ne rapporte rien.

- SA1 - std MA20 : un séjour encore ouvert, entré à la valorisation du 2026-09-18, valorisé +2.96% au 2026-10-09, sans vente finale.

### SA9 : ses 21 séjours en 7 groupes (convention : 20 valorisations)

| Première entrée | Dernière sortie | Séjours | Net | Coûts EUR |
|---|---:|---:|---:|---:|
| 2021-12-08 | 2022-02-14 | 5 | -2.07% | 493 |
| 2022-03-17 | 2022-04-12 | 3 | +0.30% | 297 |
| 2022-05-17 | 2022-07-13 | 5 | -2.50% | 484 |
| 2022-10-31 | 2022-11-17 | 2 | -2.22% | 190 |
| 2024-08-12 | 2024-09-03 | 2 | +1.75% | 190 |
| 2025-04-15 | 2025-05-21 | 2 | +0.90% | 190 |
| 2026-04-07 | 2026-04-29 | 2 | +3.30% | 197 |

Deux séjours séparés par 20 valorisations ou moins sont rattachés au même groupe. C'est un regroupement automatique par cette convention, pas l'identification économique d'autant de paniques indépendantes ; un groupe gagnant peut compter plusieurs entrées, comme un groupe perdant.

## 2. Écart de prix signé clôture-ouverture, à quantités données

| Livre | Ordres | Écarts favorables EUR | Écarts défavorables EUR | Écart net EUR | En % du capital initial | Ordres exclus (date de détachement) |
|---|---:|---:|---:|---:|---:|---:|
| 50/50 rebalanced | 617 | +112 | -1,211 | -1,100 | -1.10% | 0 |
| EWMA 0.94 control | 220 | +3,571 | -6,647 | -3,076 | -3.08% | 0 |
| SA6 - vol control | 180 | +2,985 | -5,487 | -2,503 | -2.50% | 0 |
| SA10 - ensemble | 465 | +4,966 | -5,997 | -1,031 | -1.03% | 0 |
| SA3 - smooth MA | 78 | +2,107 | -2,752 | -645 | -0.65% | 0 |
| SA11 - GARCH vol control | 508 | +10,066 | -12,989 | -2,923 | -2.92% | 0 |
| SA2 - dual momentum | 317 | +9,460 | -11,297 | -1,838 | -1.84% | 0 |
| SA5 - relative tilt | 1904 | +44,451 | -47,022 | -2,571 | -2.57% | 0 |
| SA1 - std MA20 | 143 | +28,201 | -42,768 | -14,568 | -14.57% | 0 |
| SA4 - pullback | 237 | +14,660 | -12,358 | +2,303 | +2.30% | 0 |
| SA9 - VIX relief | 42 | +4,528 | -9,472 | -4,944 | -4.94% | 0 |
| buy & hold World | 1 | +0 | -951 | -951 | -0.95% | 0 |

Pour chaque ordre : `-signe x quantité x (ouverture - clôture précédente)`, signe +1 pour un achat, sur le prix de marché de l'ouverture et non sur le prix exécuté : le spread, le slippage et la commission restent dans les coûts. Positif : le mouvement de la nuit est allé dans le sens de l'ordre. Un ordre exécuté à une date de détachement est exclu, les deux prix n'étant pas sur la même base.

C'est un **écart de prix à quantités données**, pas le résultat d'un autre backtest exécuté à la clôture : le signal lit cette clôture, donc l'ordre ne pouvait pas y être exécuté, et un autre prix d'exécution aurait changé toutes les quantités suivantes. Il ne se lit ni comme un coût payé ni comme un manque à gagner exact.

## 3. SA2 et SA5 contre le panier 50/50 des deux mêmes fonds

| Stratégie | Panier (clôtures) | Exposition totale | Choix entre fonds | Résidu de l'approximation aux poids de clôture | Coûts | = Net de la stratégie | Panier 50/50 exécuté, net |
|---|---:|---:|---:|---:|---:|---:|---:|
| SA2 - dual momentum | +0.7273 | -0.1397 | +0.0044 | -0.0392 | -0.0270 | +0.5258 | +0.7097 |
| SA5 - relative tilt | +0.7273 | -0.0111 | +0.0027 | -0.0596 | -0.1122 | +0.5471 | +0.7097 |

Rendements logarithmiques sur la période, qui s'additionnent ligne à ligne. « Exposition totale » : ce que détenir le poids total de la veille dans le panier ajoute au panier. « Choix entre fonds » : ce que détenir les poids par fonds de la veille ajoute à cela. Ces trois premières colonnes sont une **approximation** : elles valorisent les poids détenus à la clôture précédente avec le rendement de clôture à clôture, ce qui n'est pas la façon dont le livre a traité.

Le **résidu** est l'écart entre cette approximation et la comptabilité brute du moteur. Ce n'est pas une mesure de l'exécution : outre l'écart entre la clôture et le prix exécuté, la bande et les quantités entières, il contient le rendement de la journée sur ce qui a été acheté ou vendu le matin même - une partie de l'effet du signal. Un livre en cash qui achète à l'ouverture, au prix de la clôture précédente, et gagne 10 % dans la journée voit tout ce gain dans le résidu, avec une « exposition » négative d'autant. Les colonnes « exposition » et « choix » ne sont donc pas l'apport complet d'un timing, et le résidu n'est pas un handicap d'exécution. Une attribution exacte demande les quantités avant et après chaque exécution et les prix d'ouverture ; elle n'est pas produite ici.

### SA5 : le signal d'inclinaison et ce que les fonds ont fait ensuite

- 1416 décisions avec un résidu non nul ; le résidu change de signe **293 fois**, soit un signe tenu en moyenne 4.8 valorisations.
- Corrélation du résidu (positif quand le fonds monde a pris du retard, donc surpondéré) avec le rendement relatif monde moins S&P 500 :

| Horizon | Pearson | Spearman | Paires |
|---|---:|---:|---:|
| séance t + 1 (en partie avant l'exécution à son ouverture) | +0.029 | +0.030 | 1415 |
| séance t + 2, la première entière après l'exécution | +0.028 | +0.004 | 1414 |
| séances t + 2 à t + 6, rendements composés | +0.064 | +0.005 | 1410 |

Un signal qui prévoirait le rendement relatif sur lequel il mise montrerait une corrélation positive. Ces coefficients sont donnés sans intervalle, sur des rendements de clôture à clôture : ils ne mesurent pas l'intervalle d'ouverture à ouverture réellement porté après la décision, qui n'est pas calculé ici, et une corrélation proche de zéro n'exclut pas toute relation non linéaire.

## 4. Chaque règle à exposition variable à côté d'un témoin à cible constante

| Livre | Net | Net/an | Vol. | Sharpe | Perte max. | Retour au sommet (j) | Expo. moy. | Ordres | Coûts EUR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| SA3 - smooth MA | +57.88% | +8.62% | 11.01% | +0.79 | -21.64% | 540 | 71.5% | 78 | 680 |
| ↳ témoin à cible constante (ETF_WORLD 71.5%) | +63.15% | +9.27% | 9.88% | +0.93 | -15.86% | 226 | 72.2% | 7 | 94 |
| SA6 - vol control | +67.43% | +9.78% | 10.87% | +0.90 | -15.72% | 330 | 84.7% | 180 | 1,445 |
| ↳ témoin à cible constante (ETF_WORLD 84.7%) | +77.98% | +11.00% | 11.83% | +0.93 | -18.53% | 229 | 86.1% | 4 | 97 |
| SA10 - ensemble | +32.06% | +5.16% | 6.00% | +0.86 | -11.76% | 442 | 42.4% | 465 | 1,986 |
| ↳ témoin à cible constante (ETF_SP500_PEA 15.3%, ETF_WORLD 27.1%) | +37.08% | +5.88% | 6.23% | +0.93 | -9.99% | 231 | 44.8% | 8 | 61 |
| SA11 - GARCH vol control | +65.98% | +9.61% | 11.14% | +0.87 | -16.50% | 324 | 87.5% | 508 | 3,749 |
| ↳ témoin à cible constante (ETF_WORLD 87.5%) | +81.19% | +11.36% | 12.27% | +0.92 | -19.46% | 229 | 89.0% | 3 | 96 |
| EWMA 0.94 control | +73.37% | +10.48% | 11.16% | +0.93 | -15.45% | 321 | 87.8% | 220 | 1,519 |
| ↳ témoin à cible constante (ETF_WORLD 87.8%) | +81.59% | +11.41% | 12.31% | +0.92 | -19.51% | 229 | 89.3% | 3 | 97 |

Témoin à **cible constante** égale aux poids moyens historiques de la règle, avec la même bande de rééquilibrage de 3 points et les mêmes coûts : il ne traite que lorsque la dérive des cours l'écarte de sa cible de 3 points. Son exposition **réalisée** diffère donc de celle de la règle, comme la colonne « Expo. moy. » le montre (témoin moins règle : de +0.7 à +2.4 points ici). La comparaison décrit le résultat de deux règles exécutables ; elle n'isole pas, à exposition exactement identique, la valeur du timing : le niveau d'exposition, la composition, les coûts et la trajectoire changent aussi. Ces poids étant connus après coup, elle est descriptive.

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

L'écart entre SA10 et sa version sans contrôle de risque mesure l'**effet agrégé** de ce contrôle sur ce run. Il ne dit pas combien de fois le facteur de réduction a été inférieur à 1, ni à quelles dates : ce facteur et les décisions forcées par le risque du portefeuille détenu ne sont pas exportés.

## 6. SA6 contre le témoin EWMA, et l'EWMA à d'autres coefficients

Différence de Sharpe SA6 moins EWMA 0,94 : **-0.036**, intervalle bootstrap à 95% [-0.104 ; +0.027] (blocs de 20 séances, 5000 tirages, graine 20261010). L'intervalle inclut zéro : les deux témoins ne sont pas départagés.

| Livre | Net | Net/an | Vol. | Sharpe | Perte max. | Retour au sommet (j) | Expo. moy. | Ordres | Coûts EUR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| EWMA 0.94 control | +73.37% | +10.48% | 11.16% | +0.93 | -15.45% | 321 | 87.8% | 220 | 1,519 |
| SA6 - vol control | +67.43% | +9.78% | 10.87% | +0.90 | -15.72% | 330 | 84.7% | 180 | 1,445 |
| EWMA 0.90 | +69.40% | +10.02% | 11.14% | +0.90 | -14.60% | 251 | 87.9% | 366 | 2,686 |
| EWMA 0.97 | +77.75% | +10.98% | 11.25% | +0.97 | -17.08% | 330 | 87.6% | 127 | 769 |

Les coefficients 0,90 et 0,97 ont été fixés dans le script avant leur run, de part et d'autre de 0,94 ; ils ne sont pas le résultat d'une recherche du meilleur coefficient, et ne doivent pas le devenir sur ce même historique. L'ordre de ces trois EWMA ne vaut que pour elles : il ne définit pas une « vitesse » du GARCH réestimé chaque soir et n'établit pas une règle générale selon laquelle un estimateur plus lent serait meilleur.

## 7. ML1

Période de test prolongée, 2025-01-02 → 2026-10-09, modèle figé `d9bfd125bf69`.

### Contre une allocation constante

| Livre | Net | Net/an | Vol. | Sharpe | Perte max. | Retour au sommet (j) | Expo. moy. | Ordres | Coûts EUR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ML1 - neural allocation | +13.42% | +7.39% | 9.88% | +0.76 | -16.11% | 251 | 66.6% | 270 | 756 |
| ↳ témoin à cible constante (ETF_SP500_PEA 36.3%, ETF_WORLD 30.3%) | +17.16% | +9.38% | 10.01% | +0.93 | -15.20% | 225 | 68.3% | 6 | 76 |
| buy & hold World | +24.54% | +13.23% | 14.31% | +0.93 | -21.51% | 229 | 99.1% | 1 | 99 |

Témoin à cible constante égale aux poids moyens de ML1 sur ces dates, avec la même bande de 3 points et les mêmes coûts : c'est le témoin exécutable que le produit « 65 % fois le rendement du fonds » ne remplaçait pas. Son exposition réalisée n'est pas exactement celle de ML1 (colonne « Expo. moy. ») : la comparaison décrit deux règles exécutables et n'isole pas la valeur du timing à exposition identique. Choisi après coup, il est descriptif.

Sur ces dates, hors la première séance, le poids total détenu par ML1 va de 47.4% à 87.3% (écart-type 8.3%), et la part du fonds S&P 500 dans ce qui est investi va de 33.1% à 66.2% (moyenne 54.8%).

### Sensibilités annoncées par l'hypothèse (période de test d'origine, 2025-01-02 → 2026-09-30)

| Variante | Modèle | Époque retenue | Score | Net | Sharpe | Sharpe du fonds détenu | Perte max. | Expo. moy. | Coûts EUR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| graine 42, coûts x1 (le test préinscrit) | `d9bfd125bf69` | 20 | 44.5% | +11.71% | +0.68 | +0.86 | -16.11% | 66.6% | 752 |
| graine 43, coûts x1 | `84d056424fc7` | 5 | 45.9% | +11.78% | +0.70 | +0.86 | -15.33% | 61.8% | 683 |
| graine 44, coûts x1 | `8c9eaf9f5e92` | 15 | 45.6% | +12.26% | +0.71 | +0.86 | -15.96% | 68.3% | 654 |
| graine 42, modèle figé du test, coûts x2 (moteur seul) | `d9bfd125bf69` | 20 | 40.7% | +11.01% | +0.64 | +0.86 | -16.21% | 66.6% | 1,434 |
| graine 42, recalibrée sous coûts x2 | `a5afb76183eb` | 15 | 44.3% | +11.78% | +0.69 | +0.86 | -15.65% | 66.0% | 1,037 |

Les graines 43 et 44 et les coûts doublés sont rapportés à côté de la graine 42 et ne la remplacent pas : une graine n'est jamais choisie sur son résultat de test. Toutes les lignes portent sur la même période d'origine. Deux lignes à coûts doublés répondent à deux questions différentes. « Modèle figé » rejoue le **même artefact** que le test préinscrit - même normalisation, mêmes poids, même époque - en doublant seulement les coûts du moteur : ce que devient le modèle initial s'il coûte deux fois plus cher à exécuter. « Recalibrée » refait la calibration de `scripts/run_neural_strategy.py` sous ces coûts : sa validation peut retenir une autre époque, et c'est alors un autre modèle - ce que produit la procédure de calibration sous un autre coût. Dans chaque variante le Sharpe reste sous celui du fonds détenu et le score sous 50 %.

### Entrées du réseau

Les 319 caractéristiques lues par le réseau à chacune des 453 décisions sont exportées dans `ml1_inputs.csv` (dossier des diagnostics), avec leur statut : 453 décisions ont un vecteur complet. Elles sont reconstruites par le `NeuralFeatureBuilder` du modèle sur un lecteur figé à l'instant de chaque décision.

