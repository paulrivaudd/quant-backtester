# M03 - analyse des mecanismes

Parent : M02. Bloc change : risk. 

M02 confirme mieux la reprise mais le cap20/60 ajoute14dates et limite l'exposition. Modifier seulement le cap pour le suspendre quand MA200 ET momentum21 sont positifs.

Benefice attendu : Maintenir100% quand la hausse est confirmee, reduire les petits reajustements et recuperer du rendement.

Cout attendu : Protection abandonnee avant certains chocs en regime encore positif; verifier drawdown et faux regimes.

Refutation annoncee : Gain trop faible ou drawdown excessif/interventions non reduites; capmax reste controle de reference sans changer la cible20%.

Comparaisons de vrais parcours continus 2019-2024 ; memes donnees et frais. Les deux niveaux de frais sont reellement simules. Histoire deja exploree.

| Cout | Controle retire/parent | Delta CAGR | Amelioration DD | Delta frais EUR | Delta dates |
| --- | --- | --- | --- | --- | --- |
| x1 | Nasdaq_buy_hold | -2.39 % | 7.90 % | 1676.26 | 19 |
| x1 | parent | 0.91 % | 0.00 % | 167.43 | -4 |
| x1 | without_defensive | 0.04 % | 0.00 % | 326.07 | 1 |
| x1 | without_execution | 0.12 % | -0.00 % | -72.67 | -7 |
| x1 | without_recovery | 0.88 % | 0.00 % | 218.94 | 3 |
| x1 | without_risk | 0.56 % | 4.82 % | 159.21 | 10 |
| x1 | without_trend | -0.90 % | 6.21 % | 985.34 | 1 |
| x2 | Nasdaq_buy_hold | -2.65 % | 7.90 % | 3329.61 | 19 |
| x2 | parent | 0.90 % | 0.00 % | 338.36 | -4 |
| x2 | without_defensive | 0.01 % | 0.06 % | 645.78 | 1 |
| x2 | without_execution | 0.17 % | 0.03 % | -140.89 | -7 |
| x2 | without_recovery | 0.83 % | 0.10 % | 432.98 | 3 |
| x2 | without_risk | 0.56 % | 4.82 % | 313.28 | 10 |
| x2 | without_trend | -1.06 % | 6.27 % | 1960.89 | 1 |

Une amelioration DD positive signifie une perte maximale reduite. Un delta CAGR negatif est le prix en croissance de cette protection. Les effets conditionnels ne s'additionnent pas.

Les CSV publient tous les regimes, episodes sous 95 % Nasdaq et inputs refuses. Les poids de cloture decrivent l'exposition ; ils ne servent jamais a reconstruire un PnL exact a partir de rendements deja realises. Les regimes de rendement t utilisent seulement le NAV Nasdaq connu a t-1 (126/21 seances, stress 10 %). Les 127 premieres observations restent non classees.

La decision suivante est ecrite separement dans analysis.json par le chercheur. Aucune ablation n'est promue automatiquement.
