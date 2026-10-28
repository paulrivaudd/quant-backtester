# M04 - analyse des mecanismes

Parent : M02. Bloc change : risk. 

M03 montre qu'alleger le cap dans les hausses confirmees recupere du rendement. Alternative isolee depuisM02 : remplacer max(vol20,vol60) par vol20, pour tester directement la traine60 apres choc, cible20% inchangee.

Benefice attendu : Restaurer l'exposition plus vite quand la volatilite recente se calme, sans condition de tendance qui supprime tout cap.

Cout attendu : Sous-estimer une nouvelle vague baissiere, varier davantage avec le bruit de vol20.

Refutation annoncee : Pas de recuperation nette des reprises ou hausse excessive du DD et des ordres; aucune recherche d'un autre nombre de seances.

Comparaisons de vrais parcours continus 2019-2024 ; memes donnees et frais. Les deux niveaux de frais sont reellement simules. Histoire deja exploree.

| Cout | Controle retire/parent | Delta CAGR | Amelioration DD | Delta frais EUR | Delta dates |
| --- | --- | --- | --- | --- | --- |
| x1 | Nasdaq_buy_hold | -3.09 % | 7.90 % | 1801.56 | 26 |
| x1 | parent | 0.21 % | 0.00 % | 292.73 | 3 |
| x1 | without_defensive | 0.07 % | 0.00 % | 384.67 | 2 |
| x1 | without_execution | 0.09 % | -0.00 % | -38.22 | -8 |
| x1 | without_recovery | 0.70 % | 0.00 % | 385.69 | 4 |
| x1 | without_risk | -0.14 % | 4.82 % | 284.51 | 17 |
| x1 | without_trend | -0.50 % | 5.22 % | 1057.55 | 3 |
| x2 | Nasdaq_buy_hold | -3.35 % | 7.90 % | 3573.42 | 26 |
| x2 | parent | 0.20 % | 0.00 % | 582.16 | 3 |
| x2 | without_defensive | 0.01 % | 0.00 % | 757.43 | 2 |
| x2 | without_execution | 0.10 % | 0.03 % | -73.61 | -8 |
| x2 | without_recovery | 0.64 % | 0.00 % | 757.54 | 4 |
| x2 | without_risk | -0.15 % | 4.82 % | 557.09 | 17 |
| x2 | without_trend | -0.62 % | 5.31 % | 2095.17 | 3 |

Une amelioration DD positive signifie une perte maximale reduite. Un delta CAGR negatif est le prix en croissance de cette protection. Les effets conditionnels ne s'additionnent pas.

Les CSV publient tous les regimes, episodes sous 95 % Nasdaq et inputs refuses. Les poids de cloture decrivent l'exposition ; ils ne servent jamais a reconstruire un PnL exact a partir de rendements deja realises. Les regimes de rendement t utilisent seulement le NAV Nasdaq connu a t-1 (126/21 seances, stress 10 %). Les 127 premieres observations restent non classees.

La decision suivante est ecrite separement dans analysis.json par le chercheur. Aucune ablation n'est promue automatiquement.
