# M05 - analyse des mecanismes

Parent : M03. Bloc change : cadence. 

M03 ameliore le risque conditionnel mais reste sous le Nasdaq et expose seulement80.73% pendant les reprises. Verifier les memes signaux chaque fin de semaine pour isoler le retard calendaire, sans toucher bandes ni seuils.

Benefice attendu : Reagir avant la fin du mois aux baisses et aux retournements, mieux capturer les rebonds.

Cout attendu : Davantage de verifications et de faux changements; frais et dates de transactions potentiellement trop eleves.

Refutation annoncee : La cadence plus rapide ne justifie pas sa croissance/protection par rapport au nombre d'ordres et aux frais doubles.

Comparaisons de vrais parcours continus 2019-2024 ; memes donnees et frais. Les deux niveaux de frais sont reellement simules. Histoire deja exploree.

| Cout | Controle retire/parent | Delta CAGR | Amelioration DD | Delta frais EUR | Delta dates |
| --- | --- | --- | --- | --- | --- |
| x1 | Nasdaq_buy_hold | -3.32 % | 9.07 % | 5287.61 | 45 |
| x1 | parent | -0.92 % | 1.17 % | 3611.35 | 26 |
| x1 | without_defensive | 0.00 % | -0.21 % | 2213.04 | 4 |
| x1 | without_execution | 0.10 % | -0.11 % | -217.38 | -29 |
| x1 | without_recovery | 1.39 % | 1.10 % | 751.59 | 7 |
| x1 | without_risk | -0.99 % | 3.77 % | 675.07 | 28 |
| x1 | without_trend | -1.12 % | 8.71 % | 3258.68 | 1 |
| x2 | Nasdaq_buy_hold | -3.95 % | 8.78 % | 10390.15 | 45 |
| x2 | parent | -1.31 % | 0.89 % | 7060.54 | 26 |
| x2 | without_defensive | -0.21 % | -0.37 % | 4311.57 | 4 |
| x2 | without_execution | 0.14 % | -0.15 % | -416.23 | -29 |
| x2 | without_recovery | 1.31 % | 1.90 % | 1466.41 | 7 |
| x2 | without_risk | -1.04 % | 3.78 % | 1308.78 | 28 |
| x2 | without_trend | -1.49 % | 8.67 % | 6370.90 | 1 |

Une amelioration DD positive signifie une perte maximale reduite. Un delta CAGR negatif est le prix en croissance de cette protection. Les effets conditionnels ne s'additionnent pas.

Les CSV publient tous les regimes, episodes sous 95 % Nasdaq et inputs refuses. Les poids de cloture decrivent l'exposition ; ils ne servent jamais a reconstruire un PnL exact a partir de rendements deja realises. Les regimes de rendement t utilisent seulement le NAV Nasdaq connu a t-1 (126/21 seances, stress 10 %). Les 127 premieres observations restent non classees.

La decision suivante est ecrite separement dans analysis.json par le chercheur. Aucune ablation n'est promue automatiquement.
