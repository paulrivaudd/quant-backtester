# M12 - analyse des mecanismes

Parent : M10. Bloc change : risk. 

Le trimestriel M11 dégrade fortement les réactions. Sur le parent mensuel M10, l’ablation du risque, déjà observée, reste à 24,063 % de drawdown avec 19 dates, contre 22,054 % et 25 dates avec le cap. Promouvoir explicitement ce contrôle en candidat sans bloc de risque supplémentaire ; le consensus de tendance conserve son dimensionnement gradué.

Benefice attendu : Retirer un mécanisme de réglage d’exposition et réduire les interventions tout en conservant une protection observée inférieure à 25 % de drawdown.

Cout attendu : Abandonner environ deux points de protection et un peu de croissance observée ; la borne de drawdown n’est pas une garantie future. Ce résultat d’ablation est déjà connu et ne fournit pas une confirmation indépendante.

Refutation annoncee : La réduction des ordres ne compense pas les pertes de croissance ou de protection ; publier également les ablations des autres blocs, sans considérer le résultat connu comme un test vierge.

Comparaisons de vrais parcours continus 2019-2024 ; memes donnees et frais. Les deux niveaux de frais sont reellement simules. Histoire deja exploree.

| Cout | Controle retire/parent | Delta CAGR | Amelioration DD | Delta frais EUR | Delta dates |
| --- | --- | --- | --- | --- | --- |
| x1 | Nasdaq_buy_hold | -0.28 pp | 6.99 pp | 3158.85 | 18 |
| x1 | parent | -0.20 pp | -2.01 pp | -493.86 | -6 |
| x1 | without_defensive | 2.71 pp | -0.69 pp | 1892.67 | 0 |
| x1 | without_execution | 0.69 pp | 0.14 pp | -104.78 | -6 |
| x1 | without_trend | -0.28 pp | 6.99 pp | 3158.85 | 18 |
| x2 | Nasdaq_buy_hold | -0.65 pp | 6.93 pp | 6257.95 | 18 |
| x2 | parent | -0.13 pp | -2.00 pp | -968.43 | -6 |
| x2 | without_defensive | 2.51 pp | -0.72 pp | 3740.85 | 0 |
| x2 | without_execution | 0.73 pp | 0.14 pp | -189.87 | -5 |
| x2 | without_trend | -0.65 pp | 6.93 pp | 6257.95 | 18 |

Une amelioration DD positive signifie une perte maximale reduite. Les deltas CAGR/DD sont en points de pourcentage (pp). Un delta CAGR negatif est le prix en croissance de cette protection. Les effets conditionnels ne s'additionnent pas.

Les CSV publient tous les regimes, episodes sous 95 % Nasdaq et inputs refuses. Les poids de cloture decrivent l'exposition ; ils ne servent jamais a reconstruire un PnL exact a partir de rendements deja realises. Les regimes de rendement t utilisent seulement le NAV Nasdaq connu a t-1 (126/21 seances, stress 10 %). Les 127 premieres observations restent non classees.

La decision suivante est ecrite separement dans analysis.json par le chercheur. Aucune ablation n'est promue automatiquement.
