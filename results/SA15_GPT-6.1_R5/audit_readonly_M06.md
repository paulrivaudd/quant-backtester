# Audit en lecture seule — M01 à M06

Audit réalisé le 16 octobre 2026 pendant l'exécution des expériences suivantes. Aucun backtest, ordre, téléchargement ou changement de source financière n'a été effectué par l'auditeur. Cette note est un artefact narratif ; elle n'entre pas dans les critères de sélection.

## Chaîne de preuves

- Les six `verify_completed(..., deep=True)` ont réussi : candidats archivés, contrats, métriques, caches physiques et copies par rôle, sommes de contrôle de tous les artefacts, analyses préalables et scores recalculés.
- 96 contrats logiques de comparaison utilisent 66 simulations physiques distinctes, dont 33 aux frais doubles. Les répétitions exactement identiques sont réutilisées ; les frais doubles possèdent leurs propres contrats et simulations.
- M01 comporte précisément 16 contrats et 14 simulations distinctes : le parent correspond à l'ablation de la reprise, aux deux niveaux de frais.
- Chaque candidat modifie uniquement le mécanisme déclaré par rapport à son parent. Les contrats de choix s'arrêtent tous au 31 décembre 2024, avec départ au 3 juin 2019 ; aucune période 2025–2026 n'entre dans les scores.
- Les 112 sources financières correspondent au gel et aux membres de `source/source.zip`. Leur empreinte canonique est `fe61aa9b520c5fcaead9ca0c34aded9dbbab261d39fa5be770b82819085902e6`.
- Les 41 fichiers de données et métadonnées correspondent tous au gel ; aucun ajout n'a été détecté.

## Journaux de décisions

8 400 lignes du journal passif ont été contrôlées. Tous les instants ont un fuseau et correspondent à 23 h Europe/Paris. Les signaux disponibles sont finis, les poids sont positifs et leur somme ne dépasse pas un. Le poids Nasdaq enregistré correspond au plan avant bande.

Pour les 5 192 lignes où `hold_positions` est vrai, le plan proposé reste enregistré séparément du maintien officiel. Pour les autres lignes, les poids officiels correspondent exactement aux poids du plan. Les transactions réalisées et les poids du portefeuille restent les sources de vérité après exécution.

## Correctif de sérialisation et parent d'origine

Une comparaison préalable a confirmé que les quatre fichiers `equity.csv`, `gross_equity.csv`, `fills.csv` et `weights.csv` du premier candidat sont identiques octet par octet avant et après la correction de jointure des instants du journal. L'essai échoué est conservé dans `../SA15_GPT-6.1_R5_attempt01_audit_timestamp_error/` et constitue une simulation physique supplémentaire, distincte des 66 caches actifs comptés ici.

Les mêmes quatre fichiers du parent M00 aux frais normaux sont identiques au pilote d'origine `../SA15_GPT-6.1_mechanism_pilot/choice/costs_x1/full/`. Tous les indicateurs concordent : CAGR 19,6875457 %, drawdown −23,1471099 %, 22 dates de transactions, 27 exécutions et frais de 1 396,659894 €.

Aucune anomalie détectée. Cet audit vérifie la fidélité des calculs et de leur traçabilité ; il ne transforme pas l'historique déjà exploré en validation indépendante.