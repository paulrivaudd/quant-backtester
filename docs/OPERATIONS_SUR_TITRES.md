# Opérations sur titres

État au 2026-09-27. Ce document dit ce que le projet fait d'une opération sur
titres (OST, *corporate action*), à chaque couche, et surtout ce qu'il **ne
fait pas encore**. L'architecture est dans [ARCHITECTURE.md](ARCHITECTURE.md),
les formules dans [FORMULES.md](FORMULES.md).

## 1. Ce qu'est une OST, et pourquoi elle est dangereuse

Une OST change les titres, les droits ou les flux d'un détenteur. Le prix bouge
alors mécaniquement, sans que personne ait gagné ou perdu autant. Un split 2:1
divise le prix par deux, mais le détenteur a deux fois plus de titres. Un
dividende fait baisser le prix de son montant, mais le détenteur reçoit ce
montant en cash.

Lue sur une série brute, une OST ressemble à un mouvement de marché : un krach
de −50 % pour un split 2:1, une baisse de 2 % pour un dividende de 2 %. Un
momentum, un drawdown ou un rendement calculé à travers elle est faux.

Il y a quatre dates distinctes : l'**annonce** (l'événement devient public), la
**date ex** (le titre se négocie sans le droit), l'**enregistrement** (qui est
détenteur) et le **paiement** (le cash ou les titres arrivent). Le projet ne
connaît que la date ex : Yahoo ne fournit rien d'autre.

## 2. Les types stockés

`data/schemas.py`, `ActionType`. La colonne `value` a un sens différent selon le
type :

| Type | `value` | Ajustement des prix antérieurs à la date ex |
|---|---|---|
| `SPLIT` | ratio : 4.0 pour un 4:1, 0.125 pour un regroupement 1:8 | divisés par le ratio |
| `DIVIDEND` | montant brut par titre, en devise de l'instrument | multipliés par `1 − D / C_prev` |
| `SPIN_OFF` | facteur d'ajustement du prix | divisés par le facteur, comme un split, mais **aucun titre n'a été multiplié** |
| `SPECIAL_DIVIDEND` | montant brut d'une distribution exceptionnelle | comme un dividende |

`C_prev` est la clôture brute de la séance qui précède la date ex.

Yahoo ne distingue pas ces cas. Il code une scission comme un split fractionnaire
(GE 1.281 le 2023-01-04 pour GE HealthCare) et un dividende exceptionnel comme un
dividende ordinaire (COST 15.00 le 2023-12-27). Seule une **correction revue** et
commitée dans `market_data/metadata/corporate_actions.toml` requalifie un
événement (`data/corporate_actions.py`). Une correction ne peut que renommer
`SPLIT` en `SPIN_OFF` ou `DIVIDEND` en `SPECIAL_DIVIDEND`. Les deux types d'une
même paire ajustent le prix de la même façon, donc une correction ne déplace
jamais une série stockée. Elle change seulement ce que les couches au-dessus ont
le droit d'y lire.

Une correction n'est pas point-in-time : elle s'applique à tout l'historique à
partir du jour où elle est écrite. **Le type corrigé n'est donc pas utilisable
comme variable prédictive.** Le fichier est vide aujourd'hui : SP500 et VIX sont
des indices, les ETF sont capitalisants et les taux ne distribuent rien.

## 3. Ce que fait chaque couche

### `data` : ingestion et contrôle

- Yahoo : les splits et dividendes sont téléchargés à part et stockés dans leur
  propre table. `YahooSource.download` **refuse une action ou un ETF pour lequel
  Yahoo signale un split**, même hors de la période demandée. Avec
  `auto_adjust=False`, Yahoo ajuste quand même les prix antérieurs d'un split. Le
  brut n'est donc pas brut, et on ne peut pas s'en servir. Cette protection peut
  bloquer un actif pourtant présent chez le fournisseur.
- Le validateur refuse (`ERROR`) :
  - une action en double le même jour ;
  - **un split et une distribution à la même date ex** (`SPLIT_WITH_DISTRIBUTION`,
    décision D2) : on ne sait pas si le montant est par titre avant ou après le
    split ;
  - un ratio ≤ 0 ou égal à 1 ;
  - un dividende ≤ 0 ;
  - une distribution sur une part déclarée `ACCUMULATING` (`UNEXPECTED_DISTRIBUTION`).
- `distribution_policy` (`DISTRIBUTING` / `ACCUMULATING`) dit si un flux de
  dividendes vide est normal ou si c'est un trou.

### `data` : lecture

- Une action est **disponible à l'ouverture de sa date ex**, en même temps que le
  premier prix qu'elle affecte. Le lecteur d'exécution de la date ex voit l'ouverture
  déjà ajustée *et* l'action. Le lecteur de la veille au soir ne voit ni l'une ni
  l'autre. Aucun des deux ne montre de faux saut.
- `PointInTimeReader.adjusted_history` ajuste en remontant le temps, avec les seules
  actions connues à l'instant. Les facteurs se multiplient. Une action encore
  future ne modifie pas la fenêtre. Un facteur ≤ 0 lève une erreur.

### `signals`

`PriceBasis.ADJUSTED` lit `adjusted_history`. C'est un **prix ajusté**, pas une
richesse réinvestie : le jour ex, le rendement lu vaut `C_ex / (C_prev − D) − 1`,
et non `(C_ex + D) / C_prev − 1`. Avec `C_prev = 100`, `D = 2` et `C_ex = 101`, le
signal lit 101/98 − 1 = 3,06 %, alors que le détenteur a gagné 103/100 − 1 = 3 %.
Un signal a besoin du premier nombre : le second attend une clôture qu'il n'a
pas encore vue. `PriceBasis.RAW` lit la cotation telle quelle. Un signal sur `RAW`
dont la fenêtre traverse une OST mesure l'OST.

### `backtest` : le livre

**Le moteur ne comptabilise aucune OST sur une position détenue.** Avant chaque
ouverture, `BacktestEngine._require_no_corporate_action` vérifie si une position
détenue passe une date ex depuis la séance précédente. Si c'est le cas, le run
s'arrête avec `UnsupportedCorporateAction`, **même si la stratégie allait vendre à
cette ouverture**, car la vente aurait lieu après l'événement. Sans cet arrêt, un
split se lirait comme un effondrement du prix, et un dividende n'arriverait
jamais dans le cash.

C'est un arrêt explicite, pas une gestion de l'événement. Aujourd'hui aucun
instrument négociable ne distribue : les deux ETF sont capitalisants, et aucun n'a
de split. L'arrêt ne s'est donc jamais produit sur les runs du README.

### `backtest` et `analytics` : le benchmark

`value_benchmark` et `session_growth` valorisent une part détenue sans coûts, en
fractions de titres :

- **split** : le nombre de titres est multiplié par le ratio ;
- **dividende**, ordinaire ou spécial, sous `BenchmarkBasis.TOTAL_RETURN` : le
  montant est versé sur chaque titre détenu à la date ex, puis réinvesti à la
  clôture de cette séance. Sous `PRICE_RETURN`, il est ignoré ;
- une action connue en retard est comptée au premier pas où elle est connue ;
- **scission : refusée**. Le benchmark ne peut pas valoriser ce qui a été
  distribué, et ne traite pas une scission comme un split (décision D3) ;
- **split et distribution le même jour : refusés** (décision D2).

## 4. Ce qui n'est pas géré

- La comptabilité d'une OST sur une position détenue : le run s'arrête (voir §3).
- La créance entre la date ex et le paiement, et le délai de paiement.
- La fiscalité : retenue à la source, régime PEA.
- La livraison des titres d'une scission, l'échange d'une fusion, l'exercice ou la
  vente d'un droit préférentiel de souscription.
- Les rompus de split : fractions de titre à régler en cash.
- Le remboursement à la radiation. Un titre radié arrête le run
  (`UnvaluablePosition`) et le benchmark, sans prix de liquidation inventé.
- Un historique des annonces : le catalogue ne connaît pas la date d'annonce, et ce
  n'est pas un flux négociable avant la date ex.
- Le biais de survivance au niveau des données : Yahoo ne sert rien pour un titre
  radié (TWTR, SIVB, CELG). Un univers doit être déclaré date par date, et le brut
  archivé avant la radiation.

## 5. Pour l'étendre (lot G, C05 de l'audit de l'archive 9)

L'extension attend trois **décisions de l'utilisateur** : le délai de paiement
d'un dividende, le traitement de la retenue à la source en PEA et le règlement
des rompus. Une fois ces décisions prises, la méthode est la suivante :

1. un événement typé et daté par OST, avec ses unités avant et après ;
2. le livre met à jour les quantités et le coût moyen à l'ouverture de la date
   ex ;
3. un dividende devient une **créance** à la date ex, puis du cash au paiement.
   Les deux mouvements sont enregistrés dans le `BacktestRecord` ;
4. un test de **conservation de richesse** sans mouvement de marché : 10 titres à
   100 avant un split 2:1 deviennent 20 titres à 50, soit 1 000 dans les deux cas ;
5. le même test pour un dividende : la richesse du livre à la date ex, créance
   comprise, ne change pas quand le prix baisse du montant.

## 6. Les OST comme source de signal

Hors périmètre aujourd'hui. Pour mémoire :

- **nettoyer un signal** : c'est le rôle de `ADJUSTED`. Une base ajustée
  aujourd'hui peut quand même contenir des corrections inconnues à la date de
  décision ;
- **signal d'événement** : il faut un horodatage d'**annonce**, qu'on n'a pas.
  Une date ex connue après coup n'en est pas un ;
- **arbitrage de fusion** : une cible à 48, une offre à 50, un retour à 35 en cas
  d'échec. Le gain espéré vaut `15p − 13`, donc il faut `p > 13/15` avant frais
  et portage. Ce n'est pas de l'argent gratuit, et le projet n'a ni ces
  probabilités ni la mécanique d'échange.
