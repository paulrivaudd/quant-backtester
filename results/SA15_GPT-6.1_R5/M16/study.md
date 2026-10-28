# M16 - analyse des mecanismes

Parent : M15. Bloc change : confirmation. 

Le seul signal de reprise actif de M15 est un faux retour de juillet 2022, alors que sa tendance longue reste négative. Ajouter uniquement une confirmation de risque globale : les ETF Monde et marchés émergents doivent tous deux avoir un momentum positif à 126 séances. Ces indicateurs sont fixés et ne sont pas négociés.

Benefice attendu : Éviter des retours Nasdaq isolés dans un environnement de risque mondial encore défavorable, sans sélectionner des dates historiques ou des pondérations optimales.

Cout attendu : La confirmation filtre toute la direction, y compris des hausses Nasdaq qui ne sont pas partagées par les émergents. Elle peut donc manquer des tendances rentables, réduire fortement l’exposition et multiplier les sorties ; ses données manquantes sont explicitement bloquantes.

Refutation annoncee : La protection ou la suppression des faux retours ne compense pas la croissance abandonnée, ou les interventions augmentent. Comparer les ablations de confirmation et de reprise pour isoler leur interaction, sans chercher un seuil de canari favorable.

Comparaisons de vrais parcours continus 2019-2024 ; memes donnees et frais. Les deux niveaux de frais sont reellement simules. Histoire deja exploree.

| Cout | Controle retire/parent | Delta CAGR | Amelioration DD | Delta frais EUR | Delta dates |
| --- | --- | --- | --- | --- | --- |
| x1 | Nasdaq_buy_hold | -7.02 pp | 11.82 pp | 5960.12 | 24 |
| x1 | parent | -6.48 pp | 2.83 pp | 2160.40 | -1 |
| x1 | without_confirmation | -6.48 pp | 2.83 pp | 2160.40 | -1 |
| x1 | without_defensive | 3.81 pp | 3.22 pp | 3309.74 | 0 |
| x1 | without_execution | 0.50 pp | -0.00 pp | -960.25 | -15 |
| x1 | without_recovery | 0.00 pp | 0.00 pp | 0.00 | 0 |
| x1 | without_risk | 0.52 pp | 0.00 pp | 46.45 | 2 |
| x1 | without_trend | 0.57 pp | 0.00 pp | 242.38 | 3 |
| x2 | Nasdaq_buy_hold | -7.79 pp | 11.66 pp | 11676.91 | 24 |
| x2 | parent | -6.79 pp | 2.74 pp | 4162.90 | -1 |
| x2 | without_confirmation | -6.79 pp | 2.74 pp | 4162.90 | -1 |
| x2 | without_defensive | 3.42 pp | 3.19 pp | 6431.99 | 0 |
| x2 | without_execution | 0.63 pp | 0.00 pp | -1839.84 | -14 |
| x2 | without_recovery | 0.00 pp | 0.00 pp | 0.00 | 0 |
| x2 | without_risk | 0.52 pp | 0.00 pp | 83.20 | 2 |
| x2 | without_trend | 0.55 pp | 0.00 pp | 462.02 | 3 |

Une amelioration DD positive signifie une perte maximale reduite. Les deltas CAGR/DD sont en points de pourcentage (pp). Un delta CAGR negatif est le prix en croissance de cette protection. Les effets conditionnels ne s'additionnent pas.

Les CSV publient tous les regimes, episodes sous 95 % Nasdaq et inputs refuses. Les poids de cloture decrivent l'exposition ; ils ne servent jamais a reconstruire un PnL exact a partir de rendements deja realises. Les regimes de rendement t utilisent seulement le NAV Nasdaq connu a t-1 (126/21 seances, stress 10 %). Les 127 premieres observations restent non classees.

La decision suivante est ecrite separement dans analysis.json par le chercheur. Aucune ablation n'est promue automatiquement.
