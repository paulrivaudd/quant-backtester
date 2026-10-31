# SA16 — protocole fixé avant le premier candidat

Écrit le 31 octobre 2026, après la reproduction des deux références et avant
tout run de candidat SA16. Cahier des charges :
`Prompt_backtester_v2.md` fourni par le propriétaire (N = 16). Changer ce
protocole est un commit revu ; un changement ne s'applique jamais à un essai
déjà lancé.

## 1. La stratégie précédente à battre : SA15, essai 71 de R4

SA15 (GPT-6.1) a cinq séries. La dernière, R5 (mécanismes M01–M50), s'est
arrêtée à M34 : `results/SA15_GPT-6.1_R5/` n'a ni `selected.json`, ni
`study.md`, ni verdict, alors que le README renvoie à ces deux fichiers. Aucune
configuration R5 n'a donc été « explicitement retenue et archivée ».

La dernière sélection complète et archivée est celle de R4 :
`results/SA15_GPT-6.1_R4/selected.json`, essai 71, classe
`SA15RiskAwareRotation`, empreinte `ef95006960c2…`, cadence mensuelle avec
décision initiale (`MonthlyFromStart`) : technologie américaine (QDVE.DE)
plafonnée à 20 % de volatilité estimée (max des volatilités 20 et 60 séances),
reliquat vers l'or ou les matières premières de momentum 21/63/126 positif,
sinon monétaire, bande de 20 points. Son verdict R4 est `NOT_SUPPORTED`
contre le Nasdaq sur 2025–2026. C'est la référence SA(N−1), et elle est figée.

**Reproduction.** Sur le magasin SA16 reconstruit le 2026-10-31, l'essai 71 et
le Nasdaq conservé, relancés sur la fenêtre de SA15 (2019-06-03 →
2026-10-09), retombent au centime sur l'archive : 499 693,44 EUR et
448 002,97 EUR, écart relatif maximal nul sur 1 886 séances
(`results/SA16/reproduction/reproduction.json`).

## 2. Données, conventions et fenêtres

- Magasin isolé `runs/sa16_store` (`scripts/SA16_download_data.py`) : registre
  du projet + ajouts SA15 + séries de signal SA16
  (`research/SA16/instruments.toml` : `^NDX`, `GLD`, `HYG`, `IEF`, VIX3M FRED),
  toutes non négociables. Historiques Yahoo/FRED restatés, pas des millésimes.
  Les fonds Xetra QDVE, 4GLD, IS3N, XDWH, XDWU n'ont pas de barre le
  2025-10-24 ni le 2026-03-06 (panne fournisseur, cf. `known_gaps.toml`) ;
  SXRV (Nasdaq) est complet. Aucun prix n'est reconstitué.
- Conventions de SA15, pour comparer à l'identique : calendrier XPAR,
  100 000 EUR, parts entières, commission 5 pb (min. 1 EUR), demi-spread
  3 pb, glissement 2 pb, quantités fixées à la décision de 23:00 Paris,
  exécution à l'ouverture suivante du fonds, Sharpe sur 252 séances et taux
  sans risque nul. Coûts doublés = second vrai run.
- **Fenêtre d'étude : 2018-08-01 → 2026-10-30**, premier mois où toutes les
  entrées des deux références sont lisibles (archive or depuis 2018-01-02,
  momentum 126 séances) jusqu'à la dernière séance complète avant l'étude.
  Elle ajoute à la fenêtre de SA15 la baisse du quatrième trimestre 2018 et
  octobre 2026.
- Sous-périodes lues (grille fixée ici) : années civiles 2018 (partielle) à
  2026 (partielle) ; épisodes 2018T4, krach et rebond 2020, 2022, krach et
  rebond 2025 (`EPISODES` du script) ; sept redémarrages depuis le cash
  (2019-01-02 … 2025-01-02), chacun jusqu'au 2026-10-30.

Toute cette histoire a déjà été examinée par SA1–SA15 : l'étude est
rétrospective. Aucun échantillon n'en est vierge.

## 3. Ce que « battre » veut dire, fixé avant les essais

Sur la fenêtre d'étude, aux coûts déclarés, contre chacune des deux
références :

1. **CAGR net et Sharpe net strictement supérieurs** (obligatoire).
2. **Drawdown maximal comparable** : au plus 2 points plus profond que le
   moins profond des deux références (tolérance « comparable » = 2 pp).
3. **Coûts doublés** (vrai run) : les deux critères 1 tiennent encore contre
   les références rejouées à coûts doublés.
4. **Redémarrages** : CAGR net et Sharpe net supérieurs aux deux références
   dans au moins 5 des 7 redémarrages depuis le cash.
5. **Voisinage** : le critère 1 contre le Nasdaq tient pour au moins les deux
   tiers des voisins déclarés (paramètres principaux décalés d'un cran).
6. **Incertitude** : bootstrap apparié par blocs (`paired_block_bootstrap`,
   blocs de 20 séances, 2 000 tirages, graine 1616, niveau 90 %) des
   différences de Sharpe et de rendement moyen. Un intervalle qui contient
   zéro ne permet pas de conclure à une supériorité établie ; il est publié.

Les années civiles et les épisodes sont publiés sans exigence d'en gagner
chacun : une règle qui réduit le risque perd normalement certaines années
de forte hausse. Les périodes défavorables sont publiées.

Statuts : `NOT_SUPPORTED` si 1 échoue ; `UNCERTAIN` si 1 tient mais 2, 3, 4
ou 5 échouent, ou si les intervalles contiennent zéro ;
`SUPPORTED_RETROSPECTIVE` si tout tient et que les intervalles excluent zéro.

## 4. Budget, décompte et contrôles

- **Dix candidats au plus**, SA16_it1 à SA16_it10, échecs compris, numérotés
  dans l'ordre de leur premier run. Aucun balayage caché sous un numéro.
- Chaque candidat déclare avant son premier run, dans
  `research/hypotheses.toml` et `research/SA16/itNN.md` : lacune → mécanisme
  → gain attendu → risque introduit → résultat qui le réfuterait, sources,
  parent.
- **Contrôles d'ablation** : un vrai backtest qui retire un mécanisme. Ils ne
  sont jamais candidats (en adopter un serait un nouveau candidat), mais ils
  comptent comme essais dans le registre `results/SA16/register.csv` qui
  déflate le Sharpe.
- Sensibilités finales (voisins, redémarrages, coûts doublés) : comptées et
  publiées, jamais sélectionnables. Si leur lecture conduit à une
  modification, celle-ci est un nouveau candidat dans le budget.

## 5. Exécution manuelle

20 ordres au plus par séance, 1 à 10 visés lorsqu'il faut intervenir ;
mesurés par `result.orders()` (moyenne et maximum par jour d'intervention,
jours d'intervention par an). Aucune limite sur le nombre de jours
d'intervention n'est imposée par le cahier des charges ; il est publié et
pèse dans la lecture.

## 6. Choix du candidat retenu (ajouté le 2026-10-31, après it3, avant toute sensibilité)

Cette règle manquait ; elle est écrite après la lecture d'it1 à it3 et avant
tout run de voisinage ou de redémarrage. Parmi les candidats qui tiennent les
critères 1 à 3 (calculés pour chacun), est retenu celui dont le Sharpe net à
coûts ×1 est le plus élevé ; les critères 4 à 6 (redémarrages, voisins,
bootstrap) sont ensuite calculés pour lui. Si leur lecture conduit à une
modification, elle est un nouveau candidat, compté, et le choix est refait
avec la même règle. Les voisins et redémarrages ne sont jamais candidats.

Voisins déclarés pour un candidat de la famille `SA16RiskBudget`, un
paramètre à la fois : budget de la croissance ±0,05 ; fenêtre de volatilité
63 et 189 rendements (126 ± 50 %) ; bande 0,03 et 0,08 ; cadence mensuelle au
lieu d'hebdomadaire. Sept voisins, chacun à coûts ×1.
