# M32 - analyse des mecanismes

Parent : M31. Bloc change : cadence. 

M31 évite 7,590 points de drawdown mais ajoute six dates et 1 940 EUR de frais sous contrôle hebdomadaire. Garder exactement les horizons 63/126 et les autres mécanismes, et remplacer seulement la cadence par le mensuel déclaré.

Benefice attendu : Ignorer des franchissements intermédiaires de courte durée et diminuer les contrôles, les fills et les frais, en conservant la logique de confirmation à deux horizons.

Cout attendu : Des sorties et réentrées seront retardées ; une partie de la protection de drawdown ou de la reprise peut disparaître. Le risque de cadence observé dans les autres assemblages reste une limite.

Refutation annoncee : Les économies d’intervention ne compensent pas la protection ou la croissance perdue, ou la stratégie reste sous Nasdaq aux frais doubles. Aucun jour historique n’est choisi manuellement.

Comparaisons de vrais parcours continus 2019-2024 ; memes donnees et frais. Les deux niveaux de frais sont reellement simules. Histoire deja exploree.

| Cout | Controle retire/parent | Delta CAGR | Amelioration DD | Delta frais EUR | Delta dates |
| --- | --- | --- | --- | --- | --- |
| x1 | Nasdaq_buy_hold | 2.01 pp | 11.98 pp | 3927.19 | 10 |
| x1 | parent | 2.42 pp | -0.74 pp | -1844.83 | -6 |
| x1 | without_confirmation | 2.36 pp | 8.90 pp | 2334.63 | 6 |
| x1 | without_defensive | 6.00 pp | -2.90 pp | 2136.80 | 0 |
| x1 | without_execution | 0.63 pp | 0.17 pp | -788.77 | -7 |
| x1 | without_trend | 1.44 pp | 0.54 pp | -618.91 | -2 |
| x2 | Nasdaq_buy_hold | 1.60 pp | 11.81 pp | 7769.49 | 10 |
| x2 | parent | 2.71 pp | -0.43 pp | -3563.20 | -6 |
| x2 | without_confirmation | 2.12 pp | 8.74 pp | 4596.90 | 6 |
| x2 | without_defensive | 5.81 pp | -3.07 pp | 4211.03 | 0 |
| x2 | without_execution | 0.71 pp | 0.17 pp | -1538.74 | -6 |
| x2 | without_trend | 1.54 pp | 0.55 pp | -1201.19 | -2 |

Une amelioration DD positive signifie une perte maximale reduite. Les deltas CAGR/DD sont en points de pourcentage (pp). Un delta CAGR negatif est le prix en croissance de cette protection. Les effets conditionnels ne s'additionnent pas.

Les CSV publient tous les regimes, episodes sous 95 % Nasdaq et inputs refuses. Les poids de cloture decrivent l'exposition ; ils ne servent jamais a reconstruire un PnL exact a partir de rendements deja realises. Les regimes de rendement t utilisent seulement le NAV Nasdaq connu a t-1 (126/21 seances, stress 10 %). Les 127 premieres observations restent non classees.

La decision suivante est ecrite separement dans analysis.json par le chercheur. Aucune ablation n'est promue automatiquement.
