# SA15 R5 : hypothèses par mécanismes

Note du 16 octobre 2026, avant les simulations R5. Les sources primaires motivent des blocs et leurs réfutations ; leurs performances ne constituent pas une prévision pour nos ETF. Cinquante itérations avec ablations sont autorisées, sans grille de poids historiques. Nasdaq conservé reste le contrôle principal. L'histoire 2019–2026 a déjà été explorée.

| Source primaire consultée | Mécanisme motivé | Coût ou réfutation à mesurer |
| --- | --- | --- |
| Moskowitz, Ooi et Pedersen (2012), [Time Series Momentum](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum) | Direction par rendements passés et horizons fixes. | Retard de sortie/retour, faux signaux, rendement net sacrifié ; leurs futures diversifiés diffèrent de notre Nasdaq long-only. |
| Moreira et Muir (2017), [Volatility-Managed Portfolios](https://www.nber.org/papers/w22208) | Réduction d'exposition lorsque le risque estimé augmente. | La volatilité après un choc peut limiter la reprise. Notre plafond sans levier diffère du dimensionnement académique et ne détecte pas directement les hausses. |
| Daniel et Moskowitz (2016), [Momentum Crashes](https://www.nber.org/papers/w20439) | Étudier les reprises après stress. | Leur momentum transversal diffère de notre filtre directionnel. Un retour rapide doit mesurer les faux rebonds et la protection abandonnée. |
| Gârleanu et Pedersen (2013), [Dynamic Trading with Predictable Returns and Transaction Costs](https://www.nber.org/papers/w15205) | Persistance des signaux, ajustement progressif et coûts. | Une bande ou une cadence lente peut diminuer les frais et manquer un retournement. Aucun seuil n'est réputé optimal pour nos ETF. |
| Bailey et López de Prado (2014), [The Deflated Sharpe Ratio](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf) | Compter les essais et corriger descriptivement le Sharpe sélectionné. | Approximation de Sharpe absolu, pas probabilité de battre Nasdaq ; les choix adaptatifs ne sont pas intégralement corrigés. |
| Bailey, Borwein, López de Prado et Zhu (2017), [The Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf) | Conserver tous les essais/échecs et geler chaque mécanisme avant calcul. | Cinquante adaptations sur des données connues restent rétrospectives, même sans optimiser directement les poids. |

Les quatre pages HTML et les deux PDF ont été consultés par urllib le 16 octobre 2026, sans téléchargement de prix ni ajout de dépendance. SHA-256 des contenus reçus :

- AQR TSMOM (71 369 octets) : `191525b94282dc7dd3c4cd417a5cf3e2f739e422b37c53ccc54ce956666ccba0`.
- NBER 22208 (90 415 octets) : `6b63658b28d7df2b8a06e384ebfc9cebb9bdc8011870cb521457c5e9d014efcd`.
- NBER 20439 (89 480 octets) : `6e16c5653ebf9739eb489e7860b56e482edd2e0f1ba21be5a2dee142e374abc5`.
- NBER 15205 (90 682 octets) : `ccf8444a665654a6e4147fda5a7b8a5c1cff7280b10b610591e7fa90df63f0b6`.
- DSR (1 048 118 octets) : `ca4a1e834a2954b84eb560776e903329cd9cef318d458aadf6d67bc8166d10b5`.
- PBO (1 145 522 octets) : `d8bfbadaaedb430d9dec929646d92f3580fdf18238f34121ae7738fa1c69a63d`.

La disponibilité des données et l'exécution priment sur la formule. Un historique obligatoire manquant reste distinct d'un signal économique ; aucune barre n'est inventée. Les régimes communs hausse/baisse/reprise sont retardés d'une séance et décrivent les portefeuilles réellement simulés. Les poids de clôture ne sont jamais multipliés par le rendement déjà réalisé pour inventer une attribution comptable.

Chaque candidat annonce parent, unique mécanisme changé, bénéfice attendu, coût et réfutation. Retirer chaque bloc mesure un effet conditionnel dans le simulateur : les effets dépendent des autres blocs et ne s'additionnent pas nécessairement. La complexité doit apporter un gain économique net face au parent simple utilisant les mêmes informations.