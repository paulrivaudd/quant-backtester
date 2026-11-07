# SA17 — proposition de momentum sectoriel corrigé du marché

Date : 2026-11-01. Statut : **PROPOSED / NOT_TESTED**.

**Mise à jour du 2026-11-07 :** cette proposition historique est conservée.
Le [protocole corrigé](protocol.md) prévaut pour les données et la chronologie :
VL officielles USD, dates américaines communes, disponibilité après publication,
risque EUR séparé, coûts par fonds et étude longue Ken French. Aucune performance
SA17 n'a été calculée. Une VL datée du jour n'est pas disponible à sa clôture.

Cette note propose une seule candidate. Aucun résultat SA17 n'a été calculé.
Ce n'est pas encore un protocole exécutable préenregistré : le registre des
instruments, les sources et les fenêtres réellement couvertes restent à auditer.
Leur gel doit précéder toute lecture des performances de la candidate.

## Décision et objectif

Changer de mécanisme plutôt que retoucher SA16. Conserver le cadre du moteur :
100 000 EUR, positions longues, sans levier, parts entières, décisions après
clôture et exécution à une ouverture ultérieure.

L'objectif reste exigeant : CAGR et Sharpe nets supérieurs à SA16_it2 sur les
mêmes dates, avec une perte maximale comparable. Aucune performance future,
ni supériorité historique, n'est annoncée. Un résultat négatif doit pouvoir
terminer l'expérience sans déclencher une recherche de paramètres gagnants.

## Ce que les travaux existants permettent de dire

- Le rapport SA16 archive 22,40 % de CAGR, un Sharpe à taux nul de 1,321 et
  −22,3 % de drawdown sur 2018-08-01–2026-10-30. Son témoin fixe technologie/or
  obtient presque le même résultat. La supériorité en rendement reste incertaine.
- Les fichiers JSON de l'audit externe ont été consultés, sans réexécuter les
  scripts : la régression sur technologie et or donne R² = 0,9877 et un alpha
  annualisé de 0,54 %, t = 0,87. Cela ne démontre pas un alpha nul ; cela
  n'établit pas un avantage propre à la règle.
- Le test externe 2014–2018 emploie Nasdaq/or. Il affaiblit la généralité du
  mécanisme mais n'est pas un backtest exact du portefeuille technologie/or.
  Cette période est désormais consultée, donc indisponible comme validation
  vierge d'une nouvelle conception.
- SA15 a déjà exploré rotations entre actifs, tendances, plafonds de volatilité
  et reprises. SA16_it3 a déjà essayé une inclinaison de momentum technologie/or.
  Réutiliser ces mécanismes ne constituerait pas, à lui seul, une nouvelle source
  de rendement. Le mécanisme proposé ici est le **classement sectoriel corrigé
  du marché** ; le contrôle de volatilité est un outil de dimensionnement.

## Hypothèse économique

La force relative propre à un secteur pourrait persister après prise en compte
de sa sensibilité habituelle au marché. Classer cette composante pourrait mieux
sélectionner les secteurs que classer leurs seuls rendements passés.

Deux travaux motivent cette recherche :

- Moskowitz et Grinblatt (1999), [Do Industries Explain Momentum?](https://www.aqr.com/insights/research/journal-article/do-industries-explain-momentum),
  étudient la persistance des rendements sectoriels.
- Blitz, Huij et Martens (2011), [Residual Momentum](https://repub.eur.nl/pub/22252/ResidualMomentum-2011.pdf),
  classent des actions sur leurs rendements résiduels après régression
  multifactorielle, avec une estimation sur 36 mois et un signal sur 12 mois
  excluant le dernier mois.

La candidate combine des idées de ces travaux, mais **ne les réplique pas** :
ETF sectoriels, modèle à un seul facteur et portefeuille long-only. Les résultats
des articles ne prouvent ni l'efficacité de cette adaptation ni sa supériorité
sur SA16. Corriger un signal du bêta ne neutralise pas le bêta du portefeuille.

## Règle proposée avant calcul

| Élément | Choix proposé |
| --- | --- |
| Univers économique | Ensemble des secteurs du S&P 500 selon la classification effectivement en vigueur à chaque date ; aucun secteur choisi pour son rendement historique. |
| Instruments | Un ETF UCITS capitalisant coté en EUR par secteur, avec correspondance exacte documentée ; monétaire EUR pour le reliquat. Les secteurs mondiaux santé/utilities du magasin ne remplacent pas leurs homologues américains. |
| Cadence | Dernière séance XPAR du mois, décision à 23:00 Paris, après vérification de la disponibilité des données ; première ouverture ultérieure de chaque véhicule. |
| Estimation | Pour chaque secteur, régression OLS avec constante de ses 36 derniers rendements mensuels totaux en USD sur ceux du S&P 500, arrêtés au mois de décision. |
| Score | Moyenne des 11 résidus correspondant aux 12 derniers mois moins le mois le plus récent, divisée par leur écart-type d'échantillon. La fenêtre du score est plus courte que celle de la régression. |
| Sélection | Trois secteurs au score le plus élevé ; égalité départagée par identifiant stable. La sélection porte sur la force relative, même si tous les scores sont négatifs. |
| Pondération | Un tiers de la poche actions par secteur retenu ; aucune préférence structurelle pour la technologie. |
| Risque | Covariance d'échantillon sur les 63 derniers rendements quotidiens totaux synchronisés en EUR des trois secteurs. Volatilité annualisée du panier équipondéré : sigma = sqrt(252 × w'Cov w). |
| Exposition | g = min(1, 0,15 / sigma). Chaque secteur reçoit g/3, le reste va au monétaire EUR. Si sigma vaut zéro, g = 1. Aucun levier. |
| Rééquilibrage | Mensuel vers les cibles, sans bande supplémentaire à optimiser ; arrondis, frais et disponibilités de cash traités par le moteur. |

Les trois secteurs, les 63 séances et les 15 % sont des choix de conception,
pas des paramètres réputés optimaux. La volatilité réalisée peut dépasser 15 %
et cette règle ne borne pas le drawdown. Le contrôle mensuel peut intervenir
après une chute et réduire la participation à un rebond.

Les entrées doivent couvrir des fenêtres calendaires explicites. Aucun forward
fill de rendement, aucune régression sur l'historique complet. Les secteurs
n'ayant pas encore 36 mois de données admissibles ne sont pas éligibles ; leurs
dates d'entrée sont enregistrées. Une panne sur un secteur déjà éligible annule
la décision complète, conserve les positions et déclenche un diagnostic : elle
ne permet pas de classer silencieusement un univers réduit. Moins de trois
secteurs historiquement éligibles laisse le portefeuille au monétaire. Un
écart-type résiduel nul ou une covariance illisible annule aussi la décision.
L'absence de prix nécessaire à la valorisation suit les refus du moteur.

Le signal en USD vise à séparer la sélection sectorielle du mouvement EUR/USD.
Les positions restent exposées au dollar : une cotation en EUR ne couvre pas le
change. Le risque et les performances sont mesurés en EUR.

## Données : condition préalable

Il faut auditer les historiques sectoriels, les classifications et changements
d'indices, les fonds disparus, les dates de cotation et les opérations sur
titres. Une liste des ETF survivants choisis aujourd'hui ne suffit pas.
Les critères de correspondance et de choix du véhicule doivent être fixés sans
lecture de la performance SA17. Le registre manque actuellement pour cet univers.

Pour étudier 1999–2018 avec 36 mois d'amorçage, il faut des données remontant au
moins à 1996. Les séries rétropolées ou restatées sont identifiées comme telles.
Un indice total return peut servir à une étude économique sur proxys ; il ne
devient pas un ETF négociable avant sa création. Les deux études sont séparées :

1. mécanisme sur historiques sectoriels longs, avec coûts hypothétiques explicites ;
2. portefeuille exécutable sur les vrais véhicules, dès leurs dates admissibles.

La comparaison ancienne avec SA16 doit elle aussi employer un proxy sectoriel
technologie clairement identifié. Ni Nasdaq ni un historique d'indice ne seront
présentés comme une exécution historique de QDVE.

Les données ne sont pas réputées disponibles tant que cet audit n'est pas fait.
Une couverture insuffisante conduit à `INSUFFICIENT_EVIDENCE`, sans raccourcir
discrètement la fenêtre pour obtenir un résultat favorable.

## Témoins fixés avec la candidate

| Témoin | Question |
| --- | --- |
| SA16_it2 archivé | La nouvelle allocation améliore-t-elle effectivement la stratégie précédente ? |
| C1 fixe 2/3 technologie, 1/3 or | Dépasse-t-elle aussi l'explication simple de SA16 ? |
| Nasdaq acheté-conservé | Satisfait-elle encore la référence historique du projet ? |
| Tous les secteurs équipondérés, rééquilibrés mensuellement | Le choix d'univers suffit-il à expliquer le résultat ? |
| Même panier de tous les secteurs avec le contrôle de volatilité de la candidate | La sélection apporte-t-elle davantage qu'une allocation sectorielle avec risque réduit ? |
| Trois secteurs classés par rendement total 12–1, même dimensionnement | La correction du marché apporte-t-elle quelque chose au momentum ordinaire ? |
| Candidate sans contrôle de volatilité | Quelle part du résultat vient du dimensionnement ? |

Chaque témoin est un vrai run, jamais un remplaçant sélectionnable après lecture.
Les risques réalisés, bêta, cash, expositions sectorielles, rotation et coûts
sont publiés. Un même objectif de volatilité ne garantit pas un même risque
réalisé. Une régression d'attribution ex post reste descriptive.

## Critères à inscrire dans le protocole final

- Sur une fenêtre commune fixée par la couverture avant calcul, CAGR et Sharpe
  nets strictement supérieurs à SA16_it2, C1 et Nasdaq. Drawdown de la candidate
  au plus 2 points plus profond que celui de SA16. Maintien des comparaisons de
  CAGR et Sharpe dans de vrais runs à coûts doublés pour tous les portefeuilles.
- Pour revendiquer une valeur propre à la sélection, avantage net contre le
  panier sectoriel avec le même contrôle de risque. Pour revendiquer une valeur
  propre à la correction du marché, avantage contre le classement en rendement
  total. Un succès contre SA16 seul ne suffit pas à établir ces mécanismes.
- Sharpe principal calculé au-dessus d'une même référence monétaire EUR ; Sharpe
  à taux nul secondaire pour raccorder les anciens rapports. Recalculer les
  références : ne pas comparer un nouveau Sharpe excédentaire au 1,321 ancien.
- Coûts de commission, spread et glissement documentés par véhicule ; frais de
  gestion déjà présents dans les prix des ETF non déduits une seconde fois.
  Publier sensibilité à un délai supplémentaire d'exécution. Le résultat est
  avant fiscalité ; une supériorité après impôts nécessite un scénario d'enveloppe
  défini et les mêmes conventions de liquidation finale pour tous les livres.
- Bootstrap stationnaire apparié des rendements quotidiens de tous les livres,
  10 000 tirages, longueur moyenne de bloc 20 séances, graine 20261101. Intervalles
  à 95 % pour les écarts de CAGR et Sharpe ; sensibilités de blocs 5 et 60 publiées,
  jamais sélectionnées. Les comparaisons multiples exigent un ajustement commun
  défini dans le protocole ; les intervalles ordinaires sont descriptifs.
- Publier aussi rendement actif, tracking error et ratio d'information. Un DSR
  éventuel porte sur la série active et explicite ses hypothèses. Il ne remplace
  ni la comparaison de CAGR/Sharpe ni une validation indépendante.
- Une seule candidate de départ. Tous les runs, témoins, diagnostics consultés,
  changements d'univers et essais antérieurs pertinents restent traçables. Un
  nouveau numéro SA ne remet pas à zéro la sélection déjà effectuée. Toute
  modification après lecture est une nouvelle hypothèse et un nouvel essai.

Les périodes déjà examinées ne redeviennent pas hors échantillon. Un test long
1999–2018 sert à éprouver d'autres régimes, notamment 2000–2002 et 2008 ; ce n'est
pas une preuve prospective par son seul changement de dates. La connaissance
publique de ces crises a elle-même influencé la conception.

Le suivi futur commence après le gel effectif du code et du protocole, jamais
rétroactivement. Première lecture comparative après 252 séances, conformément
au protocole du projet ; cette durée n'assure pas une puissance statistique
suffisante. Une incertitude persistante reste publiée comme telle.

## Risques spécifiques et règle d'arrêt

Le classement peut manquer de stabilité sur un petit nombre de secteurs. Trois
secteurs peuvent être fortement corrélés et les portefeuilles restent des
portefeuilles actions. Le modèle à un facteur laisse subsister d'autres
expositions. Une hausse durable technologie/or peut laisser SA16 largement
devant. Frais, fiscalité, estimation du bêta et retournements peuvent absorber
l'avantage du signal. Rien ne garantit l'absence d'erreurs : des contrôles
indépendants de disponibilité des données, calendriers, calculs, opérations sur
titres et exécutions restent nécessaires avant d'interpréter un résultat.

Si la candidate ne bat pas SA16, l'objectif de remplacement est
`NOT_SUPPORTED`. Si elle le bat sans dépasser ses témoins sectoriels, l'avantage
propre du mécanisme n'est pas établi. Si les écarts restent compatibles avec
zéro, le verdict reste `UNCERTAIN`. Aucun de ces cas ne justifie automatiquement
une nouvelle série de réglages.
