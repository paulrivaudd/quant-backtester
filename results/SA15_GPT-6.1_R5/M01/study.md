# M01 - analyse des mecanismes

Parent : M00. Bloc change : recovery. 

Le pilote manque les reprises, exposition Nasdaq moyenne66% sur jours classes reprise. Ajouter uniquement la reprise momentum21 positif pour tester une reentree sans attendre MA200.

Benefice attendu : Recuperer les rebonds qui precedent le retournement de MA200, en conservant le cap de volatilite.

Cout attendu : Faux retours durant les rebonds de marche baissier et davantage de transactions.

Refutation annoncee : Apport net negatif sans protection supplementaire ou hausse forte de drawdown/interventions; aucune retouche de seuil21 apres calcul.

Comparaisons de vrais parcours continus 2019-2024 ; memes donnees et frais. Les deux niveaux de frais sont reellement simules. Histoire deja exploree.

| Cout | Controle retire/parent | Delta CAGR | Amelioration DD | Delta frais EUR | Delta dates |
| --- | --- | --- | --- | --- | --- |
| x1 | Nasdaq_buy_hold | -3.45 % | 7.28 % | 2034.72 | 25 |
| x1 | parent | 0.74 % | -0.63 % | 735.88 | 4 |
| x1 | without_defensive | 0.14 % | -0.05 % | 645.81 | 3 |
| x1 | without_execution | 0.02 % | 0.10 % | -206.28 | -14 |
| x1 | without_recovery | 0.74 % | -0.63 % | 735.88 | 4 |
| x1 | without_risk | -0.32 % | 5.85 % | -91.05 | 14 |
| x1 | without_trend | -0.85 % | 2.21 % | 1476.99 | 6 |
| x2 | Nasdaq_buy_hold | -3.78 % | 6.79 % | 4030.05 | 25 |
| x2 | parent | 0.64 % | -1.10 % | 1455.67 | 4 |
| x2 | without_defensive | 0.02 % | -0.18 % | 1265.30 | 3 |
| x2 | without_execution | 0.04 % | 0.10 % | -406.56 | -14 |
| x2 | without_recovery | 0.64 % | -1.10 % | 1455.67 | 4 |
| x2 | without_risk | -0.32 % | 5.93 % | -189.65 | 14 |
| x2 | without_trend | -1.06 % | 1.78 % | 2919.56 | 6 |

Une amelioration DD positive signifie une perte maximale reduite. Un delta CAGR negatif est le prix en croissance de cette protection. Les effets conditionnels ne s'additionnent pas.

Les CSV publient tous les regimes, episodes sous 95 % Nasdaq et inputs refuses. Les poids de cloture decrivent l'exposition ; ils ne servent jamais a reconstruire un PnL exact a partir de rendements deja realises. Les regimes de rendement t utilisent seulement le NAV Nasdaq connu a t-1 (126/21 seances, stress 10 %). Les 127 premieres observations restent non classees.

La decision suivante est ecrite separement dans analysis.json par le chercheur. Aucune ablation n'est promue automatiquement.
