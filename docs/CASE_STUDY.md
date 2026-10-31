# Étude de cas : pourquoi aucune de mes stratégies ne bat un 50/50 rebalancé

## La question

Les dix règles de timing et d'allocation du classement commun (SA1 à SA11,
SA8 mis à part) font-elles mieux, net de coûts, qu'un panier passif tenu à
moitié dans un fonds Monde (CW8) et à moitié dans un fonds S&P 500 (ESE),
rééquilibré ? SA12 à SA14 ont leurs propres études, hors de ce classement.

## Le protocole

- **Même terrain pour tous** : 2021-04-01 → 2026-10-09 (1 416 valorisations),
  100 000 EUR, commission 5 pb (minimum 1 EUR), demi-spread 3 pb, glissement
  2 pb, quantités fixées à la décision de 23:00 Paris et exécution à
  l'ouverture suivante ([résumé](../results/summary/README.md)).
- **Point-in-time** : une décision ne lit que ce qui était publié à son instant
  ; une fenêtre trouée est refusée, jamais comblée ([architecture](ARCHITECTURE.md)).
- **Coûts doublés** : chaque livre est rejoué une seconde fois, tous les coûts
  multipliés par deux ([`ranking_costs_x2.csv`](../results/summary/ranking_costs_x2.csv)).
- **Sharpe déflaté** : le score `QUALITY_V1` est déflaté par les onze essais de
  l'étude ([protocole](../research/PROTOCOL.md)).

## Les chiffres

Extraits de [`ranking.csv`](../results/summary/ranking.csv) et de
[`ranking_costs_x2.csv`](../results/summary/ranking_costs_x2.csv) :

| Livre | Rendement annualisé | Sharpe | Perte max. | Rendement annualisé, coûts ×2 | Sharpe, coûts ×2 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 50/50 rebalancé (référence) | 13,71 % | 0,96 | −22,47 % | 13,65 % | 0,96 |
| SA6 - vol control | 9,78 % | 0,90 | −15,72 % | 9,55 % | 0,88 |
| SA10 - ensemble | 5,16 % | 0,86 | −11,76 % | 4,80 % | 0,80 |
| SA7 - factor blend | 8,90 % | 0,83 | −16,36 % | 8,59 % | 0,80 |
| SA3 - smooth MA | 8,62 % | 0,79 | −21,64 % | 8,50 % | 0,79 |
| Monde conservé (étalon) | 12,83 % | 0,93 | −21,64 % | 12,79 % | 0,93 |

Le 50/50 est premier du classement (score 77,9 %), devant le meilleur témoin
(53,6 %) et la meilleure stratégie, SA6 (52,0 %).

## L'interprétation

- **Les règles investissent moins.** Exposition moyenne : 84,7 % pour SA6,
  71,5 % pour SA3, 42,4 % pour SA10, contre 99,8 % pour le 50/50
  (`average_exposure`, ranking.csv). Une perte maximale plus faible achetée
  avec du cash n'est pas une compétence ; le protocole l'écrit ainsi : « A lower drawdown
  bought with more cash is exposure, not skill ».
- **Le timing ne bat pas une cible constante.** Contre un témoin qui vise
  leurs poids moyens avec la même bande, SA3 (0,79) et SA10 (0,86) font moins
  bien que le leur (0,93 chacun), et SA6 et SA11 gagnent environ trois points
  de perte maximale pour un Sharpe plus bas
  ([diagnostics](../results/summary/diagnostics.md)).
- **Un meilleur modèle de risque ne suffit pas.** Le GARCH de SA11 prévoit
  mieux la variance que l'estimateur de SA6, mais son Sharpe n'est pas
  au-dessus : intervalles à 95 % de la différence [−0,141 ; +0,076] contre
  SA6 et [−0,147 ; +0,009] contre l'EWMA, et ses coûts sont 2,5 fois ceux
  de SA6 ([SA11/study.md](../results/SA11/study.md)).
- **Les coûts doublés ne renversent rien** : le 50/50 garde son Sharpe de
  0,96 et sa première place ; les règles actives, qui traitent davantage,
  perdent davantage.

## Les limites

Toute la période avait déjà été examinée : ces chiffres sont rétrospectifs,
pas hors échantillon. Deux fonds forment une coupe transversale très mince,
sur une seule période de cinq ans et demi. Les études SA15 et SA16 se
mesurent à d'autres références (Nasdaq-100 conservé, SA15) sur d'autres
fenêtres ; elles ne se lisent pas dans ce tableau
([SA16](../results/SA16/study.md)).

## La suite

La seule preuve restante est le futur : une stratégie gardée en observation
est figée (configuration et magasin), démarre à la première séance qui suit sa
mise à disposition, sans argent réel, et n'est pas lue avant 252 séances
([protocole](../research/PROTOCOL.md), section 6).
