# M31 - analyse des mecanismes

Parent : M30. Bloc change : confirmation. 

M30 dépasse Nasdaq mais conserve 25,926 % de drawdown avec une position binaire fondée sur le seul momentum à 126 séances. Ajouter uniquement la confirmation momentum : le rendement à 63 séances doit aussi être positif pour autoriser la direction.

Benefice attendu : Couper une position pleine lorsque l’horizon intermédiaire devient baissier avant le momentum long, tout en gardant un signal binaire et local plutôt que des ajustements de volatilité ou des canaris externes.

Cout attendu : La confirmation peut manquer un début de reprise ou osciller autour de zéro, avec davantage de contrôles déjà hebdomadaires et de faux retours. Les paramètres ne changent pas.

Refutation annoncee : La protection ne compense pas le retard ou les interventions, ou le drawdown reste supérieur à 25 %. Toutes les occurrences et les frais doubles sont publiés.

Comparaisons de vrais parcours continus 2019-2024 ; memes donnees et frais. Les deux niveaux de frais sont reellement simules. Histoire deja exploree.

| Cout | Controle retire/parent | Delta CAGR | Amelioration DD | Delta frais EUR | Delta dates |
| --- | --- | --- | --- | --- | --- |
| x1 | Nasdaq_buy_hold | -0.41 pp | 12.71 pp | 5772.02 | 16 |
| x1 | parent | -2.06 pp | 7.59 pp | 1940.49 | 6 |
| x1 | without_confirmation | -2.06 pp | 7.59 pp | 1940.49 | 6 |
| x1 | without_defensive | 6.62 pp | 5.13 pp | 3304.84 | 0 |
| x1 | without_execution | 1.08 pp | 6.21 pp | -2898.36 | -22 |
| x1 | without_trend | 0.09 pp | 4.07 pp | 39.76 | 0 |
| x2 | Nasdaq_buy_hold | -1.11 pp | 12.24 pp | 11332.69 | 16 |
| x2 | parent | -2.31 pp | 7.27 pp | 3743.60 | 6 |
| x2 | without_confirmation | -2.31 pp | 7.27 pp | 3743.60 | 6 |
| x2 | without_defensive | 6.25 pp | 4.93 pp | 6443.37 | 0 |
| x2 | without_execution | 1.45 pp | 7.37 pp | -5528.27 | -20 |
| x2 | without_trend | 0.08 pp | 3.90 pp | 75.35 | 0 |

Une amelioration DD positive signifie une perte maximale reduite. Les deltas CAGR/DD sont en points de pourcentage (pp). Un delta CAGR negatif est le prix en croissance de cette protection. Les effets conditionnels ne s'additionnent pas.

Les CSV publient tous les regimes, episodes sous 95 % Nasdaq et inputs refuses. Les poids de cloture decrivent l'exposition ; ils ne servent jamais a reconstruire un PnL exact a partir de rendements deja realises. Les regimes de rendement t utilisent seulement le NAV Nasdaq connu a t-1 (126/21 seances, stress 10 %). Les 127 premieres observations restent non classees.

La decision suivante est ecrite separement dans analysis.json par le chercheur. Aucune ablation n'est promue automatiquement.
