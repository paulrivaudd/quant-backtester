# M18 - analyse des mecanismes

Parent : M10. Bloc change : shock. 

Les diagnostics déjà calculés recensent cinq décisions où M10 garde du Nasdaq malgré un drawdown de prix à 63 séances inférieur ou égal à −10 % : juin 2019 au départ, février et mars 2020, janvier et septembre 2022. Ajouter uniquement le bloc de choc drawdown, dont le seuil et la fenêtre étaient figés avant M01.

Benefice attendu : Éviter de conserver une exposition résiduelle dans les baisses prononcées, même si des votes plus lents restent positifs ou si le cap n’impose pas une sortie complète.

Cout attendu : Sortir après une chute peut vendre trop tard et manquer le rebond suivant ; le départ de juin 2019 et toutes les autres occurrences sont conservés dans le diagnostic, sans sélectionner les seuls krachs favorables.

Refutation annoncee : La réduction des pertes ne compense pas les reprises abandonnées ou les interventions, notamment si le rendement net reste sous le Nasdaq. Aucun seuil de perte, horizon ou poids n’est ajusté après calcul.

Comparaisons de vrais parcours continus 2019-2024 ; memes donnees et frais. Les deux niveaux de frais sont reellement simules. Histoire deja exploree.

| Cout | Controle retire/parent | Delta CAGR | Amelioration DD | Delta frais EUR | Delta dates |
| --- | --- | --- | --- | --- | --- |
| x1 | Nasdaq_buy_hold | -0.01 pp | 11.81 pp | 3891.97 | 23 |
| x1 | parent | 0.06 pp | 2.82 pp | 239.26 | -1 |
| x1 | without_defensive | 4.82 pp | 0.50 pp | 2527.60 | 1 |
| x1 | without_execution | 0.96 pp | 2.05 pp | -106.93 | -9 |
| x1 | without_risk | -0.61 pp | -0.00 pp | 257.48 | 6 |
| x1 | without_shock | 0.06 pp | 2.82 pp | 239.26 | -1 |
| x1 | without_trend | 0.60 pp | 6.85 pp | 854.84 | 5 |
| x2 | Nasdaq_buy_hold | -0.55 pp | 11.66 pp | 7675.82 | 23 |
| x2 | parent | -0.03 pp | 2.73 pp | 449.43 | -1 |
| x2 | without_defensive | 4.51 pp | 0.64 pp | 4971.69 | 1 |
| x2 | without_execution | 0.94 pp | 2.47 pp | -201.49 | -9 |
| x2 | without_risk | -0.70 pp | 0.39 pp | 499.10 | 6 |
| x2 | without_shock | -0.03 pp | 2.73 pp | 449.43 | -1 |
| x2 | without_trend | 0.47 pp | 7.23 pp | 1666.84 | 5 |

Une amelioration DD positive signifie une perte maximale reduite. Les deltas CAGR/DD sont en points de pourcentage (pp). Un delta CAGR negatif est le prix en croissance de cette protection. Les effets conditionnels ne s'additionnent pas.

Les CSV publient tous les regimes, episodes sous 95 % Nasdaq et inputs refuses. Les poids de cloture decrivent l'exposition ; ils ne servent jamais a reconstruire un PnL exact a partir de rendements deja realises. Les regimes de rendement t utilisent seulement le NAV Nasdaq connu a t-1 (126/21 seances, stress 10 %). Les 127 premieres observations restent non classees.

La decision suivante est ecrite separement dans analysis.json par le chercheur. Aucune ablation n'est promue automatiquement.
