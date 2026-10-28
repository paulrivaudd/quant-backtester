# M28 - analyse des mecanismes

Parent : M27. Bloc change : shock. 

L’ablation du choc fast_loss de M27 est déjà connue : le bloc coûte 0,158 point de CAGR pour 0,015 point de protection et aucune date évitée. Promouvoir explicitement ce contrôle en candidat sans choc, avec le même cap, pour supprimer une condition redondante.

Benefice attendu : Simplifier la stratégie et supprimer des sorties de choc dont le cap a déjà absorbé le risque, sans modifier les poids par date ni les paramètres.

Cout attendu : Un choc soudain peut dépasser une estimation de volatilité encore faible ; l’absence de seuil de perte supprime cette seconde protection. Le résultat historique d’ablation est déjà connu.

Refutation annoncee : La protection marginale abandonnée n’est pas acceptable ou les autres contrôles montrent un bloc indispensable. Cette promotion compte comme design observé et n’est pas une validation indépendante.

Comparaisons de vrais parcours continus 2019-2024 ; memes donnees et frais. Les deux niveaux de frais sont reellement simules. Histoire deja exploree.

| Cout | Controle retire/parent | Delta CAGR | Amelioration DD | Delta frais EUR | Delta dates |
| --- | --- | --- | --- | --- | --- |
| x1 | Nasdaq_buy_hold | -0.72 pp | 7.08 pp | 1827.58 | 17 |
| x1 | parent | 0.16 pp | -0.02 pp | -151.64 | 0 |
| x1 | without_defensive | 2.87 pp | -0.82 pp | 981.40 | 0 |
| x1 | without_execution | 0.35 pp | -0.00 pp | -951.08 | -18 |
| x1 | without_risk | -0.37 pp | 4.00 pp | 235.03 | 13 |
| x1 | without_trend | 0.16 pp | 0.00 pp | 914.11 | 0 |
| x2 | Nasdaq_buy_hold | -1.01 pp | 7.04 pp | 3622.67 | 17 |
| x2 | parent | 0.19 pp | 0.02 pp | -300.25 | 0 |
| x2 | without_defensive | 2.74 pp | -0.85 pp | 1942.59 | 0 |
| x2 | without_execution | 0.42 pp | -0.00 pp | -1876.54 | -17 |
| x2 | without_risk | -0.49 pp | 3.97 pp | 450.08 | 13 |
| x2 | without_trend | 0.03 pp | 0.00 pp | 1809.72 | 0 |

Une amelioration DD positive signifie une perte maximale reduite. Les deltas CAGR/DD sont en points de pourcentage (pp). Un delta CAGR negatif est le prix en croissance de cette protection. Les effets conditionnels ne s'additionnent pas.

Les CSV publient tous les regimes, episodes sous 95 % Nasdaq et inputs refuses. Les poids de cloture decrivent l'exposition ; ils ne servent jamais a reconstruire un PnL exact a partir de rendements deja realises. Les regimes de rendement t utilisent seulement le NAV Nasdaq connu a t-1 (126/21 seances, stress 10 %). Les 127 premieres observations restent non classees.

La decision suivante est ecrite separement dans analysis.json par le chercheur. Aucune ablation n'est promue automatiquement.
