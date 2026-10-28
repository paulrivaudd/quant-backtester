# M26 - analyse des mecanismes

Parent : M20. Bloc change : shock. 

M20 garde un choc lorsque le prix est à plus de 10 % de son sommet de 63 séances, même si la vitesse de perte ralentit. Remplacer uniquement drawdown par fast_loss : arrêt lorsque le momentum à 21 séances est inférieur ou égal à −8 %, seuil fixé avant M01.

Benefice attendu : Permettre une réentrée après stabilisation de la perte récente sans attendre de revenir près de l’ancien sommet, et réduire des périodes de repli prolongé.

Cout attendu : Une baisse étalée peut rester grave sans dépasser la perte récente de 8 %. Par exemple, les pertes de février et mars 2020 sont connues autour de −7,6 % et −6,4 % sur 21 séances : le nouveau signal peut manquer la protection initiale. Toutes ces occurrences seront conservées.

Refutation annoncee : La reprise récupérée ne compense pas la baisse de protection, notamment si le drawdown dépasse 25 % ou si l’avance nette sur Nasdaq disparaît. Aucun seuil ni horizon n’est adapté aux épisodes.

Comparaisons de vrais parcours continus 2019-2024 ; memes donnees et frais. Les deux niveaux de frais sont reellement simules. Histoire deja exploree.

| Cout | Controle retire/parent | Delta CAGR | Amelioration DD | Delta frais EUR | Delta dates |
| --- | --- | --- | --- | --- | --- |
| x1 | Nasdaq_buy_hold | 0.52 pp | 2.72 pp | 1839.77 | 5 |
| x1 | parent | -0.82 pp | -5.76 pp | -534.84 | -2 |
| x1 | without_defensive | 2.83 pp | 0.03 pp | 1100.89 | 1 |
| x1 | without_execution | 0.71 pp | 0.00 pp | -750.66 | -5 |
| x1 | without_shock | 0.87 pp | -0.36 pp | 247.22 | 1 |
| x1 | without_trend | 1.26 pp | 0.00 pp | 122.22 | 0 |
| x2 | Nasdaq_buy_hold | 0.28 pp | 2.75 pp | 3656.22 | 5 |
| x2 | parent | -0.74 pp | -5.42 pp | -1053.21 | -2 |
| x2 | without_defensive | 2.71 pp | -0.01 pp | 2185.03 | 1 |
| x2 | without_execution | 0.79 pp | 0.00 pp | -1479.16 | -4 |
| x2 | without_shock | 0.80 pp | -0.33 pp | 483.64 | 1 |
| x2 | without_trend | 1.26 pp | 0.00 pp | 241.46 | 0 |

Une amelioration DD positive signifie une perte maximale reduite. Les deltas CAGR/DD sont en points de pourcentage (pp). Un delta CAGR negatif est le prix en croissance de cette protection. Les effets conditionnels ne s'additionnent pas.

Les CSV publient tous les regimes, episodes sous 95 % Nasdaq et inputs refuses. Les poids de cloture decrivent l'exposition ; ils ne servent jamais a reconstruire un PnL exact a partir de rendements deja realises. Les regimes de rendement t utilisent seulement le NAV Nasdaq connu a t-1 (126/21 seances, stress 10 %). Les 127 premieres observations restent non classees.

La decision suivante est ecrite separement dans analysis.json par le chercheur. Aucune ablation n'est promue automatiquement.
