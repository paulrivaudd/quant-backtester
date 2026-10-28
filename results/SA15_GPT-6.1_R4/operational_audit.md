# SA15_GPT-6.1 R4 — audit opérationnel des résultats

Audit du 16 octobre 2026, réalisé uniquement par lecture des configurations, données nettoyées et résultats sauvegardés. Aucun nouveau backtest, changement de paramètres, modification de source financier ou réparation de données. Le gagnant principal reste **71** ; les compagnons **55** et **79** restent les extrema descriptifs gelés avant le contrôle, conformément à [companions_frozen.json](companions_frozen.json). Ils ne remplacent pas le gagnant après lecture des résultats.

Tous les rendements sont en euros, nets des frais simulés et avant fiscalité personnelle. Capital initial : 100 000 EUR. Les séries fournisseurs sont ajustées/restatées, pas des archives de millésimes point-in-time. Les dates de transactions ci-dessous incluent l'achat initial ; elles ne sont pas des jours de vérification du signal.

## Comparaison du parcours continu

Portefeuilles réellement simulés sans redémarrage du 3 juin 2019 au 9 octobre 2026.

| Portefeuille | Gain total net | CAGR | Drawdown maximal | Dates de transactions | Frais EUR |
| --- | ---: | ---: | ---: | ---: | ---: |
| Gagnant principal 71 | +399,69 % | 24,46 % | −25,68 % | 29 | 6 960,54 |
| Compagnon 55 : technologie/or 75/25 | +439,19 % | 25,76 % | −25,00 % | 1 | 98,27 |
| Compagnon 79 : technologie/or 60/40 | +399,83 % | 24,47 % | −21,14 % | 2 | 189,54 |
| Nasdaq conservé | +348,00 % | 22,63 % | −31,05 % | 1 | 97,82 |
| Technologie US conservée | +513,08 % | 27,98 % | −30,99 % | 1 | 97,70 |

71 dépasse le Nasdaq sur ce parcours, mais reste inférieur à la technologie conservée de 113,39 points de rendement total. Son drawdown dépasse légèrement la cible de recherche de 25 %. Sa fréquence moyenne est de 3,94 dates avec transactions par an. Le résultat du contrôle récent ci-dessous exclut toutefois une conclusion de supériorité robuste du gagnant.

L'exposition moyenne de 71 est de 78,41 % en technologie US, 12,54 % en or, 6,87 % en matières premières, 1,19 % en monétaire et 0,99 % en cash. Sur le seul choix 2019–2024, le CAGR de 71 est de 29,13 %, contre 28,97 % pour la technologie conservée : seulement 0,163 point annuel de surplus face au contrôle sectoriel, avec 19 dates de transactions contre une. La majeure partie du gain face au Nasdaq vient donc du choix de l'exposition technologique ; l'alpha d'une gestion active n'est pas établi.

## Contrôle chronologique depuis cash

Portefeuilles redémarrés du 2 janvier 2025 au 9 octobre 2026 ; ce n'est pas le segment rebasé du parcours continu.

| Portefeuille | Gain total net | CAGR | Drawdown maximal | Dates de transactions | Frais EUR |
| --- | ---: | ---: | ---: | ---: | ---: |
| Gagnant principal 71 | +19,09 % | 10,40 % | −25,65 % | 10 | 1 312,07 |
| Compagnon 55 | +46,53 % | 24,16 % | −21,79 % | 1 | 99,40 |
| Compagnon 79 | +46,16 % | 23,98 % | −17,79 % | 1 | 99,39 |
| Nasdaq conservé | +34,32 % | 18,19 % | −26,30 % | 1 | 98,42 |
| Technologie US conservée | +47,18 % | 24,47 % | −29,69 % | 1 | 99,47 |

Sur ce contrôle, 71 demande 5,66 dates de transactions par an : la cible de quatre n'est plus respectée. L'exposition moyenne est de 55,23 % en technologie, 26,53 % en or, 15,51 % en matières premières, 1,55 % en monétaire et 1,17 % en cash. Le contrôle de frais doubles conserve le constat : 71 gagne seulement 17,64 %, contre 46,42 % pour 55 et 46,06 % pour 79. Les frais doubles ne créent aucun design supplémentaire et ne changent pas la sélection gelée.

## Règle effective de 71 et limites du plafond de risque

71 vérifie mensuellement un bloc offensif constitué uniquement de technologie US. Il estime sa volatilité par le maximum des écarts-types de 20 et 60 rendements logarithmiques consécutifs, annualisés à 252 séances. La cible offensive vaut `min(1, 0.20 / max(vol20, vol60, 0.05))`. Le reliquat va au meilleur score de momentum positif entre or et matières premières, calculé comme moyenne des rendements logarithmiques à 21, 63 et 126 séances, avec bonus de conservation de 0,02. Sinon, il utilise le monétaire à carry positif, puis le cash.

La bande de rééquilibrage est de 20 points de poids. Elle tolère des écarts à la cible ; une sortie complète d'un actif n'est jamais retardée. **20 % est une cible d'estimation du seul bloc offensif avant bande**, pas une volatilité garantie du portefeuille, ni une borne de drawdown. Les défenses ont leur propre risque et ne sont pas incluses dans cette estimation. La vérification se fait après clôture et les transactions aux ouvertures suivantes, sans levier.

## Deux trous de données commandent des exclusions de plusieurs mois

Les fichiers `runs/sa15_gpt61_r4_store/clean/checked_bars/ETF_US_TECH.parquet` ne contiennent aucune ligne les **24 octobre 2025** et **6 mars 2026**, deux séances attendues. Les mêmes absences sont présentes dans les fichiers or, santé et utilities. Aucune imputation n'a été effectuée. Le contrat de volatilité requiert 61 closes valides pour calculer 60 rendements consécutifs ; un seul trou peut donc neutraliser plusieurs décisions mensuelles.

| Décisions affectées | Refus enregistré | Conséquence effectivement exécutée |
| --- | --- | --- |
| 31 octobre, 28 novembre, 31 décembre 2025 | `ETF_US_TECH: NON_CONSECUTIVE_HISTORY` | Sortie intégrale Tech le 3 novembre 2025, poche or ; retour Tech le 2 février 2026 |
| 31 mars, 30 avril, 29 mai 2026 | `ETF_US_TECH: NON_CONSECUTIVE_HISTORY` | Sortie intégrale Tech le 1er avril 2026, poche matières premières ; retour Tech le 1er juillet 2026 |

Les positions sauvegardées confirment **62 séances sans technologie du 3 novembre au 30 janvier**, puis **62 du 1er avril au 30 juin** : 124 séances, soit 27,37 % des 453 séances du contrôle. Les six décisions de refus sont donc une politique explicite face aux données manquantes, pas un signal de volatilité économique extrême.

Sur le contrôle depuis cash, les quatre dates des séquences sortie/réentrée représentent 4 dates sur 10, 10 fills sur 22, **853,43 EUR de frais sur 1 312,07 EUR** et 853 433 EUR échangés. Cela représente environ 65,04 % des frais et du volume échangé. Dans le portefeuille continu, les quatre mêmes dates représentent 10 fills, 3 581,64 EUR de frais, soit 51,46 % des frais totaux.

Ce sont les frais observés aux dates de ces séquences, **pas un coût causal exact des trous**. Les poids de réentrée sont aussi déterminés par la volatilité alors disponible : 88,47 % de technologie à la décision du 30 janvier 2026, puis 69,85 % le 30 juin dans le contrôle depuis cash. Sans rejeu contrefactuel avec des données complètes, nous ne savons pas quels ordres auraient été passés autrement.

Les effets observés sont opposés :

| Entre clôtures, contrôle depuis cash | 71 | Technologie conservée | Nasdaq conservé |
| --- | ---: | ---: | ---: |
| 31 octobre 2025 → 30 janvier 2026 | +19,53 % | −8,30 % | −3,50 % |
| 31 mars 2026 → 30 juin 2026 | −1,88 % | +35,18 % | +29,91 % |

La première exclusion accompagne une hausse de l'or ; la seconde manque un fort rebond des actions. Ces comparaisons décrivent les parcours réellement observés, **pas un contre-backtest causal sans trous**. Aucun résultat ne doit être attribué au seul signal économique sur ces fenêtres. Le refus est cohérent avec le contrat de données figé ; il constitue néanmoins une forte sensibilité opérationnelle de la politique.

Pour reproduire cet audit sans calcul financier nouveau : lire `decisions.csv` (`session_date`, `decision_time`, `hold_positions`, `weights` JSON, `skipped` JSON), filtrer les six refus ; lire `fills.csv` (`session_date`, `instrument_id`, `side`, `quantity`, `total_cost`, `traded_value`) aux quatre dates ; compter les lignes de `weights.csv` où `ETF_US_TECH == 0`. Comparer les rapports de `net_equity` de `equity.csv` aux clôtures indiquées.

## Compagnons simples, interventions et rejets

55 et 79 utilisent des cibles fixes technologie/or, une vérification trimestrielle et une bande de 15 points. Aucun filtre de momentum ni calcul de volatilité ne conditionne leur bloc ; une disponibilité de cours récente reste requise. Les contrôles final et continu ne présentent aucun signal ignoré pour ces deux politiques.

- **55 : cible initiale 75/25.** Sur tout le continu, aucune dérive n'atteint la bande aux dates de décision : seuls les deux achats du 4 juin 2019 sont exécutés. Ce résultat équivaut à conserver le panier effectivement acheté, après arrondis et cash résiduel ; ce n'est pas une réussite de rotations actives. Expositions moyennes : 80,44 % technologie, 18,71 % or, 0,84 % cash. Aucun rejet sur les quatre rejeux normal/x2, continu/final.
- **79 : cible initiale 60/40.** Achats le 4 juin 2019, puis un seul rééquilibrage le 1er juillet 2024. Expositions moyennes : 62,88 % technologie, 36,52 % or, 0,60 % cash. Lors du rééquilibrage, 1 515 parts Tech sont vendues et 663 parts or achetées ; un reliquat d'achat de **4 parts or est rejeté pour `INSUFFICIENT_CASH`**. L'achat est donc partiellement exécuté, sans incident de données. Les frais des quatre fills, 189,54 EUR, et les positions réellement obtenues sont inclus dans le net. Le rejeu x2 conserve ce reliquat de quatre parts ; aucun rejet sur le contrôle depuis cash.

Aux frais doubles sur le continu, les gains restent de 438,93 % pour 55 et 399,40 % pour 79. La baisse maximale complète de 55/79 provient du 19 février au 23 mars 2020, avant les trous étudiés ; leur baisse maximale du contrôle se produit du 19 février au 7 avril 2025. La réduction du drawdown observée chez ces compagnons ne provient donc pas des exclusions prolongées de fenêtres de volatilité en 2025–2026.

Ces compromis satisfont descriptivement plusieurs préférences du propriétaire, mais leurs résultats restent inférieurs à la technologie conservée sur le continu. La faible intervention, la diversification avec l'or et la réduction de drawdown sont les bénéfices observés. Toute l'histoire a déjà été examinée dans le projet ; cinquante variantes supplémentaires et un univers choisi après coup interdisent de présenter ce constat comme une garantie future ou comme une validation prospective.