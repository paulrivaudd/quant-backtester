# M11 - analyse des mecanismes

Parent : M10. Bloc change : cadence. 

M10 améliore le rendement et le drawdown, mais ses 25 dates d’ordres représentent 4,48 dates par an et 3 750,53 EUR de frais. Modifier uniquement la cadence mensuelle en cadence trimestrielle pour ignorer des changements intermédiaires de votes et de risque.

Benefice attendu : Réduire les vérifications et les transactions, et laisser passer des oscillations courtes des indicateurs sans rechercher une bande numérique optimale.

Cout attendu : Un signal de risque ou un retournement observé après la décision trimestrielle sera traité plus tard ; des pertes et des reprises manquées peuvent augmenter. Une cadence lente ne garantit pas moins de risque.

Refutation annoncee : La réduction des interventions ne compense pas le retard de protection ou de réentrée, notamment si le drawdown dépasse 25 % ou si le rendement net se dégrade fortement.

Comparaisons de vrais parcours continus 2019-2024 ; memes donnees et frais. Les deux niveaux de frais sont reellement simules. Histoire deja exploree.

| Cout | Controle retire/parent | Delta CAGR | Amelioration DD | Delta frais EUR | Delta dates |
| --- | --- | --- | --- | --- | --- |
| x1 | Nasdaq_buy_hold | -5.57 pp | 3.08 pp | 1559.95 | 10 |
| x1 | parent | -5.49 pp | -5.92 pp | -2092.76 | -14 |
| x1 | without_defensive | 1.75 pp | 0.00 pp | 841.58 | 0 |
| x1 | without_execution | -0.05 pp | 0.38 pp | -6.68 | -2 |
| x1 | without_risk | -1.53 pp | 0.00 pp | 183.39 | 2 |
| x1 | without_trend | -2.27 pp | 2.68 pp | 937.14 | 3 |
| x2 | Nasdaq_buy_hold | -5.79 pp | 3.07 pp | 3101.40 | 10 |
| x2 | parent | -5.27 pp | -5.85 pp | -4124.99 | -14 |
| x2 | without_defensive | 1.68 pp | 0.00 pp | 1671.63 | 0 |
| x2 | without_execution | -0.01 pp | 0.38 pp | -13.71 | -2 |
| x2 | without_risk | -1.56 pp | 0.00 pp | 363.10 | 2 |
| x2 | without_trend | -2.36 pp | 2.70 pp | 1866.75 | 3 |

Une amelioration DD positive signifie une perte maximale reduite. Les deltas CAGR/DD sont en points de pourcentage (pp). Un delta CAGR negatif est le prix en croissance de cette protection. Les effets conditionnels ne s'additionnent pas.

Les CSV publient tous les regimes, episodes sous 95 % Nasdaq et inputs refuses. Les poids de cloture decrivent l'exposition ; ils ne servent jamais a reconstruire un PnL exact a partir de rendements deja realises. Les regimes de rendement t utilisent seulement le NAV Nasdaq connu a t-1 (126/21 seances, stress 10 %). Les 127 premieres observations restent non classees.

La decision suivante est ecrite separement dans analysis.json par le chercheur. Aucune ablation n'est promue automatiquement.
