# M02 - analyse des mecanismes

Parent : M01. Bloc change : recovery. 

M01 recupere des reprises mais ajoute4dates et augmenteDD. Confirmer le momentum21 positif par MA50 positive plutot que changer le seuil ou le ratio.

Benefice attendu : Filtrer des faux rebonds et reduire les ordres de reprise.

Cout attendu : Reentree plus tardive et risque de sacrifier des rebonds rapides.

Refutation annoncee : Confirmation sans baisse des faux retours/DD/interventions et avec perte nette de croissance; publier toutes ablations.

Comparaisons de vrais parcours continus 2019-2024 ; memes donnees et frais. Les deux niveaux de frais sont reellement simules. Histoire deja exploree.

| Cout | Controle retire/parent | Delta CAGR | Amelioration DD | Delta frais EUR | Delta dates |
| --- | --- | --- | --- | --- | --- |
| x1 | Nasdaq_buy_hold | -3.30 % | 7.90 % | 1508.83 | 23 |
| x1 | parent | 0.15 % | 0.63 % | -525.89 | -2 |
| x1 | without_defensive | 0.20 % | 0.00 % | 389.50 | 3 |
| x1 | without_execution | 0.03 % | -0.00 % | -198.48 | -13 |
| x1 | without_recovery | 0.89 % | 0.00 % | 209.99 | 2 |
| x1 | without_risk | -0.34 % | 4.82 % | -8.22 | 14 |
| x1 | without_trend | -0.70 % | 2.83 % | 951.10 | 4 |
| x2 | Nasdaq_buy_hold | -3.55 % | 7.90 % | 2991.25 | 23 |
| x2 | parent | 0.23 % | 1.10 % | -1038.79 | -2 |
| x2 | without_defensive | 0.14 % | 0.00 % | 760.42 | 3 |
| x2 | without_execution | 0.05 % | 0.03 % | -381.05 | -13 |
| x2 | without_recovery | 0.87 % | 0.00 % | 416.88 | 2 |
| x2 | without_risk | -0.34 % | 4.82 % | -25.08 | 14 |
| x2 | without_trend | -0.83 % | 2.88 % | 1880.77 | 4 |

Une amelioration DD positive signifie une perte maximale reduite. Un delta CAGR negatif est le prix en croissance de cette protection. Les effets conditionnels ne s'additionnent pas.

Les CSV publient tous les regimes, episodes sous 95 % Nasdaq et inputs refuses. Les poids de cloture decrivent l'exposition ; ils ne servent jamais a reconstruire un PnL exact a partir de rendements deja realises. Les regimes de rendement t utilisent seulement le NAV Nasdaq connu a t-1 (126/21 seances, stress 10 %). Les 127 premieres observations restent non classees.

La decision suivante est ecrite separement dans analysis.json par le chercheur. Aucune ablation n'est promue automatiquement.
