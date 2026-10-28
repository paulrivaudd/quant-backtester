# M20 - analyse des mecanismes

Parent : M19. Bloc change : trend. 

M19 est qualifié mais son consensus demande encore huit allocations intermédiaires à un tiers ou deux tiers. Certaines gardent du Nasdaq dans un rebond alors que le momentum à 126 séances reste négatif. Remplacer uniquement le consensus par la règle binaire momentum126 positif, en conservant le choc, la défense et l’exécution.

Benefice attendu : Simplifier la direction et réduire les changements intermédiaires de votes, sans chercher un horizon optimal ; éviter certaines expositions partielles dans les rebonds de tendance longue négative.

Cout attendu : Le momentum long peut entrer trop tard après un creux et permet des entrées complètes dès qu’il redevient positif. La perte de graduation peut donc augmenter les pertes et abandonner des reprises profitables.

Refutation annoncee : La réduction d’ordres ne compense pas les retards et le drawdown, ou le rendement ne résiste plus aux frais doubles. Le seuil zéro et l’horizon de 126 séances restent figés.

Comparaisons de vrais parcours continus 2019-2024 ; memes donnees et frais. Les deux niveaux de frais sont reellement simules. Histoire deja exploree.

| Cout | Controle retire/parent | Delta CAGR | Amelioration DD | Delta frais EUR | Delta dates |
| --- | --- | --- | --- | --- | --- |
| x1 | Nasdaq_buy_hold | 1.34 pp | 8.48 pp | 2374.61 | 7 |
| x1 | parent | 0.74 pp | -3.34 pp | -1259.88 | -10 |
| x1 | without_defensive | 4.44 pp | -1.25 pp | 1442.90 | 1 |
| x1 | without_execution | 0.47 pp | -0.35 pp | -816.68 | -7 |
| x1 | without_shock | 1.69 pp | 5.40 pp | 782.06 | 3 |
| x1 | without_trend | 1.77 pp | 6.07 pp | -269.06 | -2 |
| x2 | Nasdaq_buy_hold | 1.03 pp | 8.17 pp | 4709.43 | 7 |
| x2 | parent | 0.87 pp | -3.11 pp | -2467.28 | -10 |
| x2 | without_defensive | 4.29 pp | -1.25 pp | 2855.73 | 1 |
| x2 | without_execution | 0.59 pp | -0.05 pp | -1601.67 | -6 |
| x2 | without_shock | 1.54 pp | 5.09 pp | 1536.85 | 3 |
| x2 | without_trend | 1.84 pp | 6.34 pp | -529.23 | -2 |

Une amelioration DD positive signifie une perte maximale reduite. Les deltas CAGR/DD sont en points de pourcentage (pp). Un delta CAGR negatif est le prix en croissance de cette protection. Les effets conditionnels ne s'additionnent pas.

Les CSV publient tous les regimes, episodes sous 95 % Nasdaq et inputs refuses. Les poids de cloture decrivent l'exposition ; ils ne servent jamais a reconstruire un PnL exact a partir de rendements deja realises. Les regimes de rendement t utilisent seulement le NAV Nasdaq connu a t-1 (126/21 seances, stress 10 %). Les 127 premieres observations restent non classees.

La decision suivante est ecrite separement dans analysis.json par le chercheur. Aucune ablation n'est promue automatiquement.
