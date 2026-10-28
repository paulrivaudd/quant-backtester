# M24 - analyse des mecanismes

Parent : M23. Bloc change : execution. 

M23 augmente les ordres et le cash, mais deux aspects ont changé dans son bloc d’exécution : asymétrie des réponses et abandon du maintien défensif. Remplacer uniquement asymmetric par band, le contrôle symétrique déjà déclaré, pour vérifier si des entrées moins retardées et des réductions moins sensibles corrigent le problème.

Benefice attendu : Réduire les oscillations d’exécution et le retard de réentrée, tout en isolant l’effet de l’asymétrie par rapport au maintien défensif : M23 et M24 diffèrent par l’exécution, tout comme M22 et M24.

Cout attendu : La sortie de défense reste respectée, donc le bénéfice éventuel du maintien d’or demeure abandonné. Le contrôle peut montrer que l’asymétrie n’était pas la cause principale ; les trois parcours seront publiés.

Refutation annoncee : Les interventions ou le rendement ne s’améliorent pas, ou le risque se dégrade sans compensation. Les trois bandes numériques restent les constantes fixées avant M01 ; ce contrôle de mécanisme ne lance aucune recherche de seuil.

Comparaisons de vrais parcours continus 2019-2024 ; memes donnees et frais. Les deux niveaux de frais sont reellement simules. Histoire deja exploree.

| Cout | Controle retire/parent | Delta CAGR | Amelioration DD | Delta frais EUR | Delta dates |
| --- | --- | --- | --- | --- | --- |
| x1 | Nasdaq_buy_hold | 0.28 pp | 11.35 pp | 3079.48 | 20 |
| x1 | parent | 0.50 pp | -0.01 pp | 4.27 | -2 |
| x1 | without_defensive | 4.15 pp | -2.10 pp | 2161.95 | 5 |
| x1 | without_execution | -0.10 pp | 0.02 pp | -241.23 | -15 |
| x1 | without_risk | -0.36 pp | 2.49 pp | -69.40 | 10 |
| x1 | without_shock | 0.84 pp | 4.27 pp | 434.36 | -1 |
| x1 | without_trend | 0.65 pp | 4.42 pp | 344.76 | 0 |
| x2 | Nasdaq_buy_hold | -0.15 pp | 10.81 pp | 6090.57 | 20 |
| x2 | parent | 0.47 pp | 0.01 pp | -2.07 | -2 |
| x2 | without_defensive | 3.89 pp | -2.39 pp | 4266.81 | 5 |
| x2 | without_execution | -0.10 pp | 0.02 pp | -461.78 | -14 |
| x2 | without_risk | -0.36 pp | 2.58 pp | -141.41 | 10 |
| x2 | without_shock | 0.73 pp | 3.77 pp | 846.11 | -1 |
| x2 | without_trend | 0.60 pp | 4.42 pp | 675.22 | 0 |

Une amelioration DD positive signifie une perte maximale reduite. Les deltas CAGR/DD sont en points de pourcentage (pp). Un delta CAGR negatif est le prix en croissance de cette protection. Les effets conditionnels ne s'additionnent pas.

Les CSV publient tous les regimes, episodes sous 95 % Nasdaq et inputs refuses. Les poids de cloture decrivent l'exposition ; ils ne servent jamais a reconstruire un PnL exact a partir de rendements deja realises. Les regimes de rendement t utilisent seulement le NAV Nasdaq connu a t-1 (126/21 seances, stress 10 %). Les 127 premieres observations restent non classees.

La decision suivante est ecrite separement dans analysis.json par le chercheur. Aucune ablation n'est promue automatiquement.
