# Améliorations nécessaires

État au 2026-09-26, après la réponse à l'audit de l'archive (9). Cette liste
recense ce qui limite encore ce qu'un résultat peut affirmer, classé par
priorité. La première version de cette note (`207d928`) comportait des erreurs
que l'audit a relevées ; elles sont corrigées ci-dessous, et chaque point dit
ce qui est fait, ce qui reste à faire, et pourquoi.

Légende : **P1** limite la validité d'un résultat, **P2** limite sa portée ou
sa reproductibilité, **P3** relève du confort ou de l'outillage.

## Fait depuis la première version

| Point | Ce qui a été fait |
|---|---|
| 1.3 Modèle d'exécution | `Sizing.AT_DECISION` : quantités fixées à la clôture de la décision, exécutées à l'ouverture, coupées au cash disponible. `scripts/sensitivity.py` : la rotation perd 0,01 point en ordres fixés la veille, près de 4 points à coûts doublés. |
| 2.1 Séances contestées | `metadata/conflict_reviews.toml` : les 13 conflits sont revus et tranchés en faveur d'Euronext, la place de cotation, pour les valeurs exactes revues. **La barre du 24 octobre 2025 coûtait 0,47 point, et non les « environ 4 points » que j'avais écrits sans les mesurer.** |
| 3.1 Dossier de run | `research.archive` : un run relu hors ligne sans recalcul, et recalculable à partir d'une copie vérifiée du store qu'il a lu. |
| 3.2 Environnement | La version de Python, l'empreinte de `uv.lock` et les versions de numpy, pandas, pyarrow et scipy entrent dans le `run_id`. |
| 4.1 Incertitude | `analytics.uncertainty` : bootstrap par blocs apparié entre la stratégie et son témoin exécutable. Sur la période du README, l'intervalle des Sharpe exclut zéro : le Sharpe de la rotation est le plus bas. |
| 4.2 Hypothèses et verdicts | `research/hypotheses.toml` : les 19 runs existants sont déclarés `EXPLORATORY`. Les verdicts sont des événements, sans réécriture d'un run ni variante supplémentaire. |
| 4.4 Comparateur exécutable | La suite README compare la rotation à un buy & hold du fonds monde soumis aux mêmes coûts, lots et cash. |
| 5.1 Intégration continue | GitHub Actions : ruff, format, pyright et tests hors ligne à chaque push, tests réseau chaque nuit. |
| Paper trading | `contract_id`, journal de l'état économique complet, code commité obligatoire, séance prise en compte seulement une fois prête (23:00 Paris), journaux sous verrou. |

## Corrections apportées à la première version (audit de l'archive 9)

- **1.5** : le cash n'était **pas** « pénalisé deux fois ». Le Sharpe retranche le taux sans risque une seule fois. Un cash non rémunéré coûte `(1 − w) × r_ref` en coût d'opportunité, ce n'est pas un second prélèvement.
- **2.2** : US10Y n'est lu par **aucune** baseline actuelle (la jauge de `MomentumVix` est le VIX). Le passer en millésimes ne déplace aucun chiffre publié.
- **2.5 et 4.5** : les univers datés existent déjà, et le turnover annuel comme le cash moyen sont déjà calculés et affichés dans le rapport.
- **5.2** : le paper trading doit tourner après 23:00 Paris, l'heure de décision, pas « après la clôture européenne ».
- **1.1** : un dividende sur une position détenue se comptabilise comme une créance à l'ex-date, réglée au paiement. Le seul cash au paiement créerait une fausse perte puis une fausse récupération.

## Ce qui reste

| # | Prio | Problème | Ce qu'il faudrait |
|---|---|---|---|
| 1.1 | P1, avant d'élargir l'univers | Un split ou un dividende sur une ligne détenue arrête le run. | Une comptabilité des droits : créance à l'ex-date, règlement au paiement, split sur les quantités et le coût moyen, retenue à la source déclarée. |
| 1.2 | P1, avant d'élargir l'univers | Une radiation d'une ligne détenue arrête le run. | Une politique déclarée par cas : rachat, dernier cours négociable, valeur de récupération. |
| 1.4 | P2 | Pas de plafond de participation au volume, et un spread unique pour tous les instruments. | Un plafond calculé sur un volume **passé** (le volume de la journée n'est pas connu à l'ouverture), et un spread par instrument. |
| 1.5 | P3 | Le cash n'est pas rémunéré. | Une convention de placement déclarée si on en veut une : taux obtenu, jours courus, disponibilité. Elle reste distincte du taux de référence du Sharpe. |
| 1.6 | P3 | Le brut est une attribution à fills constants. | Un run sans frais en contrefactuel, sous son propre nom. |
| 1.7 | P3 | Une seule devise de compte. | Des comptes de cash par devise et une valorisation au taux de change disponible, avant tout actif hors euro. |
| 2.2 | P2, avant toute stratégie qui lit US10Y | US10Y est déclaré `RESTATED`. | ALFRED en `AS_OF_DECISION`. Pour une série quotidienne, cela demande un millésime par jour ouvré, donc une dimension de stockage à concevoir. Depuis N08, tout run qui le lit l'affiche dans son rapport. |
| 2.3 | P2 | Les historiques Yahoo sont `ASSUMED_UNREVISED` sans preuve. | Un rapport des révisions observées entre téléchargements. Les refetchs à venir ne prouveront rien sur la période antérieure au premier archivage. |
| 2.4 | P2 | Aucune seconde source ne couvre ESE avant 2024. | Une source historique indépendante, pour les périodes qu'on voudra effectivement utiliser. |
| 2.5 | P2, avant d'élargir l'univers | Aucun titre mort dans les univers. | Les données des membres sortis : cours, événements, dates. Le mécanisme d'univers daté existe déjà. |
| 3.3 | P3 | Pas de générations immuables du store. | Les dossiers de run avec copie du store couvrent le besoin de conservation. Des générations ne seraient utiles que pour un store partagé. |
| 4.3 | P2 | Pas de moteur de balayage de paramètres. | Une grille déclarée, avec dates de départ glissantes et coûts ×1 et ×2, chaque point inscrit au registre, et un budget d'essais fixé à l'avance. |
| 4.6 | P3 | Signaux S4/S5, `StrategyState`. | Seulement après 4.3, sinon on multiplie des variantes qu'on ne sait pas juger. |
| 5.3 | P2 | Les scripts n'ont pas de tests de fumée. | Des tests sur un store synthétique : arguments, sorties, codes de retour, double lancement. |
| 5.4 | P3 | Des notes d'exercice en français subsistent dans des docstrings en anglais. | Les réécrire quand ces fichiers sont repris. |
