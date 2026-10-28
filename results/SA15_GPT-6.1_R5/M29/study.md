# M29 - analyse des mecanismes

Parent : M20. Bloc change : cadence. 

M20 ne réalise que huit dates de fills sur 68 contrôles mensuels, mais peut attendre plusieurs semaines avant de répondre au choc ou au retournement du momentum. Tester uniquement une cadence hebdomadaire, sans les petits ajustements de volatilité qui rendaient l’ancien essai M05 très actif.

Benefice attendu : Répondre plus tôt aux seuils de choc et aux retournements de tendance, tout en conservant un signal binaire susceptible de rester stable entre deux contrôles.

Cout attendu : Le nombre de soirées de contrôle augmente et des franchissements temporaires peuvent créer davantage de faux retours, de fills et de frais. Aucune amélioration de risque n’est présumée.

Refutation annoncee : Le délai gagné ne compense pas les faux croisements ou les interventions, ou l’avance nette sur Nasdaq se dégrade. La règle hebdomadaire était déclarée avant M01 ; aucun calendrier optimisé par date n’est construit.

Comparaisons de vrais parcours continus 2019-2024 ; memes donnees et frais. Les deux niveaux de frais sont reellement simules. Histoire deja exploree.

| Cout | Controle retire/parent | Delta CAGR | Amelioration DD | Delta frais EUR | Delta dates |
| --- | --- | --- | --- | --- | --- |
| x1 | Nasdaq_buy_hold | -3.97 pp | 5.33 pp | 6049.13 | 17 |
| x1 | parent | -5.31 pp | -3.14 pp | 3674.52 | 10 |
| x1 | without_defensive | 4.45 pp | 3.33 pp | 3459.19 | 1 |
| x1 | without_execution | 2.40 pp | 6.34 pp | -2018.76 | -17 |
| x1 | without_shock | -5.61 pp | 0.21 pp | 2217.60 | 7 |
| x1 | without_trend | -1.97 pp | -0.65 pp | -142.59 | 0 |
| x2 | Nasdaq_buy_hold | -4.70 pp | 4.47 pp | 11871.71 | 17 |
| x2 | parent | -5.73 pp | -3.70 pp | 7162.28 | 10 |
| x2 | without_defensive | 4.05 pp | 3.00 pp | 6742.63 | 1 |
| x2 | without_execution | 2.67 pp | 7.32 pp | -3854.39 | -15 |
| x2 | without_shock | -5.90 pp | -0.51 pp | 4282.62 | 7 |
| x2 | without_trend | -1.96 pp | -0.62 pp | -273.95 | 0 |

Une amelioration DD positive signifie une perte maximale reduite. Les deltas CAGR/DD sont en points de pourcentage (pp). Un delta CAGR negatif est le prix en croissance de cette protection. Les effets conditionnels ne s'additionnent pas.

Les CSV publient tous les regimes, episodes sous 95 % Nasdaq et inputs refuses. Les poids de cloture decrivent l'exposition ; ils ne servent jamais a reconstruire un PnL exact a partir de rendements deja realises. Les regimes de rendement t utilisent seulement le NAV Nasdaq connu a t-1 (126/21 seances, stress 10 %). Les 127 premieres observations restent non classees.

La decision suivante est ecrite separement dans analysis.json par le chercheur. Aucune ablation n'est promue automatiquement.
