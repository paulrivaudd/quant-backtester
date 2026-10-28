# M08 - analyse des mecanismes

Parent : M07. Bloc change : execution. 

M07 rend le repli productif mais ajoute15fills et1411EUR de frais vsM03; des alternances or/cash surviennent avec Nasdaq toujours nul. Tester uniquement hold_defense, qui ignore les changements de seule defense si le poidscore demeure dans sa bande.

Benefice attendu : Reduire les operations entre defenses sans retarder les sorties completes Nasdaq et conserver une protection simple avec moins d'interventions.

Cout attendu : Conserver l'or apres momentumdefensif negatif peut accroitre drawdown et sacrifier le gain du filtre de defense; aucune reduction arbitraire des frais apres coup.

Refutation annoncee : Ordres/frais non reduits ou drawdown au-dessus25% ou perte de croissance non compensee; les memes bandes numeriques restent figees.

Comparaisons de vrais parcours continus 2019-2024 ; memes donnees et frais. Les deux niveaux de frais sont reellement simules. Histoire deja exploree.

| Cout | Controle retire/parent | Delta CAGR | Amelioration DD | Delta frais EUR | Delta dates |
| --- | --- | --- | --- | --- | --- |
| x1 | Nasdaq_buy_hold | -0.67 pp | 7.08 pp | 3095.64 | 19 |
| x1 | parent | 0.16 pp | 0.00 pp | 8.22 | -1 |
| x1 | without_defensive | 1.76 pp | -0.82 pp | 1745.45 | 1 |
| x1 | without_execution | 0.32 pp | -0.00 pp | -81.80 | -8 |
| x1 | without_recovery | 0.07 pp | 0.00 pp | 651.40 | 4 |
| x1 | without_risk | 1.07 pp | 4.00 pp | 506.33 | 10 |
| x1 | without_trend | -0.39 pp | 3.29 pp | 1831.81 | 2 |
| x2 | Nasdaq_buy_hold | -1.10 pp | 7.04 pp | 6118.90 | 19 |
| x2 | parent | 0.16 pp | 0.00 pp | 17.05 | -1 |
| x2 | without_defensive | 1.56 pp | -0.79 pp | 3435.07 | 1 |
| x2 | without_execution | 0.33 pp | -0.00 pp | -161.03 | -8 |
| x2 | without_recovery | -0.01 pp | 0.00 pp | 1278.78 | 4 |
| x2 | without_risk | 0.99 pp | 3.97 pp | 984.87 | 10 |
| x2 | without_trend | -0.65 pp | 3.43 pp | 3606.00 | 2 |

Une amelioration DD positive signifie une perte maximale reduite. Les deltas CAGR/DD sont en points de pourcentage (pp). Un delta CAGR negatif est le prix en croissance de cette protection. Les effets conditionnels ne s'additionnent pas.

Les CSV publient tous les regimes, episodes sous 95 % Nasdaq et inputs refuses. Les poids de cloture decrivent l'exposition ; ils ne servent jamais a reconstruire un PnL exact a partir de rendements deja realises. Les regimes de rendement t utilisent seulement le NAV Nasdaq connu a t-1 (126/21 seances, stress 10 %). Les 127 premieres observations restent non classees.

La decision suivante est ecrite separement dans analysis.json par le chercheur. Aucune ablation n'est promue automatiquement.
