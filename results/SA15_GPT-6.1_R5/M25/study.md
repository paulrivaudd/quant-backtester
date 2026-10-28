# M25 - analyse des mecanismes

Parent : M22. Bloc change : risk. 

M22 conserve neuf dates de plus que son contrôle sans risque et abandonne 0,386 point de CAGR pour sa protection. Remplacer uniquement trend_relief par conditional : ne pas limiter le facteur de risque lorsque MA200 et momentum21 sont positifs.

Benefice attendu : Récupérer les phases de hausse confirmée à pleine direction et supprimer des petits relèvements de cible dictés par une volatilité encore élevée.

Cout attendu : Une entrée pleine peut précéder un faux rebond, notamment lorsque la tendance longue reste fragile ; le drawdown peut remonter vers celui de M20.

Refutation annoncee : Le gain de croissance ou d’intervention ne compense pas la protection abandonnée, ou l’avance aux frais doubles disparaît. Aucune constante numérique ne change.

Comparaisons de vrais parcours continus 2019-2024 ; memes donnees et frais. Les deux niveaux de frais sont reellement simules. Histoire deja exploree.

| Cout | Controle retire/parent | Delta CAGR | Amelioration DD | Delta frais EUR | Delta dates |
| --- | --- | --- | --- | --- | --- |
| x1 | Nasdaq_buy_hold | 0.65 pp | 8.47 pp | 2732.74 | 14 |
| x1 | parent | -0.31 pp | -2.48 pp | 426.51 | -2 |
| x1 | without_defensive | 4.27 pp | -1.08 pp | 1629.36 | 1 |
| x1 | without_execution | 0.83 pp | -0.37 pp | -812.22 | -11 |
| x1 | without_risk | -0.69 pp | -0.00 pp | 358.13 | 7 |
| x1 | without_shock | 0.84 pp | 1.39 pp | 408.19 | -1 |
| x1 | without_trend | 1.25 pp | 3.51 pp | -304.39 | -4 |
| x2 | Nasdaq_buy_hold | 0.27 pp | 8.18 pp | 5409.31 | 14 |
| x2 | parent | -0.33 pp | -2.56 pp | 840.73 | -2 |
| x2 | without_defensive | 4.08 pp | -1.10 pp | 3219.42 | 1 |
| x2 | without_execution | 0.93 pp | -0.06 pp | -1586.32 | -10 |
| x2 | without_risk | -0.75 pp | 0.01 pp | 699.87 | 7 |
| x2 | without_shock | 0.77 pp | 1.13 pp | 798.85 | -1 |
| x2 | without_trend | 1.28 pp | 3.75 pp | -599.67 | -4 |

Une amelioration DD positive signifie une perte maximale reduite. Les deltas CAGR/DD sont en points de pourcentage (pp). Un delta CAGR negatif est le prix en croissance de cette protection. Les effets conditionnels ne s'additionnent pas.

Les CSV publient tous les regimes, episodes sous 95 % Nasdaq et inputs refuses. Les poids de cloture decrivent l'exposition ; ils ne servent jamais a reconstruire un PnL exact a partir de rendements deja realises. Les regimes de rendement t utilisent seulement le NAV Nasdaq connu a t-1 (126/21 seances, stress 10 %). Les 127 premieres observations restent non classees.

La decision suivante est ecrite separement dans analysis.json par le chercheur. Aucune ablation n'est promue automatiquement.
