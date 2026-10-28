# M10 - analyse des mecanismes

Parent : M09. Bloc change : trend. 

M09 economise des ordres mais manque encore les reprises (72.13%Nasdaq,actif-2.432bp/j). Le31mars2020 MA200 negative et momentum126 positif divergent. Remplacer uniquement la direction binaire par la fraction de votes positifs MA200/momentum63/momentum126, votes egaux figes.

Benefice attendu : Restaurer progressivement l'exposition quand plusieurs horizons se redressent, sans reinstaurer un signal21 de reprise ni conserver une demi-position permanente.

Cout attendu : Votes partiels faux pendant une baisse, davantage de positions intermediaires et d'ordres; le cap applique sa formule declaree a cette fraction.

Refutation annoncee : Meilleure reprise insuffisante pour le cout de drawdown/interventions, ou DDau-dessus25%; aucune optimisation de poids de votes ou d'horizons.

Comparaisons de vrais parcours continus 2019-2024 ; memes donnees et frais. Les deux niveaux de frais sont reellement simules. Histoire deja exploree.

| Cout | Controle retire/parent | Delta CAGR | Amelioration DD | Delta frais EUR | Delta dates |
| --- | --- | --- | --- | --- | --- |
| x1 | Nasdaq_buy_hold | -0.07 pp | 8.99 pp | 3652.71 | 24 |
| x1 | parent | 0.67 pp | 1.91 pp | 1208.46 | 9 |
| x1 | without_defensive | 3.35 pp | -1.66 pp | 2232.27 | 0 |
| x1 | without_execution | 0.93 pp | -0.00 pp | -111.67 | -10 |
| x1 | without_risk | 0.20 pp | 2.01 pp | 493.86 | 6 |
| x1 | without_trend | 0.20 pp | 5.21 pp | 2388.87 | 7 |
| x2 | Nasdaq_buy_hold | -0.51 pp | 8.93 pp | 7226.39 | 24 |
| x2 | parent | 0.57 pp | 1.88 pp | 2386.27 | 9 |
| x2 | without_defensive | 3.11 pp | -1.44 pp | 4395.20 | 0 |
| x2 | without_execution | 0.95 pp | -0.00 pp | -220.78 | -9 |
| x2 | without_risk | 0.13 pp | 2.00 pp | 968.43 | 6 |
| x2 | without_trend | -0.07 pp | 5.31 pp | 4713.48 | 7 |

Une amelioration DD positive signifie une perte maximale reduite. Les deltas CAGR/DD sont en points de pourcentage (pp). Un delta CAGR negatif est le prix en croissance de cette protection. Les effets conditionnels ne s'additionnent pas.

Les CSV publient tous les regimes, episodes sous 95 % Nasdaq et inputs refuses. Les poids de cloture decrivent l'exposition ; ils ne servent jamais a reconstruire un PnL exact a partir de rendements deja realises. Les regimes de rendement t utilisent seulement le NAV Nasdaq connu a t-1 (126/21 seances, stress 10 %). Les 127 premieres observations restent non classees.

La decision suivante est ecrite separement dans analysis.json par le chercheur. Aucune ablation n'est promue automatiquement.
