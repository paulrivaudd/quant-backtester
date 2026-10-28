# M09 - analyse des mecanismes

Parent : M08. Bloc change : recovery. 

L'ablation M08 sans reprise est deja observee: le bloc n'ajoute que0.068pointCAGR,+4dates,+651EUR, sans gainDD et devient negatif aux frais doubles. Promotion explicite comptee de ce controle en candidat plus simple; aucune preuve nouvelle independante.

Benefice attendu : Eliminer les faux retours de reprise et leurs rotations, laisser le filtreMA200 et le maintiendefense travailler avec moins d'ordres.

Cout attendu : Retarder les reentrees durant un vrai retournement et sacrifier un peu de croissance aux frais normaux; le resultat historique du controle est deja connu.

Refutation annoncee : La reduction de complexite/interventions ne compense pas la croissance manquee, ou risque degrade; toutes les ablations restantes sont reellement simulees ou reutilisees sous contrat identique.

Comparaisons de vrais parcours continus 2019-2024 ; memes donnees et frais. Les deux niveaux de frais sont reellement simules. Histoire deja exploree.

| Cout | Controle retire/parent | Delta CAGR | Amelioration DD | Delta frais EUR | Delta dates |
| --- | --- | --- | --- | --- | --- |
| x1 | Nasdaq_buy_hold | -0.74 pp | 7.08 pp | 2444.24 | 15 |
| x1 | parent | -0.07 pp | 0.00 pp | -651.40 | -4 |
| x1 | without_defensive | 2.70 pp | -0.61 pp | 1324.15 | 0 |
| x1 | without_execution | 0.84 pp | -0.00 pp | -761.72 | -10 |
| x1 | without_risk | 1.09 pp | 4.00 pp | 498.50 | 9 |
| x1 | without_trend | -0.46 pp | 3.29 pp | 1180.41 | -2 |
| x2 | Nasdaq_buy_hold | -1.08 pp | 7.04 pp | 4840.12 | 15 |
| x2 | parent | 0.01 pp | 0.00 pp | -1278.78 | -4 |
| x2 | without_defensive | 2.53 pp | -0.37 pp | 2612.52 | 0 |
| x2 | without_execution | 0.93 pp | -0.00 pp | -1492.90 | -9 |
| x2 | without_risk | 1.01 pp | 3.97 pp | 974.36 | 9 |
| x2 | without_trend | -0.64 pp | 3.43 pp | 2327.21 | -2 |

Une amelioration DD positive signifie une perte maximale reduite. Les deltas CAGR/DD sont en points de pourcentage (pp). Un delta CAGR negatif est le prix en croissance de cette protection. Les effets conditionnels ne s'additionnent pas.

Les CSV publient tous les regimes, episodes sous 95 % Nasdaq et inputs refuses. Les poids de cloture decrivent l'exposition ; ils ne servent jamais a reconstruire un PnL exact a partir de rendements deja realises. Les regimes de rendement t utilisent seulement le NAV Nasdaq connu a t-1 (126/21 seances, stress 10 %). Les 127 premieres observations restent non classees.

La decision suivante est ecrite separement dans analysis.json par le chercheur. Aucune ablation n'est promue automatiquement.
