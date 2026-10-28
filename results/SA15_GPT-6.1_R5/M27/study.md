# M27 - analyse des mecanismes

Parent : M26. Bloc change : risk. 

M26 conserve peu d’ordres mais son drawdown atteint 28,333 % : l’arrêt par vitesse ne protège pas suffisamment une position pleine pendant une baisse étalée. Ajouter uniquement le cap_max de volatilité préfixé, pour réduire l’exposition avant qu’un seuil de perte récente soit franchi.

Benefice attendu : Limiter l’exposition dans une chute volatile qui n’active pas le choc fast_loss, et ramener le risque sous la préférence de 25 % de drawdown.

Cout attendu : Le cap peut manquer une partie de la reprise et ajouter des rééquilibrages. Le risque de défense reste entier et aucun prix manquant ne sera réparé.

Refutation annoncee : Le drawdown reste au-dessus de 25 %, ou la protection coûte l’avance nette sur Nasdaq et trop d’interventions. Le seuil de choc et la cible de volatilité sont inchangés.

Comparaisons de vrais parcours continus 2019-2024 ; memes donnees et frais. Les deux niveaux de frais sont reellement simules. Histoire deja exploree.

| Cout | Controle retire/parent | Delta CAGR | Amelioration DD | Delta frais EUR | Delta dates |
| --- | --- | --- | --- | --- | --- |
| x1 | Nasdaq_buy_hold | -0.88 pp | 7.10 pp | 1979.23 | 17 |
| x1 | parent | -1.40 pp | 4.38 pp | 139.45 | 12 |
| x1 | without_defensive | 4.41 pp | -0.80 pp | 1201.67 | 1 |
| x1 | without_execution | 0.36 pp | 0.00 pp | -926.76 | -18 |
| x1 | without_risk | -1.40 pp | 4.38 pp | 139.45 | 12 |
| x1 | without_shock | -0.16 pp | 0.02 pp | 151.64 | 0 |
| x1 | without_trend | 1.34 pp | 0.00 pp | -186.34 | -3 |
| x2 | Nasdaq_buy_hold | -1.20 pp | 7.02 pp | 3922.92 | 17 |
| x2 | parent | -1.48 pp | 4.27 pp | 266.69 | 12 |
| x2 | without_defensive | 4.25 pp | -0.87 pp | 2378.48 | 1 |
| x2 | without_execution | 0.45 pp | 0.00 pp | -1827.75 | -17 |
| x2 | without_risk | -1.48 pp | 4.27 pp | 266.69 | 12 |
| x2 | without_shock | -0.19 pp | -0.02 pp | 300.25 | 0 |
| x2 | without_trend | 1.36 pp | 0.00 pp | -368.33 | -3 |

Une amelioration DD positive signifie une perte maximale reduite. Les deltas CAGR/DD sont en points de pourcentage (pp). Un delta CAGR negatif est le prix en croissance de cette protection. Les effets conditionnels ne s'additionnent pas.

Les CSV publient tous les regimes, episodes sous 95 % Nasdaq et inputs refuses. Les poids de cloture decrivent l'exposition ; ils ne servent jamais a reconstruire un PnL exact a partir de rendements deja realises. Les regimes de rendement t utilisent seulement le NAV Nasdaq connu a t-1 (126/21 seances, stress 10 %). Les 127 premieres observations restent non classees.

La decision suivante est ecrite separement dans analysis.json par le chercheur. Aucune ablation n'est promue automatiquement.
