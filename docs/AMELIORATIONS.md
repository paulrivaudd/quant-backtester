# Améliorations nécessaires

État au 2026-09-26, version 0.2.0 (`69d1219`). Cette liste recense ce qui me
semble devoir être amélioré, classé par effet sur la confiance qu'on peut
accorder à un résultat. Un point n'y figure que s'il limite ce qu'on peut
affirmer, ou s'il coûte du temps à chaque usage.

Légende : **P1** limite la validité d'un résultat, **P2** limite sa portée ou
sa reproductibilité, **P3** relève du confort ou de l'outillage.

## 1. Justesse économique du simulateur

| # | Prio | Problème | Ce qu'il faudrait |
|---|---|---|---|
| 1.1 | P1 | Une corporate action (split, dividende) sur une ligne détenue **arrête le run**. Aucun ETF distribuant ni aucune action n'est donc testable. | Un registre comptable des titres et du cash : split = quantité × ratio, dividende = cash crédité à la date de paiement, retenue à la source déclarée. Tests contre des calculs de richesse faits à la main. |
| 1.2 | P1 | Une radiation d'une ligne détenue arrête aussi le run. Il n'existe pas de modèle de liquidation. | Une politique déclarée : dernier cours, prix de retrait ou perte totale. Elle est indispensable dès que l'univers contient des titres morts. |
| 1.3 | P1 | Un seul modèle d'exécution, `OPEN_AUCTION_NOTIONAL` : taille calculée et exécution au prix d'ouverture qu'on vient d'observer. Sa sensibilité n'a jamais été mesurée. | Une variante où les quantités sont fixées à la clôture de décision, avec une réserve de cash, puis exécutées à l'ouverture. Mesurer l'écart sur les suites. |
| 1.4 | P1 | Ni plafond de participation au volume ni spread par instrument. ESE échangeait environ 25 k€ par jour avant 2016, alors que le simulateur y achète 100 k€ au prix d'ouverture. | Un plafond de participation (par exemple 10 % du volume) et un demi-spread par instrument ou par tranche de liquidité, déclarés dans la configuration. |
| 1.5 | P2 | Le cash ne rapporte rien, alors que le Sharpe retranche un taux sans risque. Une stratégie souvent en cash, comme la jauge VIX, est pénalisée deux fois. | Une rémunération du cash déclarée, sur une série de taux point-in-time (€STR). |
| 1.6 | P2 | Le « brut » est une attribution des coûts sur les mêmes fills, pas un run indépendant sans frais. | Un run sans frais optionnel, en contrefactuel, pour mesurer l'effet causal d'une grille de coûts. |
| 1.7 | P2 | Une devise de compte unique : un instrument en USD est refusé. | Une conversion de change au prix disponible à l'exécution, avec des coûts de change nommés. |
| 1.8 | P3 | Les plafonds portent sur les cibles avant coûts. | Un contrôle optionnel après coûts, avec une politique de correction, si un plafond devient une règle de risque dure. |

## 2. Données

| # | Prio | Problème | Ce qu'il faudrait |
|---|---|---|---|
| 2.1 | P1 | **Une seule barre contestée coûte 61 séances** : celle d'ETF_WORLD le 2025-10-24 bloque une fenêtre de 60 séances consécutives et retire environ 4 points à la rotation du README. ETF_WORLD a 8 séances contestées, ETF_SP500_PEA 5. | Un circuit de revue des `CONFLICT`, comparable à `accepted_revisions` : on tranche une contestation une fois revue, sans jamais inventer de prix. Il faut aussi décider, par signal, si une fenêtre en `AVAILABLE_OBSERVATIONS` est acceptable. |
| 2.2 | P1 | US10Y est déclaré `RESTATED` : la série FRED est lue dans son dernier millésime, donc avec du look-ahead. | Passer US10Y sur ALFRED en `AS_OF_DECISION`, puisque le code est prêt : décider de ce que le store ira chercher, puis rejouer. |
| 2.3 | P2 | Les historiques Yahoo sont déclarés `ASSUMED_UNREVISED` sans preuve : les données ont été téléchargées en septembre 2026 et rien n'a été comparé. | Refetcher périodiquement et comparer aux archives brutes pour mesurer les révisions réelles de Yahoo. Le journal `revisions.parquet` existe déjà, il faudrait un rapport. |
| 2.4 | P2 | Euronext, la seconde source, ne remonte que deux ans. Les 4 trous d'ESE de 2014-2015 restent des hypothèses. | Une seconde source historique, payante ou issue d'archives d'émetteur, au moins pour valider la période avant 2018. |
| 2.5 | P2 | Aucun univers historisé avec titres morts : ROTATION_2 compte deux fonds vivants. | Des univers point-in-time avec les radiés, prérequis à tout élargissement (biais du survivant). |
| 2.6 | P3 | Les ingestions dépendent de `yfinance`, qui est fragile et sans contrat. | Un adaptateur de secours et une alerte quand le schéma servi change. |

## 3. Reproductibilité et conservation

| # | Prio | Problème | Ce qu'il faudrait |
|---|---|---|---|
| 3.1 | P1 | **Un résultat n'est pas persisté.** `StrategyResult` vit en mémoire : le `run_id` identifie une expérience, mais ne la conserve pas. Relancer des mois plus tard exige le même store, que le digest sait seulement détecter. | Un « dossier de run » écrit sur disque : records, benchmark, configuration, manifeste du store, `run_id`, dans un format relu et vérifié par empreinte. |
| 3.2 | P2 | Le `run_id` n'inclut ni `uv.lock` ni la version de Python : deux environnements différents peuvent partager un identifiant. | Ajouter l'empreinte du lockfile et la version de l'interpréteur aux entrées hachées. |
| 3.3 | P2 | Le store n'est pas versionné : une révision remplace le fichier et l'ancienne génération disparaît. Seuls les snapshots manuels de `~/quant-snapshots/` la conservent. | Des générations immuables (répertoire par génération plus un pointeur atomique). Elles fermeraient aussi la fenêtre de lecture hors run entre deux renommages. |
| 3.4 | P3 | Le verrou est coopératif et ne vaut que sous POSIX. | Rien à faire tant que le projet reste mono-utilisateur sous WSL. À revoir si le store devient partagé. |

## 4. Recherche et statistique

| # | Prio | Problème | Ce qu'il faudrait |
|---|---|---|---|
| 4.1 | P1 | **Aucune mesure d'incertitude** : un Sharpe de 0,54 est affiché sans intervalle. Sur 437 séances, il n'est pas distinguable de 0,67. | Intervalles de confiance par bootstrap par blocs, et un Sharpe déflaté (Bailey et López de Prado) qui utilise le nombre de variantes du registre. |
| 4.2 | P1 | Les 19 runs du registre attendent leur verdict, et aucune hypothèse n'est écrite avant ses variantes. | Un fichier `research/hypotheses.toml` (prédiction, univers, critère de réfutation) validé avant tout run, et un verdict motivé pour chaque ligne du registre. |
| 4.3 | P2 | Pas de moteur walk-forward ni de voisinages de paramètres automatisés. Le protocole les exige, mais on les fait à la main. | Un balayage déclaré (grille, dates de départ glissantes, coûts ×1 et ×2) qui inscrit chaque point au registre. |
| 4.4 | P2 | La comparaison se fait contre un indice théorique (une part détenue, sans frais). | Un comparateur exécutable par défaut : buy & hold avec les mêmes coûts, lots, calendrier et cash de départ. |
| 4.5 | P2 | Il manque des métriques : exposition moyenne, temps investi, turnover par an dans le tableau, statistiques glissantes, contribution par régime. | Les ajouter au rapport, puisque le protocole demande de comparer exposition et turnover. |
| 4.6 | P3 | Signaux S4/S5 (OLS/Ridge/Lasso/PCA, HMM) et `StrategyState` (durée de détention, cooldown, trailing stop) absents. | À ouvrir seulement une fois 4.1 à 4.3 en place, sinon on multiplie les variantes sans pouvoir les juger. |

## 5. Outillage et code

| # | Prio | Problème | Ce qu'il faudrait |
|---|---|---|---|
| 5.1 | P2 | **Pas d'intégration continue** : ruff, pyright et pytest ne tournent que si on y pense. Un commit est déjà parti avec des erreurs pyright. | Un workflow GitHub Actions (ruff, format, pyright, pytest hors ligne à chaque push, tests réseau chaque nuit). |
| 5.2 | P2 | Le paper trading n'est pas automatisé : il faut penser à lancer `update_market_data.py` puis `paper_trade.py` chaque jour, puis commiter le journal. | Une tâche planifiée après la clôture européenne, plus une alerte si le journal n'a pas avancé. |
| 5.3 | P2 | Les scripts (`run_baselines.py`, `update_market_data.py`, `paper_trade.py`) n'ont pas de tests. | Des tests de fumée sur un store synthétique. |
| 5.4 | P3 | 13 modules gardent des notes d'exercice en français (« Exercice 8.5 ») dans des docstrings en anglais. | Les réécrire en documentation, dans une seule langue. |
| 5.5 | P3 | Les 19 runs des suites prennent 135 s, soit environ 7 s par run. Le reste du coût est dispersé dans la surcharge de pandas (`values()`, construction de frames de résultats). | Ne pas optimiser avant un besoin réel (balayage 4.3) ; mesurer alors et mettre en cache les signaux par séance. |

## Ordre que je recommande

1. **5.1** (intégration continue) et **3.1** (dossier de run persisté) : ils conditionnent la confiance dans tout le reste et coûtent peu.
2. **4.1** et **4.2** : incertitude et hypothèses écrites avant les runs, sans quoi aucun résultat n'est jugeable.
3. **2.1** et **2.2** : les deux défauts de données qui déplacent des chiffres publiés aujourd'hui.
4. **1.3** et **1.4** : sensibilité au modèle d'exécution et liquidité, avant toute conclusion sur les stratégies actives.
5. **1.1**, **1.2** et **2.5** : ce qu'il faut pour élargir l'univers.
6. Le reste, au besoin.
