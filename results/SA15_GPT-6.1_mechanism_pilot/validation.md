# Vérifications du pilote par mécanismes

16 octobre 2026. Une itération principale et quatre contrôles annoncés avant calcul, cinq politiques examinées, trente simulations (trois périodes et deux barèmes de frais). Aucun balayage de poids, horizons, bandes ou seuils, aucun changement de configuration après les résultats. Les paramètres initiaux sont simples et repris de composants existants, sur un historique déjà exploré : ce n'est pas une sélection indépendante du passé.

## Vérifications avant backtest

- Hypothèse complète et formules dans research/SA15_GPT-6.1/mechanism_pilot/hypothesis.json et inscription préalable au registre central.
- Audit de couverture Nasdaq et monétaire : aucune séance XETR manquante du01/06/2018 au09/10/2026, couvrant l'amorce200séances. Les deux fichiers et leurs SHA sont dans data_audit.json. Aucun téléchargement ni réparation.
- Revue indépendante des cinq politiques, des ablations et du moteur : seuls les deux blocs direction/risque sont activés ou retirés ; mêmes univers, capital, calendrier, cadence mensuelle, lots et coûts.
- 465 tests réussis en7,94s :18pilote,80stratégie réutilisée,367architecture. Commande :

```sh
.venv/bin/pytest tests/scripts/test_SA15_mechanism_pilot.py tests/strategies/test_SA15_gpt61_riskaware.py tests/test_package_structure.py -q
```

## Vérifications après les trente simulations

Processus terminé avec code0. Manifest.json et SHA valides ; les30contrats annoncés possèdent des résultats. Chaque checksum d'artifact et chaque identité de données a été revérifié indépendamment. Les111sources financières sont inchangées depuis le gel.

Les dix préfixes de courbe du parcours complet jusqu'à fin2024 sont exactement identiques à leurs dix runs de choix (cinq politiques x deux barèmes de frais). Ajouter les années suivantes n'a changé aucune valeur passée. Les six courbes du contrôle sans les deux blocs sont exactement identiques au Nasdaq conservé (trois périodes x deux barèmes), ce qui contrôle les conditions communes. Aucun résultat antérieur R1–R4 modifié.

Les replays sont de vrais portefeuilles depuis cash, pas des courbes bricolées ou des poids appliqués après connaissance des rendements. Les régimes du rendement de t ne lisent que les NAV arrêtées àt-1. Les différences de drawdown ne sont pas additionnées ; l'interaction est fournie séparément en log-croissance. Les expositions de clôture ne sont jamais multipliées par le rendement du jour pour inventer une attribution exacte des fills d'ouverture.

## Lecture économique

L'assemblage complet échoue contre Nasdaq sur le contrôle et le continu : NOT_SUPPORTED. Le registre central est mis à jour, l'hypothèse et les contrats archivés restent intacts. Aucun contrôle n'est promu après lecture. Les diagnostics de chaque bloc présentent ses avantages et ses coûts ; les catégories et tous les épisodes sont exportés sans sélection des seuls bons exemples.

Les trente runs comprennent réellement tous les coûts doubles. Ils ne constituent pas une validation prospective. Départs annuels et voisinages non sélectionnables restent nécessaires avant toute conclusion de robustesse favorable ; cette étude peut déjà réfuter son objectif économique sans les invoquer comme confirmation. Le DSR absolu descriptif utilise85essais déclarés et une dispersion héritée des80courbes antérieures, approximation explicitée ; il ne mesure pas une probabilité de battre Nasdaq.

Inspection visuelle indépendante des deux graphiques full_curves.png et control_curves.png : axes, cinq politiques, capital et drawdown cohérents ; la superposition du contrôle sans blocs et du Nasdaq est attendue. Le rapport ne relance aucun backtest ; son code et ses sorties portent un manifeste de présentation distinct.
## État final

490 tests réunis ont réussi en7,59s :18pilote,25rapport,80stratégie réutilisée et367architecture. Ruff check, Ruff format --check des quatre nouveaux fichiers Python et git diff --check sont propres. Commande finale :

```sh
.venv/bin/pytest tests/scripts/test_SA15_mechanism_pilot.py tests/scripts/test_SA15_report_mechanism_pilot.py tests/strategies/test_SA15_gpt61_riskaware.py tests/test_package_structure.py -q
```

Les SHA de tous les fichiers du reporting_manifest final et du code de restitution concordent. Les111sources financières du pilote et les110sources gelées de R4 sont toujours intactes. Trente résultats et verdict NOT_SUPPORTED confirmés après la dernière restitution. Aucun ordre réel, aucune dépendance installée et aucun commit créé.