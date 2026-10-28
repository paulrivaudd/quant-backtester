# SA15_GPT-6.1 — série 4 : 50 variantes, Nasdaq, drawdown et interventions

Écrit le 16 octobre 2026, avant l'essai31. Le propriétaire autorise cinquante nouvelles configurations31–80 : quatre-vingts cumulées avec R1/R2/R3. Cette série conserve les résultats et les données antérieurs.

## Objectif économique

Battre le rendement net du Nasdaq acheté une fois et conservé, en favorisant une perte maximale historique limitée et peu de transactions. Cibles de recherche retenues faute de seuil imposé : drawdown de25% au plus et quatre dates avec transactions par an au plus. Ces seuils sont des préférences de classement et non des garanties de risque futur. Les meilleures alternatives de rendement, de risque et de fréquence seront aussi publiées sur une frontière de Pareto.

Les sorties réactives deR3 manquent des reprises. R4 examine plusieurs mécanismes distincts : allocation Nasdaq/or rééquilibrée peu souvent à poids fixes ou inverse-volatilité ; rotation relative avec préférence pour le cœur et tampons ; exposition graduelle par votes de tendances ; budget conditionné à la largeur de marché/canaries ; contrôle de volatilité plafonné sans levier. Les secteurs technologie américaine, santé mondiale et services collectifs mondiaux peuvent enrichir les univers explicitement configurés. Aucun réseau neuronal ou modèle ajusté sur tout l'historique n'est requis pour cette série.

Une simple exposition à la technologie ne prouve pas une capacité de timing. Références exécutables publiées : Nasdaq conservé (principal), S&P500 conservé, or ETC conservé,50/50 Nasdaq/or acheté puis conservé et technologie américaine conservée. Les références sont descriptives et ne remplacent jamais un candidat après le contrôle.

## Données, univers et exécution

Magasin isolé runs/sa15_gpt61_r4_store : copie inchangée des données SA15 existantes, plus QDVE.DE (technologieUS), XDWH.DE (santé mondiale) et XDWU.DE (utilities mondiales), classes capitalisantes existant avant2017. Les nouvelles séries sont archivées à partir de2017 par les sources, normaliseurs et validateurs du projet ; aucun historique de fonds prédécesseur n'est concaténé. Les classes et tickers sont vérifiés auprès des émetteurs. L'or est un ETC, pas un ETF UCITS. Pas de produit à levier. Les cours sont des historiques fournisseurs ajustés et restatés, pas des millésimes point-in-time ; l'univers actuel comporte un biais de sélection/survie à déclarer.

Onze véhicules enregistrés ; chaque stratégie configure un nombre limité de lignes, avec au plus trois positions du bloc offensif et quelques défenses. Calendriers XPAR/XETR, signaux aux dates exactes disponibles à23h Europe/Paris. Endpoints exacts pour momentum, séances consécutives pour moyennes/volatilité. Pas d'imputation. Ordres à l'ouverture négociable suivante ; parts entières ;100000EUR ; commission5pb minimum1EUR, demi-spread3pb, slippage2pb. Aucun short ni levier.

Cadence candidate mensuelle, trimestrielle ou hebdomadaire ; première décision dès la première séance puis vraies fins de période. Les jours de vérification sont distincts des dates produisant effectivement des fills. Les règles de volatilité plafonnent une estimation du bloc explicitement mesuré, sans garantie de volatilité totale ou de drawdown ; les éventuelles défenses hors bloc sont nommées.

## Périodes et score gelé avant31

Choix : UN VRAI portefeuille continu2019-06-03/2024-12-31 par candidat, sans reset en2023. Développement2019–2022 et sélection2023–2024 sont dérivés de cette même courbe ; la dernière clôture2022 ancre le calcul2023 pour inclure sa première séance. Les positions et coûts sont conservés aux frontières. Pas de concaténation de sous-runs indépendants.

Contrôle chronologique2025-01-02/2026-10-09 depuis cash pour le seul gagnant gelé. Parcours complet2019-06-03/2026-10-09 par nouvelle simulation continue après gel. TOUTE l'histoire avait déjà été examinée dans le projet : il s'agit d'une étude rétrospective, pas d'un échantillon vierge, même si les nouveaux secteurs n'avaient pas été étudiés par SA15.

Notations sur la période de choix : e=CAGR_candidat-CAGR_Nasdaq ; d=abs(drawdown_candidat), dn=abs(drawdown_Nasdaq), t=dates distinctes de fills par an ; ev=excès de CAGR dans le segment2023–2024 du portefeuille continu.

qualified = e>0 ET d<=0.25 ET t<=4.

score = e +0.20*(dn-d) -0.50*max(0,d-0.25) -0.001*max(0,t-4) -0.25*max(0,-ev).

Classement : qualified décroissant, score décroissant, numéro croissant. Toutes les unités sont des fractions de rendement, sauf t. Une amélioration de drawdown de10points ajoute2points au score ; le dépassement de la cible de risque et les périodes récentes déficitaires sont pénalisés. Un gagnant non qualifié n'est pas présenté comme ayant atteint les trois objectifs. Le meilleur rendement et les compromis de risque/interventions restent visibles, indépendamment du gagnant.

## Les cinquante itérations

Cinq lots de dix configurations. Le premier explore plusieurs familles et fréquences ; chaque lot suivant modifie les mécanismes et voisins à la lumière des seuls résultats de choix déjà calculés. Les dix JSON d'un lot sont archivés avec raisons et empreintes avant son premier run. Maximum50, aucun essai supplémentaire caché ou trente-et-unième design additionnel après80.

Les paramètres complets, cadences, identifiants et raisons sont écrits avant calcul. Les échecs sont publiés. Dépendances financières et données sont gelées avant31, sélection après les cinquante et avant tout nouveau résultat final/continu. Les courbes de contrôle ne peuvent changer le gagnant ni ses paramètres.

## Robustesse et verdict

Chacune des50politiques est rejouée réellement aux frais doubles sur le choix, sans réajustement. Gagnant normal et x2 sur le contrôle et le continu. Quatre vrais redémarrages depuis cash2020/2021/2022/2023 jusqu'à2024, chacun avec les mêmes cinq références également redémarrées : pas de simple rebasage de courbe. Ces contrôles ne sont pas de nouvelles configurations sélectionnables.

Publier net et brut, CAGR, drawdown, volatilité, Sharpe, expositions, frais, rejets, dates d'ordres et jours de vérification, plus les voisins et la frontière de Pareto. Bootstrap apparié du rendement actif moyen contre Nasdaq (blocs20séances,2000tirages,seed61154,intervalle95%) ; ce n'est pas un intervalle du CAGR. DSR avec80essais cumulés et les courbes disponibles explicitement comptées ; il mesure le Sharpe absolu, pas une probabilité de battre Nasdaq, et ne corrige pas tous les choix historiques du projet.

NOT_SUPPORTED si le rendement net du gagnant n'est pas supérieur au Nasdaq sur le continu ou le contrôle. UNCERTAIN si positif mais avantage absent aux frais doubles, intervalle actif comprenant zéro ou cibles de risque/fréquence non atteintes. SUPPORTED_RETROSPECTIVE seulement si tous ces critères tiennent ; aucune prétention de résultat futur garanti. Aucun ordre réel ni publication externe n'est autorisé ou nécessaire.
## Complément descriptif décidé avant le lot51–60 et tout contrôle2025–2026

Pour répondre aux préférences simultanées de risque et de travail du propriétaire, deux extrema parmi les seuls candidats qualified seront gelés en complément du gagnant principal, après50designs et AVANT selected.json / toute nouvelle simulation finale : (a) minimum de dates de fills/an, puis score décroissant et numéro croissant ; (b) drawdown le moins profond, mêmes départages. Les extrema sont choisis indépendamment, puis dédupliqués et le gagnant principal retiré ; il peut donc y avoir zéro, un ou deux compagnons.

Chaque compagnon est une politique déjà testée parmi31–80, sans nouveau paramètre. Quatre vrais rejeux descriptifs par compagnon : continu et contrôle, chacun aux coûts normaux et doubles. Ces diagnostics ne créent aucun design supplémentaire et ne peuvent remplacer le gagnant, modifier son score ni conduire à une retouche après contrôle. Les critères, IDs, empreintes et preuves sont enregistrés avant tout résultat futur dans un manifeste avec checksum. Le rapport les présente comme compromis descriptifs gelés, sans sélectionner après lecture de2025–2026. Le score et les résultats de choix31–50 restent inchangés.