# SA15_GPT-6.1 — données et limites de l'univers

Magasin isolé : `runs/sa15_gpt61_store`. La préparation des données ne lance
aucun backtest et ne modifie ni le registre principal ni les résultats antérieurs.
La fenêtre de recherche se termine le **9 octobre 2026**. Le premier jour prévu
pour la simulation est le 3 juin 2019, après la période d'échauffement.
Les cours sont des instantanés historiques téléchargés le 15 octobre 2026,
pas des archives constituées aux dates des décisions anciennes.

| Identifiant | Symbole Yahoo | Instrument / exposition | Première ligne clean | Nombre de lignes au 09/10/2026 |
|---|---|---|---|---:|
| ETF_SP500_PEA | ESE.PA | BNP Easy S&P 500, PEA, EUR | 2014-03-18 | 3211 |
| ETF_WORLD | CW8.PA | Amundi MSCI World, PEA, EUR | 2018-04-18 | 2172 |
| ETF_MONETARY_EUR | XEON.DE | Xtrackers II taux monétaire EUR, capitalisant | 2014-01-02 | 3240 |
| ETF_NASDAQ | SXRV.DE | iShares Nasdaq 100, capitalisant, non couvert en EUR | 2014-01-02 | 3240 |
| ETF_EMERGING | IS3N.DE | iShares Core MSCI EM IMI, capitalisant, non couvert en EUR | 2014-06-12 | 3126 |
| ETF_GOLD | 4GLD.DE | Xetra-Gold, ETC physique, titre de créance | 2018-01-02 | 2226 |
| ETF_EURO_GOV | DBZB.DE | Xtrackers II Global Government Bond 1C, couvert en EUR | 2014-01-02 | 3240 |
| ETF_COMMODITY | XDBC.DE | Xtrackers Bloomberg Commodity ex-Agriculture & Livestock Swap 1C, couvert en EUR | 2014-01-02 | 3240 |

Toutes les transactions sont en EUR sur Paris ou Xetra. La devise de cotation
ne supprime pas les expositions de change des actifs sous-jacents. SXRV et
IS3N ne sont pas couverts en EUR ; DBZB et la part **1C de XDBC** le sont. Seuls
ESE et CW8 sont ici documentés comme éligibles au PEA. Les ordres portent sur
des parts entières (`quantity_step=1`).

`ETF_EURO_GOV` est un identifiant technique : son sous-jacent est un panier
**mondial** d'obligations souveraines de pays développés, couvert en EUR, et non
un panier exclusivement composé de souverains de la zone euro. Le RIC officiel
DWS `XGSH.DE` et le candidat `DBXN.DE` sont inconnus de Yahoo ; le symbole de
marché `DBZB.DE` fournit la série attendue. Le registre isolé avant correction
de cette correspondance est conservé sous `metadata_snapshots/`, avec le journal
`metadata_symbol_review.json`. Cette correction a précédé tout backtest.

4GLD est un **ETC**, non un fonds UCITS et non un ETF diversifié. Il existe un
risque lié à la structure de titre de créance, au dépositaire et au droit de
livraison. Le modèle de données ne dispose pas d'un type ETC : `asset_type=ETF`
lui applique les contrôles de cours et d'opérations sur titres. Le code
`ACCUMULATING` exprime ici uniquement l'absence de distribution monétaire
attendue ; ce n'est pas une qualification juridique de fonds capitalisant.

**Erratum documentaire du registre initial :** la note `history_note` de XDBC
indique à tort que la part n'est pas couverte en EUR, et son nom y est abrégé.
La part LU0292106167 est couverte en EUR et exclut agriculture et élevage.
Le présent document corrige ces caractéristiques. Aucune métadonnée n'a été
réécrite pendant les backtests, afin de conserver leurs empreintes initiales.
Cette erreur de description ne change aucun cours, ordre ou calcul.

## Contrôles, disponibilité et trous

Le script utilise `MarketDataUpdater`, `YahooSource`, les normaliseurs,
validateurs, calendriers et corrections déjà examinées dans le projet.
Les métadonnées de `market_data/metadata/` ont été copiées dans le magasin isolé ;
le registre principal n'est pas modifié. `metadata_sha256.json` fige le snapshot.
Les modifications ultérieures de configuration sont refusées plutôt qu'appliquées
sans examen. Les cours ne sont jamais interpolés ou corrigés par ce script.

Les OHLC sont téléchargés avec `auto_adjust=False`. L'adaptateur vérifie
qu'aucun split n'est déclaré pour chaque instrument ETF du modèle, car Yahoo
restate même alors les cours précédant un split. Aucun split n'a été signalé.
Les nouvelles séries Xetra restent **SINGLE_SOURCE**, sans comparaison avec une
seconde source historique. ESE et CW8 reprennent les vérifications Euronext et
toutes les corrections déjà examinées dans le projet.

La validation de 4GLD sur 2014–2026 a refusé les barres du 26 et du 29 juin 2017,
dont le close dépasse le high. Le snapshot brut refusé est conservé. La recherche
utilise explicitement le segment du **2 janvier 2018** au 9 octobre 2026,
validé sans modification de prix. Cette restriction a été acceptée avant le
premier test de stratégie. Elle figure dans `ARCHIVE_START_OVERRIDES` du script,
pas dans la date de cotation de l'instrument.

IS3N et 4GLD n'ont aucune barre Yahoo sur **2025-10-24** et **2026-03-06**.
Ces dates sont de vraies séances Xetra : SXRV y possède notamment des volumes
respectifs de 8147 et 13887 ; les autres ETF possèdent également des barres.
De nouveaux appels à Yahoo sur les fenêtres du 23 au 27 octobre 2025 et du
5 au 9 mars 2026 ne servent toujours que les séances encadrant ces deux trous.
Le calendrier n'explique donc pas ces absences. Le diagnostic complet, réalisé
sans écrire dans le magasin pendant les backtests, se trouve dans
`runs/sa15_gpt61_data_probes/missing_20251024_20260306.json`.
Les fenêtres de signaux exigeant N séances consécutives doivent être déclarées
indisponibles lorsqu'elles traversent ces trous. Avec N=252, cela peut exclure
l'actif pendant environ un an ; aucune interpolation ne doit masquer cet effet.

Des barres plates de volume zéro subsistent telles que servies par Yahoo,
notamment le 24 octobre 2025 pour XEON, DBZB et XDBC. Les avertissements de
validation sont conservés dans les rapports JSON. La validité OHLC ne prouve
pas qu'un particulier aurait pu être exécuté au prix indiqué un jour sans
transactions ; le modèle de participation aux volumes doit le contrôler.
IS3N commence à sa première barre montrant une transaction, le 12 juin 2014 ;
sa ligne initiale plate de volume nul du 11 juin n'est pas déclarée négociable.

Les horodatages internes sont en UTC, avec ouvertures et clôtures déterminées
par les calendriers explicites Paris/Xetra. Le script ne décale pas les clôtures :
le moteur de backtest doit prendre les décisions après les closes et attendre
l'ouverture européenne suivante pour exécuter les ordres.

## Unités et séries de contrôle

Les OHLC des huit véhicules sont en **EUR par part** ; les volumes sont des
parts échangées, non des euros. Les valeurs n'ont pas été multipliées par des
taux de change externes. Les indices sous-jacents ou parts USD entraînent des
expositions économiques au change même avec une cotation EUR.

Trois séries de contrôle ont aussi été archivées, sans être nécessaires aux
signaux SA15 retenus : SP500 (`^GSPC`, points d'indice USD), VIX (`VIXCLS`,
points de volatilité : 20 signifie environ 20 % annualisés) et US10Y (`DGS10`,
pourcentage annuel : 4 signifie 4 %, non 0,04). VIX est un niveau FRED disponible
à 16h15 New York pour le jour considéré ; US10Y reprend la règle prudente du
projet, publication après une séance de décalage. US10Y est une série FRED
restatée, sans vintages point-in-time ; l'utiliser dans des signaux demanderait
de signaler cette limite. Une observation présente dans le stockage ne devient
lisible qu'à son instant de publication documenté.

XDBC a changé d'indice le **21 mai 2021**, depuis DBLCI-OY Balanced vers la
famille Bloomberg actuelle, ex-agriculture et élevage avec limites de poids et
contrats à terme décalés. Son historique inclut donc deux méthodologies et ne
représente pas rétrospectivement l'indice courant. La performance d'un ETF de
futures inclut renouvellement des contrats, collatéral et frais ; elle ne suit
pas simplement le prix spot des matières premières. DBZB comporte du risque
de duration et de taux ; sa couverture EUR ne couvre pas ce risque.

## Sources primaires des caractéristiques

- [iShares Nasdaq 100, IE00B53SZB19](https://www.blackrock.com/ch/professionals/en/products/253741/ishares-nasdaq-100-ucits-etf) : lancement de la part le 26/01/2010, ligne Xetra EUR le 10/03/2010.
- [iShares Core MSCI EM IMI, IE00BKM4GZ66](https://www.ishares.com/uk/individual/en/products/264659/ishares-msci-emerging-markets-imi-ucits-etf) : lancement de la part le 30/05/2014, ligne Xetra EUR le 04/06/2014. Yahoo commence plus tard.
- [Xetra-Gold, données contractuelles DE000A0S9GB0](https://www.xetra-gold.com/en/investing-in-gold/master-data/) et [structure du placement](https://www.xetra-gold.com/en/investing-in-gold/) : titre adossé à l'or physique, admission le 14/12/2007.
- [DWS, fiche Global Government Bond EUR hedged 1C, LU0378818131](https://etf.dws.com/en-no/AssetDownload/Index/6394b68b-946e-4575-9c43-9576d10b8506/Factsheet.pdf) : part capitalisante, réplication physique, lancement le 20/10/2008.
- [DWS, fiche Commodity ex-Agriculture & Livestock 1C, LU0292106167](https://etf.dws.com/download/asset/aa033f93-7450-44a5-8ffa-1dc6bba6e5d7) : part couverte en EUR, réplication swap, lancement le 29/06/2007, changement d'indice le 21/05/2021.

Ces fiches décrivent les caractéristiques présentes et les dates historiques
publiées aujourd'hui. Elles ne constituent pas une base de compositions
historiques point-in-time. Les cours proviennent de Yahoo, non de ces fiches.

## Reproduction et validation

Sous WSL, depuis la racine du dépôt et avec l'environnement déjà présent :

```sh
.venv/bin/python scripts/SA15_download_data.py
.venv/bin/python scripts/SA15_download_data.py --coverage-only
```

Le premier appel archive la fenêtre déclarée à partir de 2014, avec début en
2018 pour l'or et aux premières observations valides pour CW8/IS3N.
Un téléchargement ultérieur peut révéler des révisions Yahoo : les valeurs
archivées gagnent et les désaccords sont journalisés selon la politique du projet.
Pour retrouver exactement ce travail, conserver l'archive raw et les empreintes
de métadonnées ; retélécharger Yahoo plus tard ne promet pas les mêmes données.

Chaque invocation crée un rapport daté sous `runs/sa15_gpt61_store/reports/`
avec couverture, séances manquantes, conflits et détails des avertissements ou
erreurs. Le code retour indique une erreur de téléchargement/validation ; des
trous restent explicitement visibles même après une ingestion autorisée.

Contrôles réalisés : 213 tests existants du registre, de l'ingestion et de
l'adaptateur Yahoo réussis, 6 tests réseau exclus ; Ruff vérifie le script et
son format. Le mode `--coverage-only --start 2018-01-02` a aussi été exécuté
sans réseau. Aucun paquet installé, aucun fichier de dépendances modifié,
aucune stratégie testée par la tâche de préparation des données.