# M06 - analyse des mecanismes

Parent : M03. Bloc change : trend. 

M05 montre que verifier plus souvent recupere les reprises mais multiplie les faux ordres. DepuisM03 mensuel, remplacer la sortie binaire sousMA200 par la reserve directionnelle fixe50% deja declaree, avant risque et confirmation.

Benefice attendu : Conserver une participation aux rebonds durant une tendance lente faible, en gardant le cap de risque et la cadence lente.

Cout attendu : Plus de pertes lors des baisses persistantes, drawdown possiblement plus profond; aucun essai d'autres pourcentages.

Refutation annoncee : Le gain de reprise ne compense pas le risque abandonne ou l'ecart Nasdaq;50% est un budget de regime predeclare, pas une ponderation ajustee a chaque date.

Comparaisons de vrais parcours continus 2019-2024 ; memes donnees et frais. Les deux niveaux de frais sont reellement simules. Histoire deja exploree.

| Cout | Controle retire/parent | Delta CAGR | Amelioration DD | Delta frais EUR | Delta dates |
| --- | --- | --- | --- | --- | --- |
| x1 | Nasdaq_buy_hold | -1.98 % | 5.21 % | 1152.17 | 20 |
| x1 | parent | 0.42 % | -2.70 % | -524.09 | 1 |
| x1 | without_defensive | 0.03 % | -0.14 % | 192.98 | 1 |
| x1 | without_execution | -0.02 % | -0.56 % | -81.23 | -11 |
| x1 | without_recovery | 0.21 % | -1.70 % | 98.19 | 3 |
| x1 | without_risk | -0.67 % | 2.13 % | 328.81 | 11 |
| x1 | without_trend | -0.49 % | 3.51 % | 461.25 | 2 |
| x2 | Nasdaq_buy_hold | -2.14 % | 5.02 % | 2291.84 | 20 |
| x2 | parent | 0.50 % | -2.88 % | -1037.77 | 1 |
| x2 | without_defensive | 0.01 % | -0.19 % | 383.38 | 1 |
| x2 | without_execution | -0.00 % | -0.50 % | -168.43 | -11 |
| x2 | without_recovery | 0.20 % | -1.69 % | 195.92 | 3 |
| x2 | without_risk | -0.73 % | 1.94 % | 653.41 | 11 |
| x2 | without_trend | -0.56 % | 3.39 % | 923.12 | 2 |

Une amelioration DD positive signifie une perte maximale reduite. Un delta CAGR negatif est le prix en croissance de cette protection. Les effets conditionnels ne s'additionnent pas.

Les CSV publient tous les regimes, episodes sous 95 % Nasdaq et inputs refuses. Les poids de cloture decrivent l'exposition ; ils ne servent jamais a reconstruire un PnL exact a partir de rendements deja realises. Les regimes de rendement t utilisent seulement le NAV Nasdaq connu a t-1 (126/21 seances, stress 10 %). Les 127 premieres observations restent non classees.

La decision suivante est ecrite separement dans analysis.json par le chercheur. Aucune ablation n'est promue automatiquement.
