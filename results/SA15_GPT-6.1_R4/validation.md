# Vérifications de la série R4

Le 16 octobre 2026. Cette note distingue la conformité des calculs de la réussite économique. Les résultats financiers sauvegardés font foi ; une suite de tests verte ne démontre pas une surperformance future.

## Code et architecture

Commande exécutée dans la venv existante du projet :

```sh
.venv/bin/pytest tests/strategies/test_SA15_gpt61_riskaware.py tests/scripts/test_SA15_run_gpt61_round4.py tests/scripts/test_SA15_diagnostics_gpt61_round4.py tests/scripts/test_SA15_report_gpt61_round4.py tests/test_package_structure.py -q
```

**536 tests réussis en 17,16 s** : 80 stratégie, 49 orchestration, 21 diagnostics compagnons, 19 restitution et 367 architecture. Vérifications significatives : absence d'anticipation, endpoints exacts et fenêtres consécutives, poids et canaris incomplets, limites du bloc offensif, cadence et bandes, segments d'un portefeuille continu sans reset, score figé, sélections indépendantes des compagnons, refus d'écrasement et restitution depuis les seuls résultats sauvegardés.

Ruff check et format --check ont réussi sur les neuf nouveaux fichiers Python R4 avant les runs puis sur leur état final. git diff --check est propre. Les seules modifications ultérieures du rapport sont de présentation ; ses tests et son empreinte sont consignés séparément. Aucun paquet installé ou moteur financier modifié pendant les calculs.

## Intégrité de l'expérience

- 50 nouveaux designs numérotés 31–80, en cinq lots de dix. Aucun design 81 ; 80 designs SA15 cumulés.
- Les 50 JSON de recherche, les cinq manifestes de lots, les configurations exécutées, caches, scores et sous-périodes ont été comparés intégralement. 28 candidats qualifiés sur la période de choix.
- Gagnant 71 conforme au score ; extrema descriptifs 55 et 79 choisis indépendamment selon le complément écrit avant le troisième lot et tout nouveau contrôle. Manifestes selected et companions_frozen et leurs checksums vérifiés. Aucun remplacement du gagnant après lecture du contrôle.
- Les 110 sources financières ont été revérifiées après les 50 essais et la sélection : empreinte agrégée `17a142becbc360b3ea61f49085ddf5f2eb634911bed184c86241335c6f4244e1`, inchangée.
- Archives sources R1–R4 : checksums ZIP et chaque membre vérifiés. Archives et sources financières antérieures intactes.
- Les 22 fichiers de prix/niveaux antérieurs sont identiques bit à bit dans la copie R4. Registre et journal des trois nouvelles collectes sont des ajouts administratifs au seul magasin R4.

## Calculs et limites opérationnelles

La sélection utilise un seul portefeuille continu 2019–2024 par candidat. Les sous-périodes sont des segments du même portefeuille ; 2023 garde son close d'ancrage 2022. Le contrôle 2025–2026 repart réellement de cash. Le parcours complet est une nouvelle simulation continue, après sélection. Toutes les années avaient déjà été examinées : aucune période n'est vierge ou prospective.

Les contrôles exécutés comprennent 50 vrais rejeux de choix aux frais doubles, 24 redémarrages depuis cash (quatre départs et six politiques comparables) et sept parcours complets, soit 81 diagnostics. Les deux compagnons figés ont chacun quatre simulations supplémentaires (continu et contrôle, frais normaux et doubles), soit huit rejeux descriptifs. Ils n'ajoutent aucun design sélectionnable.

Le candidat 71 ne bat pas Nasdaq sur le contrôle final : hypothèse principale **NOT_SUPPORTED**. La restitution publie également les deux compromis gelés sans les substituer au gagnant. Deux trous de données rendent ses fenêtres de volatilité inutilisables plusieurs mois : les décisions archivées et operational_audit.md distinguent cette politique d'absence de données d'un véritable signal de volatilité. Les trous ne sont ni réparés après résultat ni interprétés comme une expérience causale sans trous.

Pour les politiques peu actives, les dates de transactions incluent l'achat initial ; elles se distinguent des vérifications trimestrielles. Les poids cibles peuvent dériver dans la bande de 15 points. Les rendements sont nets des frais modélisés, en EUR, avant fiscalité. L'or est un ETC. Drawdown passé, hypothèses de liquidité et prix restatés ne garantissent pas le risque futur.

Le rapport final et reporting_manifest.json identifient les exports de présentation sans modifier les archives financières. La génération des tableaux, figures et diagnostics statistiques ne lance aucun backtest.
Vérification indépendante après fin des processus (exit 0) : tableaux de robustesse de 50, 24 et 7 lignes, huit metrics.json compagnons, 50 JSON candidats, 110 sources financières toujours inchangées. Contrôle final et parcours complet effectivement sauvegardés, sans nouveau candidat ni modification de paramètres.
Inspection visuelle indépendante des figures comparison/full/comparison.png, comparison/final/comparison.png et frontier.png : axes, légendes, huit portefeuilles et niveaux terminaux cohérents avec les métriques. Les trois références secondaires sont visibles, les compagnons ne remplacent pas le gagnant. Les précisions finales de texte/unité/reproduction sont suivies d'un nouveau passage des 19 tests du rapport et de Ruff, sans changement financier.