# M21 - analyse des mecanismes

Parent : M20. Bloc change : risk. 

M20 améliore le rendement et réduit fortement les ordres, mais son drawdown passe de 19,234 % à 22,574 % à cause de la perte de graduation directionnelle. Ajouter uniquement le contrôle de volatilité cap_max déjà défini, cible 20 % et maximum des estimations 20/60 séances, pour mesurer la protection des entrées pleines dans ce contexte précis.

Benefice attendu : Réduire les pertes quand une tendance longue positive autorise encore une entrée complète mais que le risque récent est élevé ; mesurer si cette protection s’ajoute réellement à celle du choc.

Cout attendu : La volatilité passée peut rester forte pendant une reprise et empêcher de réinvestir pleinement ; le dimensionnement crée aussi des ajustements supplémentaires et leurs frais. Le risque défensif reste hors de ce cap Nasdaq.

Refutation annoncee : La protection marginale ne justifie pas la croissance abandonnée ou le nombre d’ordres, notamment si l’avance sur le Nasdaq disparaît aux frais doubles. Les fenêtres et la cible restent celles figées avant M01.

Comparaisons de vrais parcours continus 2019-2024 ; memes donnees et frais. Les deux niveaux de frais sont reellement simules. Histoire deja exploree.

| Cout | Controle retire/parent | Delta CAGR | Amelioration DD | Delta frais EUR | Delta dates |
| --- | --- | --- | --- | --- | --- |
| x1 | Nasdaq_buy_hold | 0.33 pp | 11.16 pp | 2247.21 | 17 |
| x1 | parent | -1.01 pp | 2.68 pp | -127.40 | 10 |
| x1 | without_defensive | 5.03 pp | -2.46 pp | 1362.16 | 1 |
| x1 | without_execution | 0.52 pp | -0.36 pp | -973.64 | -18 |
| x1 | without_risk | -1.01 pp | 2.68 pp | -127.40 | 10 |
| x1 | without_shock | 1.05 pp | 4.08 pp | 419.63 | 0 |
| x1 | without_trend | 1.27 pp | 3.66 pp | -412.62 | -3 |
| x2 | Nasdaq_buy_hold | 0.02 pp | 10.93 pp | 4457.87 | 17 |
| x2 | parent | -1.01 pp | 2.76 pp | -251.56 | 10 |
| x2 | without_defensive | 4.81 pp | -2.45 pp | 2695.04 | 1 |
| x2 | without_execution | 0.66 pp | -0.07 pp | -1890.93 | -17 |
| x2 | without_risk | -1.01 pp | 2.76 pp | -251.56 | 10 |
| x2 | without_shock | 1.03 pp | 3.89 pp | 835.20 | 0 |
| x2 | without_trend | 1.32 pp | 3.99 pp | -815.23 | -3 |

Une amelioration DD positive signifie une perte maximale reduite. Les deltas CAGR/DD sont en points de pourcentage (pp). Un delta CAGR negatif est le prix en croissance de cette protection. Les effets conditionnels ne s'additionnent pas.

Les CSV publient tous les regimes, episodes sous 95 % Nasdaq et inputs refuses. Les poids de cloture decrivent l'exposition ; ils ne servent jamais a reconstruire un PnL exact a partir de rendements deja realises. Les regimes de rendement t utilisent seulement le NAV Nasdaq connu a t-1 (126/21 seances, stress 10 %). Les 127 premieres observations restent non classees.

La decision suivante est ecrite separement dans analysis.json par le chercheur. Aucune ablation n'est promue automatiquement.
