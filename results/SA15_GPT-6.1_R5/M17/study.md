# M17 - analyse des mecanismes

Parent : M10. Bloc change : risk. 

M16 montre qu’un filtre mondial trop large abandonne des reprises rentables. Sur M10, le consensus limite déjà la direction et inclut MA200, tandis que le cap n’est suspendu que si MA200 et momentum21 sont positifs. Remplacer uniquement conditional par negative_only : appliquer le cap lorsque momentum21 est non positif, et conserver la fraction directionnelle lorsque le momentum court est positif.

Benefice attendu : Éviter d’utiliser deux fois la faiblesse de MA200 contre une reprise, sans restaurer automatiquement toute la direction ni exiger des marchés émergents haussiers. Les votes longs continuent à limiter l’exposition.

Cout attendu : Un rebond court positif dans un marché baissier relâche la protection de volatilité ; les pertes après faux rebond peuvent donc augmenter. Ce mécanisme ne mesure pas la semivariance et ne garantit aucun niveau de risque.

Refutation annoncee : Les reprises récupérées ne compensent pas la protection abandonnée ou le drawdown dépasse 25 %, ou les interventions restent excessives. Aucun horizon, cible de volatilité ou seuil n’est modifié.

Comparaisons de vrais parcours continus 2019-2024 ; memes donnees et frais. Les deux niveaux de frais sont reellement simules. Histoire deja exploree.

| Cout | Controle retire/parent | Delta CAGR | Amelioration DD | Delta frais EUR | Delta dates |
| --- | --- | --- | --- | --- | --- |
| x1 | Nasdaq_buy_hold | -0.22 pp | 8.99 pp | 3648.26 | 24 |
| x1 | parent | -0.15 pp | 0.00 pp | -4.45 | 0 |
| x1 | without_defensive | 3.28 pp | -1.41 pp | 2196.48 | 0 |
| x1 | without_execution | 0.83 pp | -0.00 pp | -135.56 | -11 |
| x1 | without_risk | 0.05 pp | 2.01 pp | 489.41 | 6 |
| x1 | without_trend | 0.04 pp | 6.87 pp | 2199.78 | 4 |
| x2 | Nasdaq_buy_hold | -0.66 pp | 8.93 pp | 7207.48 | 24 |
| x2 | parent | -0.15 pp | 0.00 pp | -18.90 | 0 |
| x2 | without_defensive | 3.03 pp | -1.20 pp | 4323.72 | 0 |
| x2 | without_execution | 0.87 pp | -0.00 pp | -249.18 | -9 |
| x2 | without_risk | -0.02 pp | 2.00 pp | 949.53 | 6 |
| x2 | without_trend | -0.22 pp | 7.05 pp | 4329.03 | 4 |

Une amelioration DD positive signifie une perte maximale reduite. Les deltas CAGR/DD sont en points de pourcentage (pp). Un delta CAGR negatif est le prix en croissance de cette protection. Les effets conditionnels ne s'additionnent pas.

Les CSV publient tous les regimes, episodes sous 95 % Nasdaq et inputs refuses. Les poids de cloture decrivent l'exposition ; ils ne servent jamais a reconstruire un PnL exact a partir de rendements deja realises. Les regimes de rendement t utilisent seulement le NAV Nasdaq connu a t-1 (126/21 seances, stress 10 %). Les 127 premieres observations restent non classees.

La decision suivante est ecrite separement dans analysis.json par le chercheur. Aucune ablation n'est promue automatiquement.
