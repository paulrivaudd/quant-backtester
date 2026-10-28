# SA15_GPT-6.1 — série 4 : littérature et univers

Note du **16 octobre 2026**, préparée avant les backtests R4. Elle motive des familles de règles ; le protocole et les cinquante configurations archivées définissent les expériences effectives. Aucun rendement des publications n'est attribué à SA15.

## Question et enseignements précédents

L'objectif est de battre la croissance nette de **100 % Nasdaq acheté puis conservé**, avec drawdown limité et peu d'interventions. Ces contraintes sont distinctes : le cash peut réduire le drawdown en sacrifiant la croissance ; une exposition technologique plus concentrée peut battre Nasdaq avec davantage de risque. Aucun de ces résultats ne démontre le succès conjoint.

R2 dépasse le S&P 500 mais reste sous Nasdaq. R3 manque notamment des rebonds après une sortie défensive : son gagnant ne satisfait ni croissance ni drawdown sur ses contrôles. Cela motive des mécanismes différents sans autoriser à programmer les bons rebonds connus après coup.

Le compte annoncé devient **80 designs SA15 cumulés**, dont 50 ici. Toutes les années 2019–2026 étaient déjà connues du projet. Les blocs chronologiques restent rétrospectifs. Les choix d'univers, de benchmark et de métrique ajoutent encore des degrés de liberté que le seul compte de 80 ne corrige pas.

## Cinq familles proposées

Une organisation de dix voisins par famille limite les retouches arbitraires. Le protocole effectif peut adapter cette répartition avant son premier essai. Aucun voisin supplémentaire ne doit sauver une conclusion défavorable après le cinquantième design.

1. **Rotation sectorielle lente.** Nasdaq, technologie, santé, services collectifs, avec défense déclarée. Quelques horizons combinés, une ou deux lignes, filtre absolu et tampon de classement. La technologie augmente la concentration avec Nasdaq ; un contrôle technologie conservée distingue exposition et utilité du timing.
2. **Cœur Nasdaq et protection partielle.** Fraction risquée permanente, défense réservée aux tendances faibles, retour explicite. Or et obligations ne sont pas des refuges certains. Une protection partielle manque moins de reprises mais protège moins d'une baisse prolongée.
3. **Ensemble de tendances gradué.** Les votes de quelques tendances ou moyennes mobiles déterminent la fraction risquée. Les horizons sont corrélés et ne constituent pas des preuves indépendantes. Une bande explicite évite les rééquilibrages minuscules.
4. **Largeur et canaris.** Budget risqué lié à la proportion d'expositions déclarées en tendance positive. Quelques ETF ne mesurent pas la vraie largeur de toutes les actions. Dénominateur fixe et traitement des absences sont nécessaires ; une ligne absente ne doit pas modifier silencieusement le signal.
5. **Volatilité et corrélation sans levier.** Réduction du risque en volatilité élevée ; covariance diagonale ou stabilisée, poids positifs et somme au plus 100 %. Cette gestion peut sacrifier la forte hausse d'actifs volatils. L'estimation des rendements attendus reste instable sur ce petit historique.

La cadence mensuelle est un point de départ ; une hebdomadaire doit compenser ses vérifications supplémentaires. Décision après les clôtures requises, exécution à l'ouverture négociable suivante, parts entières et coûts explicites.

## Sources scientifiques primaires

Pages NBER et AQR lues le 16 octobre 2026 ; PDF de Bailey et coauteurs vérifiés accessibles sur le site de l'auteur. Ces recherches motivent les mécanismes, pas une surperformance garantie de nos ETF.

- **Moskowitz, Ooi et Pedersen (2012), “Time Series Momentum”, Journal of Financial Economics 104(2), 228–250.** [Page des auteurs](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum). Tendance documentée sur futures et contrats de change diversifiés ; motivation des filtres et horizons. Instruments et positions diffèrent de notre petit univers long-only.
- **Daniel et Moskowitz (2016), “Momentum Crashes”, Journal of Financial Economics 122(2), 221–247 ; NBER 20439 (2014).** [Recherche originale](https://www.nber.org/papers/w20439). Certains épisodes défavorables au momentum coïncident avec panique et rebonds. Motivation de l'analyse des reprises manquées, sans seuil de retour déduit directement : leur momentum cross-sectionnel diffère de notre filtre Nasdaq.
- **Moreira et Muir (2017), “Volatility-Managed Portfolios”, Journal of Finance 72(4), 1611–1644 ; NBER 22208 (2016).** [Recherche originale](https://www.nber.org/papers/w22208). La réduction de risque en variance élevée motive la famille volatilité. Leur mise à l'échelle académique n'est pas notre règle plafonnée à 100 %, sans levier.
- **Gârleanu et Pedersen (2013), “Dynamic Trading with Predictable Returns and Transaction Costs”, Journal of Finance 68(6), 2309–2340 ; NBER 15205.** [Recherche originale](https://www.nber.org/papers/w15205). Prise en compte de la persistance des signaux et trading partiel avec coûts : motivation de l'inertie et des bandes, pas optimalité de nos seuils.
- **Novy-Marx et Velikov (2016), “A Taxonomy of Anomalies and Their Trading Costs”, Review of Financial Studies 29(1), 104–147 ; NBER 20721 (2014).** [Recherche originale](https://www.nber.org/papers/w20721). Coûts et seuils distincts d'achat/maintien motivent tampons et vrais runs aux frais doubles. Anomalies et instruments diffèrent des nôtres.
- **Bailey, Borwein, López de Prado et Zhu (2017), “The Probability of Backtest Overfitting”, Journal of Computational Finance 20(4), 39–69.** [Manuscrit de l'auteur](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf). Le meilleur résultat parmi de nombreux essais peut créer une illusion de compétence. Compter les essais et publier les perdants ne rend pas l'histoire vierge.
- **Bailey et López de Prado (2014), “The Deflated Sharpe Ratio”, Journal of Portfolio Management 40(5), 94–107.** [Manuscrit de l'auteur](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf). Annoncer les 80 designs corrélés et les courbes disponibles. Ce diagnostic n'est pas une probabilité de battre Nasdaq demain et ne corrige pas tous les choix du projet.

Les publications Keller/Keuning de R1 restent des inspirations possibles pour momentum accéléré et canari. SSRN a refusé la lecture automatique ici ; aucune nouvelle affirmation détaillée n'est ajoutée sur cette seule base. Les forums R3 fournissent des objections pratiques — faux signaux, reprises, frais — pas une preuve de performance.

## Nouveaux secteurs : vérification auprès des émetteurs

Le registre principal contient déjà des facteurs monde value, quality et minimum volatility ; ce ne sont pas des secteurs. Ajouter des fonds corrélés sans hypothèse claire ne crée pas une meilleure diversification.

| Symbole fournisseur à vérifier | Produit et ISIN | Classe / lancement officiel | Rôle |
| --- | --- | --- | --- |
| QDVE.DE | iShares S&P 500 Information Technology Sector UCITS ETF, IE00B3WJKG14 | USD Acc, 20/11/2015 ; listing Xetra EUR 02/12/2015 | Technologie, concentration Nasdaq |
| XDWH.DE | Xtrackers MSCI World Health Care UCITS ETF 1C, IE00BM67HK77 | USD capitalisante, 04/03/2016 | Santé développée |
| XDWU.DE | Xtrackers MSCI World Utilities UCITS ETF 1C, IE00BM67HQ30 | USD capitalisante, 16/03/2016 | Services collectifs, taux et régulation |
| XDWS.DE | Xtrackers MSCI World Consumer Staples UCITS ETF 1C, IE00BM67HN09 | USD capitalisante, 09/03/2016 | Consommation courante facultative |

Sources primaires : [iShares QDVE et cotations](https://www.ishares.com/uk/individual/en/products/280510/ishares-sp-500-information-technology-sector-ucits-etf), [DWS santé](https://etf.dws.com/de-de/IE00BM67HK77-msci-world-health-care-ucits-etf-1c/), [DWS utilities](https://etf.dws.com/de-de/IE00BM67HQ30-msci-world-utilities-ucits-etf-1c/), [DWS staples](https://etf.dws.com/de-de/IE00BM67HN09-msci-world-consumer-staples-ucits-etf-1c/). Les pages DWS confirment les tickers allemands XDWH GY, XDWU GY et XDWS GY, capitalisation et réplication physique. Le prédécesseur fusionné de 2010 mentionné par DWS n'autorise pas à antidater les classes de 2016. La cotation EUR conserve les devises sous-jacentes.

Au 16 octobre 2026, iShares déclare le **S&P 500 Capped 35/20 Information Technology Index NTR**, TER 0,15 %. Les trois DWS affichent 0,25 %. Cela ne prouve pas une méthodologie constante depuis lancement ; les prix du fonds portent ses changements effectivement subis.

Un appel de métadonnées Yahoo par symbole, sans backtest, indique la première observation fournisseur le 3 décembre 2015 pour QDVE et le 18 avril 2016 pour XDWH/XDWU/XDWS. La date de lancement ne crée pas les barres manquantes. Admission seulement après validation OHLC, calendriers, couverture et opérations sur titres. Toute extension doit utiliser un magasin R4 séparé ; anciens magasins et métadonnées restent immuables.

### Piste Nasdaq à levier

La [page officielle Amundi](https://www.amundietf.fr/fr/particuliers/produits/equity/amundi-nasdaq100-daily-2x-leveraged-ucits-etf-acc/fr0010342592) confirme **Amundi Nasdaq-100 Daily (2x) Leveraged UCITS ETF Acc**, FR0010342592, généralement LQQ.PA. Le 2x est quotidien, pas deux fois le rendement conservé sur plusieurs années. Gaps et dépendance au chemin demeurent ; le contrôle de volatilité ne garantit aucun drawdown.

Admission déconseillée sans audit complet des opérations sur titres. Yahoo ne signale aucun split dans le contrôle sommaire, mais une piste externe indique une division de part en 2026, non confirmée par un avis officiel accessible ici. Un événement absent du flux n'est pas la preuve de son absence. Ne pas reconstruire les quantités ni utiliser des prix potentiellement ajustés comme négociables. Aucun backtest LQQ n'a été calculé pour cette note. Le protocole décide de son exclusion avant essais ; un futur audit du levier serait distinct.

## Critères de lecture recommandés

- Succès conjoint : croissance nette supérieure au Nasdaq, drawdown réduit et charge opérationnelle contenue. Drawdown historique au plus 25 % et quatre jours de transactions par an sont des objectifs possibles à fixer avant essais, pas des garanties.
- Contrôles : Nasdaq reste principal ; technologie conservée et mélange statique simple distinguent exposition sectorielle et valeur des rotations.
- Interventions : publier jours de fills, ordres, rotation, frais et vérifications. Mensuel sans fill demande environ douze contrôles par an ; hebdomadaire environ cinquante-deux.
- Robustesse : voisins, redémarrages depuis cash, coûts doublés sans réestimation, années et épisodes sortie/reprise. Expliquer tout avantage concentré dans une crise ou un secteur.
- Risque porté : volatilité, exposition, cash, concentration et drawdown relatif. Un faible bêta obtenu par du cash n'établit pas un bon timing.
- Incertitude : bootstrap actif descriptif sur une histoire déjà vue. Cinquante essais ne créent pas cinquante périodes de marché indépendantes.
