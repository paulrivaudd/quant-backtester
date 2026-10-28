# M14 - analyse des mecanismes

Parent : M13. Bloc change : execution. 

M13 conserve les obligations en août et septembre 2022 malgré un momentum négatif, parce que la cible Nasdaq reste inchangée. Remplacer uniquement hold_defense par band afin que les sorties complètes de la défense soient respectées dès la décision mensuelle suivante.

Benefice attendu : Rétablir la fonction du filtre de momentum défensif et limiter les pertes dues à une position conservée malgré un plan devenu cash ou monétaire.

Cout attendu : Davantage de changements entre défenses et de frais ; le maintien de l’or qui aidait M08 peut également être abandonné. La bande de 10 points reste inchangée.

Refutation annoncee : L’amélioration des épisodes obligataires ne compense pas les coûts et la protection ou la croissance perdue ailleurs ; comparer tous les blocs et conserver les résultats défavorables.

Comparaisons de vrais parcours continus 2019-2024 ; memes donnees et frais. Les deux niveaux de frais sont reellement simules. Histoire deja exploree.

| Cout | Controle retire/parent | Delta CAGR | Amelioration DD | Delta frais EUR | Delta dates |
| --- | --- | --- | --- | --- | --- |
| x1 | Nasdaq_buy_hold | -1.63 pp | 6.99 pp | 3448.06 | 22 |
| x1 | parent | -0.24 pp | 0.43 pp | 118.14 | 4 |
| x1 | without_defensive | 1.35 pp | -0.69 pp | 2181.88 | 4 |
| x1 | without_execution | -0.07 pp | 0.14 pp | -12.82 | -1 |
| x1 | without_trend | -1.63 pp | 6.99 pp | 3448.06 | 22 |
| x2 | Nasdaq_buy_hold | -2.04 pp | 6.25 pp | 6818.02 | 22 |
| x2 | parent | -0.25 pp | 0.18 pp | 230.74 | 4 |
| x2 | without_defensive | 1.11 pp | -1.40 pp | 4300.92 | 4 |
| x2 | without_execution | -0.05 pp | -0.02 pp | -30.53 | -1 |
| x2 | without_trend | -2.04 pp | 6.25 pp | 6818.02 | 22 |

Une amelioration DD positive signifie une perte maximale reduite. Les deltas CAGR/DD sont en points de pourcentage (pp). Un delta CAGR negatif est le prix en croissance de cette protection. Les effets conditionnels ne s'additionnent pas.

Les CSV publient tous les regimes, episodes sous 95 % Nasdaq et inputs refuses. Les poids de cloture decrivent l'exposition ; ils ne servent jamais a reconstruire un PnL exact a partir de rendements deja realises. Les regimes de rendement t utilisent seulement le NAV Nasdaq connu a t-1 (126/21 seances, stress 10 %). Les 127 premieres observations restent non classees.

La decision suivante est ecrite separement dans analysis.json par le chercheur. Aucune ablation n'est promue automatiquement.
