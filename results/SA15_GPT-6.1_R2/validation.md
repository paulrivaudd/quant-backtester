# Vérifications — SA15_GPT-6.1, seconde série

- 482 tests passent ensemble : 72 tests des nouveaux signaux/stratégie, 36 du runner, 13 du rapport et 361 d'architecture.
- Ruff check et Ruff format --check passent sur les huit nouveaux fichiers Python ; les 13 tests du rapport passent à nouveau après sa dernière retouche de présentation.
- Le momentum utilise les endpoints exacts du calendrier propre au titre. Tests de trous intermédiaires, endpoint absent, cours futur, couverture de calendrier, avant clôture et jours fériés.
- La sélection est fondée uniquement sur l'excès net contre le S&P500 en développement/sélection. L'essai17 a été gelé avant le calcul de ses périodes finale et continue.
- Dix nouveaux designs11–20 ; vingt designs cumulés. Vingt rejeux aux frais doubles sur développement/sélection, quatre vrais redémarrages depuis cash et quatre livres sur l'historique complet. Ces rejeux ne changent ni le gagnant ni ses paramètres.
- La première décision mensuelle intervient à la première séance du run ; les suivantes aux vraies fins de mois. Chaque ordre utilise l'ouverture suivante, jamais la clôture qui a fourni le signal.
- Les références sont S&P500 conservé, Nasdaq conservé et portefeuille50/50 acheté une fois puis conservé sans rééquilibrage.
- L'empreinte du driver a été complétée pendant la mise en place initiale : les essais11/12 ont été rejoués sans changement de politique, et métriques et fichiers de courbes sont strictement identiques. Leurs premiers originaux sont conservés sous original_before_driver_freeze/. Chaque période conserve son driver_freeze_verification.json.
- Les sources et métadonnées sont archivées dans source/. Les prix et les résultats de la première série n'ont pas été modifiés.
- Le rapport lit uniquement les résultats sauvegardés ; ses tests interdisent toute invocation d'un backtest. Les retouches de présentation après le gel sont consignées dans reporting_manifest.json.
- Les courbes complètes et finales sont inspectées visuellement ; la fréquence des contrôles est distinguée des jours ayant réellement produit des ordres.
- Aucun package n'a été ajouté, ni dépendance ou lockfile changé.

Résultat : le rendement net continu dépasse le S&P500, mais l'avantage2025–2026 ne résiste pas aux frais doubles et son intervalle d'incertitude recouvre zéro. Le statut de l'hypothèse reste UNCERTAIN. Le contrôle Nasdaq conservé est plus rentable sur cet historique ; une surperformance contre le seul S&P500 ne démontre donc pas l'utilité des rotations.
