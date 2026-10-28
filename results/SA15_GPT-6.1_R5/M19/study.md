# M19 - analyse des mecanismes

Parent : M18. Bloc change : risk. 

Sur M18, l’ablation du risque déjà observée donne environ 24,474 % de CAGR et 19,234 % de drawdown avec 18 dates, contre 23,863 %, 19,237 % et 24 dates. Le cap coûte du rendement et des interventions sans protection supplémentaire à frais normaux. Promouvoir explicitement ce contrôle en candidat sans cap, en conservant le consensus et l’arrêt de choc.

Benefice attendu : Supprimer un mécanisme redondant qui freine les reprises et réduit le nombre d’ordres ; garder la direction graduée et le choc comme protections quantitatives.

Cout attendu : La volatilité ne sera plus plafonnée entre deux déclenchements de choc et le résultat historique de cette ablation est déjà connu. Un choc après un régime calme ou une reprise avortée peut alors coûter davantage.

Refutation annoncee : Les contrôles restants révèlent une protection insuffisante ou une supériorité qui disparaît aux frais doubles ; l’objectif de faible intervention reste appliqué. Cette promotion est comptée comme design et ne constitue pas une confirmation indépendante.

Comparaisons de vrais parcours continus 2019-2024 ; memes donnees et frais. Les deux niveaux de frais sont reellement simules. Histoire deja exploree.

| Cout | Controle retire/parent | Delta CAGR | Amelioration DD | Delta frais EUR | Delta dates |
| --- | --- | --- | --- | --- | --- |
| x1 | Nasdaq_buy_hold | 0.60 pp | 11.82 pp | 3634.49 | 17 |
| x1 | parent | 0.61 pp | 0.00 pp | -257.48 | -6 |
| x1 | without_defensive | 4.88 pp | 1.03 pp | 2355.01 | 1 |
| x1 | without_execution | 0.75 pp | 2.81 pp | -92.28 | -5 |
| x1 | without_shock | 0.88 pp | 4.83 pp | 475.64 | -1 |
| x1 | without_trend | 1.02 pp | 9.41 pp | 990.83 | 8 |
| x2 | Nasdaq_buy_hold | 0.16 pp | 11.27 pp | 7176.72 | 17 |
| x2 | parent | 0.70 pp | -0.39 pp | -499.10 | -6 |
| x2 | without_defensive | 4.61 pp | 0.76 pp | 4634.72 | 1 |
| x2 | without_execution | 0.78 pp | 2.88 pp | -188.24 | -5 |
| x2 | without_shock | 0.80 pp | 4.34 pp | 918.76 | -1 |
| x2 | without_trend | 0.97 pp | 9.45 pp | 1938.05 | 8 |

Une amelioration DD positive signifie une perte maximale reduite. Les deltas CAGR/DD sont en points de pourcentage (pp). Un delta CAGR negatif est le prix en croissance de cette protection. Les effets conditionnels ne s'additionnent pas.

Les CSV publient tous les regimes, episodes sous 95 % Nasdaq et inputs refuses. Les poids de cloture decrivent l'exposition ; ils ne servent jamais a reconstruire un PnL exact a partir de rendements deja realises. Les regimes de rendement t utilisent seulement le NAV Nasdaq connu a t-1 (126/21 seances, stress 10 %). Les 127 premieres observations restent non classees.

La decision suivante est ecrite separement dans analysis.json par le chercheur. Aucune ablation n'est promue automatiquement.
