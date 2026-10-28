# M13 - analyse des mecanismes

Parent : M12. Bloc change : defensive. 

M12 conserve un cash moyen de 14,71 % pendant les baisses et une défense concentrée sur l’or. Remplacer uniquement gold_momentum par dual_defense : choisir le meilleur momentum positif à 63 séances entre l’or et les obligations souveraines mondiales couvertes en EUR, déjà dans l’univers figé.

Benefice attendu : Offrir une défense investissable lorsque l’or est faible et que les obligations sont orientées positivement, et réduire la dépendance à un seul marché défensif.

Cout attendu : Les obligations peuvent perdre avec les actions et l’or, notamment lors d’un choc de taux ; le choix relatif ajoute des signaux, des rotations et du risque non plafonné par le contrôle Nasdaq. Le maintien de défense peut ignorer certains changements de classement.

Refutation annoncee : L’alternative obligataire n’améliore ni rendement ni protection, reste inactive, ou augmente les interventions et le drawdown sans compensation nette. Les scores et horizons restent identiques, sans poids optimisés.

Comparaisons de vrais parcours continus 2019-2024 ; memes donnees et frais. Les deux niveaux de frais sont reellement simules. Histoire deja exploree.

| Cout | Controle retire/parent | Delta CAGR | Amelioration DD | Delta frais EUR | Delta dates |
| --- | --- | --- | --- | --- | --- |
| x1 | Nasdaq_buy_hold | -1.39 pp | 6.56 pp | 3329.92 | 18 |
| x1 | parent | -1.11 pp | -0.43 pp | 171.07 | 0 |
| x1 | without_defensive | 1.59 pp | -1.12 pp | 2063.74 | 0 |
| x1 | without_execution | 0.17 pp | -0.28 pp | -130.96 | -5 |
| x1 | without_trend | -1.39 pp | 6.56 pp | 3329.92 | 18 |
| x2 | Nasdaq_buy_hold | -1.79 pp | 6.07 pp | 6587.29 | 18 |
| x2 | parent | -1.14 pp | -0.86 pp | 329.33 | 0 |
| x2 | without_defensive | 1.36 pp | -1.58 pp | 4070.18 | 0 |
| x2 | without_execution | 0.20 pp | -0.21 pp | -261.27 | -5 |
| x2 | without_trend | -1.79 pp | 6.07 pp | 6587.29 | 18 |

Une amelioration DD positive signifie une perte maximale reduite. Les deltas CAGR/DD sont en points de pourcentage (pp). Un delta CAGR negatif est le prix en croissance de cette protection. Les effets conditionnels ne s'additionnent pas.

Les CSV publient tous les regimes, episodes sous 95 % Nasdaq et inputs refuses. Les poids de cloture decrivent l'exposition ; ils ne servent jamais a reconstruire un PnL exact a partir de rendements deja realises. Les regimes de rendement t utilisent seulement le NAV Nasdaq connu a t-1 (126/21 seances, stress 10 %). Les 127 premieres observations restent non classees.

La decision suivante est ecrite separement dans analysis.json par le chercheur. Aucune ablation n'est promue automatiquement.
