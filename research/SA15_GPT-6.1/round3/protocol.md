# SA15_GPT-6.1 — troisième série : battre 100 % Nasdaq conservé

Écrit le 15 octobre 2026, avant le premier candidat21. Le propriétaire autorise dix nouveaux designs21–30, soit trente cumulés. Les références restent des contrôles descriptifs, jamais des candidats sélectionnables. R1 et R2 sont conservés sans modification.

## Objectif et hypothèse

La référence économique est ETF_NASDAQ acheté une fois et conservé. Surperformance de croissance nette, mêmes dates, deviseEUR, capital100000EUR et coûts. Un Sharpe supérieur ou une baisse maximale plus faible ne remplace pas cette cible de rendement.

La série2 dilue le Nasdaq dans les reprises. Hypothèse de départ : garder Nasdaq par défaut et protéger seulement des régimes faibles, avec retour rapide lorsque la tendance courte se rétablit. Défense sur un nombre limité d'instruments déjà disponibles : or (ETC, pas ETF UCITS), S&P500 et éventuellement monétaire. Des variantes explicites peuvent comparer le momentum relatif à l'or ou un filtre de moyenne mobile. Aucun levier ni vente à découvert.

Maximum dix configurations, écrites une à une avant leur calcul et conservées avec motif. Les candidats voisins sont choisis après lecture du développement et de la sélection précédents. Pas de grille cachée, de recherche supplémentaire ou de onzième modification après lecture du contrôle. Tout échec est publié.

## Calendriers, signaux et exécution

Données et métadonnées du store isolé runs/sa15_gpt61_store. Univers enregistré inchangé (huit véhicules). Signaux sur les cours ajustés disponibles au plus tard à la décision23h Europe/Paris, calendriers propres XPAR/XETR. Momentum aux endpoints exacts ; aucune imputation. Les moyennes mobiles éventuelles requièrent leurs séances consécutives exactes et refusent les trous.

Ordres exécutés à la prochaine ouverture négociable, avec parts entières. Cadence candidate déclarée : mensuelle, hebdomadaire ou quotidienne. Mensuel/hebdomadaire comprennent une première décision dès la première séance du run, puis les vraies fins de période, comme enR2. Les jours de contrôle et les dates ayant réellement généré des transactions sont publiés séparément.

Commission5pb minimum1EUR, demi-spread3pb, slippage2pb ; aucune modification du moteur. Les prix fournisseurs sont ajustés/restatés, pas des archives de millésimes historiques point-in-time. Les limites de données deR1 restent applicables.

## Périodes et sélection

Développement2019-06-03/2022-12-30 ; sélection2023-01-02/2024-12-31. Contrôle chronologique2025-01-02/2026-10-09 ; continu2019-06-03/2026-10-09. Toute cette histoire a déjà été vue dans le projet. Ces périodes sont des contrôles rétrospectifs, jamais un échantillon vierge ni une validation prospective.

Pour chaque période de choix : e = CAGR_candidat - CAGR_Nasdaq_conservé. Priorité aux candidats ayant e>0 sur développement ET sélection ; puis score décroissant, puis premier numéro. Score = moyenne(e_dev,e_selection) -0.25*abs(e_dev-e_selection). Les gains contre le seul S&P500 ne peuvent justifier un succès.

Le gagnant est gelé après les dix candidats et avant tout nouveau calcul final/continu. Pas de changement de gagnant après le contrôle final, les coûts doubles ou les redémarrages. Les courbes S&P500 et50/50 initial conservé restent publiées pour contexte ; référence principaleNasdaq.

## Diagnostics et verdict

Rejouer les dix candidats aux frais doubles en développement/sélection ; gagnant aux frais doubles sur contrôle. Quatre vrais redémarrages depuis cash2020/2021/2022/2023 jusqu'à2024 ; historique continu du gagnant et trois références. Ces rejeux ne constituent pas de nouveaux designs.

Comparer net et brut, CAGR, drawdown, volatilité, exposition, frais, rotation et interventions. Bootstrap apparié du rendement actif moyen contre Nasdaq (blocs20séances,2000tirages,seed61153), avec intervalle95% ; ceci n'est pas un intervalle du CAGR. Déflater le Sharpe en annonçant30designs cumulés et les séries réellement disponibles ; ce diagnostic ne corrige pas tous les choix antérieurs du projet.

NOT_SUPPORTED si le gagnant ne dépasse pas Nasdaq net sur le contrôle ou le continu ; UNCERTAIN si positif mais disparaît aux frais doubles ou si l'intervalle du rendement actif inclut zéro ; SUPPORTED_RETROSPECTIVE seulement si l'ensemble des critères tient, sans prétention prospective. L'objectif demeure le rendement absolu supérieur au Nasdaq conservé, pas le seul confort de risque.