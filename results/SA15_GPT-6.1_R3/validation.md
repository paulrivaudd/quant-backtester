# Vérifications — SA15_GPT-6.1, troisième série

- Dix designs21–30 terminés, trente cumulés ; aucun trente-et-unième candidat. Configurations et raisons enregistrées avant chaque calcul. Aucun candidat ne bat le Nasdaq dans les DEUX périodes de choix.
- L'essai30 est retenu selon le score déclaré, pas selon le contrôle final. Son développement perd0,053 point de CAGR contre Nasdaq ; sa sélection2023–2024, redémarrée depuis cash, reproduit exactement le Nasdaq conservé. Le continu reporte ses positions défensives de décembre2022 et son année2023 diffère :48,04% contre50,53% pour Nasdaq ; les sous-runs ne sont pas concaténés pour fabriquer le continu.
- Hypothèse et protocole écrits avant21. L'histoire2019–2026 avait déjà été vue : contrôle rétrospectif, pas de validation prospective.
- Stratégie et driver gelés avant21. driver_frozen.json couvre110 fichiers financiers. Avant le gel final, scores et métriques sont recalculés à partir des preuves de développement/sélection vérifiées. selected.json possède son checksum indépendant et est écrit avant toute lecture de la nouvelle période finale.
- 487 tests passent ensemble :58 stratégie,41 runner,24 rapport,364 architecture. Ruff check et format --check passent sur les six nouveaux fichiers Python.
- Le core reste Nasdaq par défaut ; les règles utilisent seulement les signaux disponibles au soir. Le momentum compare les endpoints exacts du calendrier propre ; les MA éventuelles exigent des séances consécutives. Les tests couvrent futur, prix manquant, état initialcash, parts entières et ordres rejetés.
- Aucune mémoire cachée de régime : la persistance utilise les positions effectivement détenues. Le retour rapide est évalué uniquement aux décisions prévues ; le gagnant hebdomadaire ne comporte pas de protection intrasemaine.
- Exécution à l'ouverture négociable suivante, parts entières, capital100000EUR, commission5pb minimum1EUR, demi-spread3pb et slippage2pb. Aucun levier ni short. Les prix ajustés fournisseurs sont restatés, pas point-in-time.
- Six références dev/sélection R2 copiées uniquement après vérification stricte des signatures, checksums, identités et configurations. Les autres contrôles ont été rejoués avec les mêmes conditions.
- Vingt rejeux aux frais doubles en développement/sélection, gagnant aux frais doubles sur le final, quatre vrais redémarrages depuis cash et quatre livres continus terminés. Ces diagnostics ne changent ni paramètres ni gagnant.
- Rapport autonome : lit uniquement les résultats sauvés, ne construit aucun runner. Nasdaq est la référence pour alpha, bêta, patrimoine relatif, bootstrap et verdict. Les tests couvrent explicitement le cas favorable au S&P500 mais défavorable au Nasdaq.
- Les deux données Gold absentes des24/10/2025 et06/03/2026 provoquent des refus individuels ; le livre reste Nasdaq aux deux dates. Les deux rejets d'achat Gold pour cash insuffisant sont distincts et inclus dans le journal et les métriques.
- Les archives R1 et R2 restent intactes : SHA256 respectifs542500e8d8daa18dbb5889284867a5cff2c6bb996a53f3fb5ffd586d8e6fece9 et a6b7d2f7963728584d9dfb25f2c3abe947a6e62b7c8d7d97e61fb1c696cc73a7. Aucun prix, dépendance, lockfile, moteur ou ancien résultat modifié.

## Résultat économique

Continu2019-06-03/2026-10-09 : gain net316,96% contre348,00% Nasdaq ; CAGR21,44% contre22,63% ; drawdown-33,01% contre-31,05%. Le gagnant compte20 dates de transactions (38fills) et3610,33EUR de frais contre un achat/97,82EUR pour Nasdaq.

Final2025-01-02/2026-10-09 : gain net27,74% contre34,32% ; drawdown-27,40% contre-26,30%. Les deux détours vers l'or manquent des rebonds Nasdaq :07/04→28/04/2025, Nasdaq+14,23% contre or+5,49% ;30/03→13/04/2026, Nasdaq+5,96% contre or+3,05%. Le coût des allers-retours s'ajoute à la reprise manquée.

Verdict : NOT_SUPPORTED. Ni rendement supérieur ni baisse maximale améliorée sur les deux contrôles. Les faibles différences entre horizons ne justifient pas d'adopter cette variante. Les courbes et le manifeste de rendu sont produits depuis les résultats archivés ; aucune retouche de stratégie après le contrôle final.
Les figures continues et finales sont inspectées visuellement ; axes, base100, patrimoine relatif Nasdaq et drawdown concordent avec les exports. L'audit final confirme les110 fichiers financiers gelés, les dix designs et le checksum de selected.json.
