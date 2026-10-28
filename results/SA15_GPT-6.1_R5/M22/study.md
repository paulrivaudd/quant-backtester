# M22 - analyse des mecanismes

Parent : M21. Bloc change : risk. 

M21 réduit le drawdown mais coûte un point de CAGR et dix dates ; quatre décisions restent sous 75 % Nasdaq malgré MA50 et momentum21 positifs, notamment avril et mai 2020. Remplacer uniquement cap_max par trend_relief : conserver le cap normal, mais relever son facteur au plancher fixe de 75 % quand ces deux confirmations sont positives.

Benefice attendu : Rétablir une exposition significative dans une reprise confirmée sans attendre que la volatilité longue ait entièrement baissé, et limiter des petits ajustements de risque pendant cette phase.

Cout attendu : Relâcher le cap quand des prix remontent peut perdre davantage dans un faux rebond. Le plancher de 75 % est une constante numérique figée avant M01, pas un poids optimisé pour une date ni une allocation permanente.

Refutation annoncee : Le rendement de reprise récupéré ne compense pas le drawdown ou les interventions supplémentaires, ou l’avance nette sur Nasdaq reste trop fragile. Aucun voisinage de planchers ou de seuils n’est recherché.

Comparaisons de vrais parcours continus 2019-2024 ; memes donnees et frais. Les deux niveaux de frais sont reellement simules. Histoire deja exploree.

| Cout | Controle retire/parent | Delta CAGR | Amelioration DD | Delta frais EUR | Delta dates |
| --- | --- | --- | --- | --- | --- |
| x1 | Nasdaq_buy_hold | 0.95 pp | 10.95 pp | 2306.23 | 16 |
| x1 | parent | 0.62 pp | -0.20 pp | 59.01 | -1 |
| x1 | without_defensive | 4.82 pp | -2.50 pp | 1388.70 | 1 |
| x1 | without_execution | 0.57 pp | -0.38 pp | -1014.48 | -19 |
| x1 | without_risk | -0.39 pp | 2.48 pp | -68.38 | 9 |
| x1 | without_shock | 0.84 pp | 3.87 pp | 406.29 | -1 |
| x1 | without_trend | 1.39 pp | 4.02 pp | -418.29 | -3 |
| x2 | Nasdaq_buy_hold | 0.61 pp | 10.74 pp | 4568.58 | 16 |
| x2 | parent | 0.59 pp | -0.19 pp | 110.70 | -1 |
| x2 | without_defensive | 4.64 pp | -2.47 pp | 2744.81 | 1 |
| x2 | without_execution | 0.66 pp | -0.06 pp | -1983.77 | -18 |
| x2 | without_risk | -0.42 pp | 2.57 pp | -140.86 | 9 |
| x2 | without_shock | 0.73 pp | 3.70 pp | 795.56 | -1 |
| x2 | without_trend | 1.41 pp | 4.34 pp | -828.10 | -3 |

Une amelioration DD positive signifie une perte maximale reduite. Les deltas CAGR/DD sont en points de pourcentage (pp). Un delta CAGR negatif est le prix en croissance de cette protection. Les effets conditionnels ne s'additionnent pas.

Les CSV publient tous les regimes, episodes sous 95 % Nasdaq et inputs refuses. Les poids de cloture decrivent l'exposition ; ils ne servent jamais a reconstruire un PnL exact a partir de rendements deja realises. Les regimes de rendement t utilisent seulement le NAV Nasdaq connu a t-1 (126/21 seances, stress 10 %). Les 127 premieres observations restent non classees.

La decision suivante est ecrite separement dans analysis.json par le chercheur. Aucune ablation n'est promue automatiquement.
