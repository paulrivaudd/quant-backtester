# M15 - analyse des mecanismes

Parent : M10. Bloc change : recovery. 

M10 manque encore des reprises : exposition Nasdaq moyenne de 67,63 % et rendement actif de −1,888 point de base par jour dans ce régime. Les reprises sur momentum court avaient produit des faux retours. Ajouter uniquement une règle de reprise sur clôture égale au plus haut des 63 séances passées, afin d’exiger une confirmation de prix différente.

Benefice attendu : Restaurer la direction complète avant le redressement de tous les votes de tendance lorsque le marché atteint effectivement un nouveau plus haut récent ; le risque et les autres filtres restent actifs.

Cout attendu : Une cassure peut échouer ou disparaître à la décision suivante ; cette règle sans état caché peut donc créer des réductions et réentrées supplémentaires. Les baisses après cassure et tous les frais seront conservés.

Refutation annoncee : La reprise récupérée ne compense pas les faux retours et les ordres, ou le drawdown dépasse 25 %. La fenêtre de 63 séances et le critère de nouveau plus haut restent figés, sans recherche de seuil favorable.

Comparaisons de vrais parcours continus 2019-2024 ; memes donnees et frais. Les deux niveaux de frais sont reellement simules. Histoire deja exploree.

| Cout | Controle retire/parent | Delta CAGR | Amelioration DD | Delta frais EUR | Delta dates |
| --- | --- | --- | --- | --- | --- |
| x1 | Nasdaq_buy_hold | -0.55 pp | 8.99 pp | 3799.72 | 25 |
| x1 | parent | -0.47 pp | 0.00 pp | 147.01 | 1 |
| x1 | without_defensive | 3.33 pp | -0.02 pp | 2224.03 | 0 |
| x1 | without_execution | 0.89 pp | -0.00 pp | -91.94 | -9 |
| x1 | without_recovery | -0.47 pp | 0.00 pp | 147.01 | 1 |
| x1 | without_risk | 0.33 pp | 2.01 pp | 431.26 | 6 |
| x1 | without_trend | -0.27 pp | 5.21 pp | 2535.89 | 8 |
| x2 | Nasdaq_buy_hold | -0.99 pp | 8.93 pp | 7514.00 | 25 |
| x2 | parent | -0.48 pp | 0.00 pp | 287.62 | 1 |
| x2 | without_defensive | 3.09 pp | 0.28 pp | 4385.21 | 0 |
| x2 | without_execution | 0.91 pp | 0.55 pp | -180.68 | -8 |
| x2 | without_recovery | -0.48 pp | 0.00 pp | 287.62 | 1 |
| x2 | without_risk | 0.29 pp | 2.00 pp | 852.30 | 6 |
| x2 | without_trend | -0.55 pp | 5.31 pp | 5001.10 | 8 |

Une amelioration DD positive signifie une perte maximale reduite. Les deltas CAGR/DD sont en points de pourcentage (pp). Un delta CAGR negatif est le prix en croissance de cette protection. Les effets conditionnels ne s'additionnent pas.

Les CSV publient tous les regimes, episodes sous 95 % Nasdaq et inputs refuses. Les poids de cloture decrivent l'exposition ; ils ne servent jamais a reconstruire un PnL exact a partir de rendements deja realises. Les regimes de rendement t utilisent seulement le NAV Nasdaq connu a t-1 (126/21 seances, stress 10 %). Les 127 premieres observations restent non classees.

La decision suivante est ecrite separement dans analysis.json par le chercheur. Aucune ablation n'est promue automatiquement.
