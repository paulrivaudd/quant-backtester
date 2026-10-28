# M23 - analyse des mecanismes

Parent : M22. Bloc change : execution. 

M22 conserve une bonne protection mais compte encore neuf dates de plus que son ablation du risque. Remplacer uniquement hold_defense par asymmetric : les petites augmentations de cible attendent la bande d’entrée fixe de 20 points, tandis que les réductions utilisent la bande fixe de 5 points.

Benefice attendu : Éviter des réinvestissements intermédiaires quand la volatilité se détend par petits pas, tout en répondant plus vite aux nouvelles réductions de risque ; aucune recherche de bande optimale n’est conduite.

Cout attendu : Une réentrée retardée peut manquer la hausse et les réductions plus sensibles peuvent multiplier les ordres. Le remplacement abandonne aussi le maintien d’une défense quand seul son classement change ; des rotations défensives supplémentaires sont possibles.

Refutation annoncee : Les interventions ne baissent pas ou la croissance perdue ne justifie pas la protection ; publier tous les effets, y compris ceux des sorties de défense. Les bandes numériques restent celles inscrites avant M01.

Comparaisons de vrais parcours continus 2019-2024 ; memes donnees et frais. Les deux niveaux de frais sont reellement simules. Histoire deja exploree.

| Cout | Controle retire/parent | Delta CAGR | Amelioration DD | Delta frais EUR | Delta dates |
| --- | --- | --- | --- | --- | --- |
| x1 | Nasdaq_buy_hold | -0.22 pp | 11.36 pp | 3075.21 | 22 |
| x1 | parent | -1.18 pp | 0.41 pp | 768.99 | 6 |
| x1 | without_defensive | 5.35 pp | -2.20 pp | 2284.95 | 11 |
| x1 | without_execution | -0.60 pp | 0.03 pp | -245.50 | -13 |
| x1 | without_risk | -0.86 pp | 2.50 pp | -73.67 | 12 |
| x1 | without_shock | 0.77 pp | 4.28 pp | 427.52 | 0 |
| x1 | without_trend | 0.48 pp | 4.46 pp | 353.52 | -1 |
| x2 | Nasdaq_buy_hold | -0.63 pp | 10.80 pp | 6092.65 | 22 |
| x2 | parent | -1.23 pp | 0.06 pp | 1524.07 | 6 |
| x2 | without_defensive | 5.06 pp | -2.53 pp | 4518.21 | 11 |
| x2 | without_execution | -0.57 pp | 0.01 pp | -459.70 | -12 |
| x2 | without_risk | -0.83 pp | 2.57 pp | -139.33 | 12 |
| x2 | without_shock | 0.69 pp | 3.76 pp | 849.27 | 0 |
| x2 | without_trend | 0.46 pp | 4.39 pp | 699.27 | -1 |

Une amelioration DD positive signifie une perte maximale reduite. Les deltas CAGR/DD sont en points de pourcentage (pp). Un delta CAGR negatif est le prix en croissance de cette protection. Les effets conditionnels ne s'additionnent pas.

Les CSV publient tous les regimes, episodes sous 95 % Nasdaq et inputs refuses. Les poids de cloture decrivent l'exposition ; ils ne servent jamais a reconstruire un PnL exact a partir de rendements deja realises. Les regimes de rendement t utilisent seulement le NAV Nasdaq connu a t-1 (126/21 seances, stress 10 %). Les 127 premieres observations restent non classees.

La decision suivante est ecrite separement dans analysis.json par le chercheur. Aucune ablation n'est promue automatiquement.
