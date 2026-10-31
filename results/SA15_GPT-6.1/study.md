# SA15_GPT-6.1 — etude retrospective du 15 octobre 2026

## Erratum, 2026-10-31: decision-time sizing valued a held line without a close at zero

With `Sizing.AT_DECISION`, which this study uses, a line held at the decision
whose close was missing was valued at zero when the book was sized, so every
other line was sized on an equity short of that line's weight. The fix (pull
request #2) values it at its last known price. In this study one decision is
exposed: the evening of 2025-10-24, when ETF_EMERGING and ETF_GOLD had no
close, executed at the open of 2025-10-27. The `equal_weight` control has a
second one, executed on 2026-03-09. Development and validation contain none:
the ten selection scores and the frozen choice of trial 8 are unchanged.

The rerun is a new trial in the sense of `research/PROTOCOL.md`: it replaces
neither the frozen selection nor the figures below this erratum, which are
those of the original run and are left as they were. It was made on
2026-10-31 on a store downloaded again with the same frozen end (2026-10-09),
whose fingerprint differs (`cdb10486…` against `316789fb…`) but on which the
code before the fix reproduces every table of this folder byte for byte. The
differences below therefore come from the fix alone, and all of them start on
2025-10-27.

| Book, control period 2025-01-02 to 2026-10-09 | Net return, archived | Net return, fixed | Sharpe, archived | Sharpe, fixed | Costs EUR, archived | Costs EUR, fixed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| SA15_GPT-6.1 (trial 8) | 23.53% | 23.58% | 1.240 | 1.242 | 1979 | 1965 |
| SA15_GPT-6.1, costs x2 | 21.18% | 21.25% | 1.129 | 1.133 | 3915 | 3883 |
| equal_weight | 32.90% | 33.30% | 1.497 | 1.512 | 564 | 479 |
| World_buy_hold, SP500_buy_hold, SA1_MA20 | unchanged | unchanged | unchanged | unchanged | unchanged | unchanged |

- Maximum drawdown of SA15_GPT-6.1 unchanged (-10.08%); its gap to World held
  goes from -1.01 to -0.96 point; the block bootstrap of the annualised active
  return goes from -0.99% [-17.16%; +13.66%] to -0.97% [-17.17%; +13.73%].
- Full history 2019-06-03 to 2026-10-09 (`robustness/full.csv`): SA15_GPT-6.1
  from +158.35% to +158.47% (Sharpe 1.278 to 1.279), equal_weight from
  +141.45% to +142.40% (Sharpe 1.152 to 1.156); the other books unchanged.
- Restarts from cash and doubled costs on development and validation:
  unchanged.
- **The verdict does not change**: NOT_SUPPORTED, the selection still trails
  World held on the control period, and equal_weight still leads it.

Reproduction, in a new folder (`--full-only` writes `full/`; after it
`SA15_report_gpt61.py` stops on `KeyError: 'alpha_vs_world'`, with or without
the fix):

```bash
uv run python scripts/SA15_download_data.py
OUT=runs/sa15_r1_rerun
for N in 01 02 03 04 05 06 07 08 09 10; do
  uv run python scripts/SA15_run_gpt61_study.py --candidate research/SA15_GPT-6.1/candidates/trial_$N.json --output "$OUT"
done
uv run python scripts/SA15_run_gpt61_study.py --final --output "$OUT"
uv run python scripts/SA15_robustness_gpt61.py --output "$OUT" --workers 3
uv run python scripts/SA15_robustness_gpt61.py --output "$OUT" --workers 3 --full-only
```


Statut de l'hypothese : **NOT_SUPPORTED**. Configuration retenue : **essai 8**,
choisie uniquement sur developpement 2019-06-03/2022-12-30 et selection
2023-01-02/2024-12-31 parmi **10 configurations**. Le controle
2025-01-02/2026-10-09 est lu apres gel de cette selection.

| Livre | Rendement net | CAGR | Volatilite | Sharpe | Drawdown max | Frais EUR |
| --- | --- | --- | --- | --- | --- | --- |
| SA15_GPT-6.1 | 23.53 % | 12.71 % | 9.90 % | 1.24 | -10.08 % | 1979 |
| World_buy_hold | 24.54 % | 13.23 % | 14.31 % | 0.93 | -21.51 % | 99 |
| SA1_MA20 | 2.54 % | 1.43 % | 9.02 % | 0.20 | -10.09 % | 5711 |
| SP500_buy_hold | 22.89 % | 12.38 % | 15.38 % | 0.82 | -23.16 % | 99 |
| equal_weight | 32.90 % | 17.47 % | 11.00 % | 1.50 | -13.55 % | 564 |

L'ecart net total contre World est de
**-1.01 points**, et contre SA1 de
**20.99 points**. L'alpha annuel
de regression contre World est 6.19 %, beta
0.46. Alpha, surperformance totale et CAGR mesurent
des choses differentes.

Allocation moyenne reellement detenue pendant le controle final :
**85.65 %** en vehicules hors monetaire,
**13.62 %** en ETF monetaire et
**0.73 %** en liquidites.
Le capital investi total inclut le monetaire ; le hors-monetaire inclut aussi
l'or, les matieres premieres et les obligations, et ne mesure pas une exposition actions.

## Strategie retenue et fonctionnement

Sept vehicules possibles : S&P 500, Nasdaq, emergents, or (ETC Xetra-Gold),
obligations souveraines mondiales couvertes EUR, matieres premieres couvertes EUR,
ETF monetaire. Maximum top_k actifs tactiques, plus le coeur et le monetaire
si les parametres le demandent. Aucun levier, aucune vente a decouvert.
Frequence retenue : **hebdomadaire**.
Signaux calcules a **23:00:00, Europe/Paris**.
Les ordres de parts entieres sont prepares apres les clotures et executes
au prix d'ouverture de la prochaine seance ; l'instant d'execution du moteur
est **09:01:00** dans le meme fuseau.
La strategie ne negocie jamais au close qui a produit son signal.

Parametres complets de l'essai retenu :

| Parametre | Valeur effective |
| --- | --- |
| risky_ids | ["ETF_SP500_PEA", "ETF_NASDAQ", "ETF_EMERGING", "ETF_GOLD", "ETF_EURO_GOV", "ETF_COMMODITY"] |
| monetary_id | "ETF_MONETARY_EUR" |
| momentum_lookbacks | [21, 63, 126, 252] |
| momentum_weights | [1.0, 1.0, 1.0, 1.0] |
| top_k | 3 |
| use_trend_filter | true |
| trend_sessions | 200 |
| short_returns | 20 |
| long_returns | 60 |
| target_volatility | 0.18 |
| volatility_floor | 0.05 |
| volatility_power | 1.0 |
| renormalize_active | false |
| max_asset_weight | 1.0 |
| core_fraction | 0.5 |
| core_id | "ETF_SP500_PEA" |
| monetary_lookback | 21 |
| monetary_maximum_volatility | 0.02 |
| max_age_sessions | 1 |
| rebalance_band | 0.05 |
| strategy_id | "SA15_GPT-6.1" |

Le score utilise les CAGR et drawdowns des deux premieres periodes, avec une
penalite d'instabilite. Sa formule etait ecrite avant le premier essai dans
[le protocole](../../research/SA15_GPT-6.1/protocol.md). Il n'est ni un rendement
ni une probabilite de reussite.

## Tous les essais

| Essai | CAGR dev. | CAGR selection | DD dev. | DD selection | Score | DSR selection |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 11.50 % | 17.26 % | -12.86 % | -8.02 % | 0.1120 | 0.976 |
| 2 | 11.14 % | 17.59 % | -13.69 % | -8.03 % | 0.1100 | 0.977 |
| 3 | 8.36 % | 17.14 % | -19.60 % | -8.03 % | 0.0841 | 0.959 |
| 4 | 10.72 % | 17.35 % | -16.92 % | -7.84 % | 0.1027 | 0.974 |
| 5 | 9.97 % | 19.73 % | -14.52 % | -8.12 % | 0.1104 | 0.988 |
| 6 | 9.74 % | 19.31 % | -17.36 % | -8.13 % | 0.1038 | 0.986 |
| 7 | 8.03 % | 16.88 % | -15.03 % | -8.11 % | 0.0868 | 0.974 |
| 8 | 10.40 % | 20.36 % | -15.40 % | -8.09 % | 0.1144 | 0.990 |
| 9 | 11.01 % | 18.84 % | -13.65 % | -8.04 % | 0.1143 | 0.985 |
| 10 | 6.33 % | 13.05 % | -17.42 % | -8.49 % | 0.0578 | 0.947 |

Les changements et leurs motivations :

1. Point de départ inspiré du momentum multi-horizon : top3, filtre200 séances, poids inverse volatilité et plafond de risque18%.
2. Essai1 : rotation13-14 fois/an et frais6427EUR en développement. Espacer les décisions au mois pour limiter le changement de classement et les frais, mêmes signaux et risque.
3. Essai2 réduit les frais mais reste derrière World en validation. Tester une sélection top2 au lieu de top3 pour moins diluer les leaders, en conservant fréquence mensuelle et contrôle18%.
4. Le top2 (essai3) détériore développement et validation. Revenir top3 mensuel et tester des poids égaux : l'inverse volatilité peut surpondérer les actifs défensifs au détriment des tendances actions.
5. Poids égaux (essai4) ne corrigent pas la sous-performance en sélection. Ajouter un coeur S&P500 de50%, toujours filtré par momentum/tendance, avec50% pour la rotation top3 inversevol ; conserver mensuel et risque18%.
6. Le coeur50% améliore CAGR de sélection à19.73% et baisse les frais mais pénalise développement. Tester le momentum seul sans double filtre de moyenne200, pour entrer plus tôt après retournements ; coeur50% et mensuel inchangés.
7. Retirer totalement la tendance (essai6) aggrave le drawdown. Garder le coeur50% et le filtre mais raccourcir la moyenne de200 à126 séances pour réduire le retard aux reprises.
8. Le filtre126 (essai7) perd encore. Le meilleur score reste l'hebdomadaire initial ; combiner cette fréquence avec le coeur50% de l'essai5, qui améliorait fortement la participation actions en sélection.
9. L'hebdomadaire avec coeur50% (essai8) donne enfin le meilleur score, mais l'écart est faible. Tester son voisin coeur25% pour vérifier si un coeur plus modeste conserve la hausse tout en améliorant le développement.
10. Le coeur25% (essai9) reste très proche du coeur50%, sans le dépasser. Dernier essai : conserver coeur50% hebdomadaire et accélérer le momentum en pondérant les horizons21/63/126/252 par12/4/2/1 pour améliorer les retournements ; ne rien sélectionner sur le contrôle final.

Le DSR corrige le Sharpe de selection avec 10 essais et une dispersion
empirique de leurs Sharpe par seance de 0.011130. Ces essais sont correles ;
le DSR est un diagnostic approximatif, pas une preuve de rendement superieur
a World. Les choix anciens du projet et la selection de l'univers ne sont pas
captures par ce decompte.

## Controle final et robustesse

| Annee | SA15 | World | SA1 | S&P 500 | Panier equipondere |
| --- | --- | --- | --- | --- | --- |
| 2025 | 6.36 % | 5.92 % | 2.56 % | 3.01 % | 15.93 % |
| 2026 | 16.14 % | 17.58 % | -0.02 % | 19.30 % | 14.64 % |

Les annees extremes du tableau sont partielles. Meme capital initial
100 000 EUR et memes frais pour chaque livre de chaque periode.
Avec commission, spread et slippage doubles, SA15 gagne
**21.18 %**, CAGR **11.49 %**,
drawdown **-10.83 %** ; frais
3915 EUR. Il s'agit d'un second vrai backtest, avec
les memes seuils, pas d'une soustraction de frais a posteriori.
Le statut reste UNCERTAIN si cette version aux frais doubles ne surpasse
plus World et SA1 aux frais standards, meme si l'intervalle bootstrap est positif.
Cette comparaison est volontairement prudente ; le DSR reste un diagnostic
sans nouveau seuil de decision.

Bootstrap apparie de l'exces de rendement moyen annualise contre World :
**-0.99 %**, intervalle 95 %
**[-17.16 % ; 13.66 %]**.
2000 tirages, blocs circulaires de 20 seances, seed 6115. Ce n'est pas un
intervalle du CAGR ni une correction des essais multiples.

Les frais doubles des configurations figurent dans
[le tableau des frais doubles](robustness/costs_x2.csv), et les vrais redemarrages
du gagnant dans [les departs glissants](robustness/starts.csv).
Les variantes proches de ponderation, frequence et horizons sont les essais
publies ci-dessus ; aucune recherche de grille cachee n'a ete realisee.

## Historique complet, du 3 juin 2019 au 9 octobre 2026

| Livre | Rendement net | CAGR | Sharpe | Drawdown max | Alpha annuel / World |
| --- | --- | --- | --- | --- | --- |
| SA15_GPT-6.1 | 158.35 % | 13.78 % | 1.28 | -15.40 % | 6.71 % |
| World_buy_hold | 167.08 % | 14.30 % | 0.91 | -33.40 % | 0.00 % |
| SA1_MA20 | 45.08 % | 5.19 % | 0.54 | -18.95 % | -0.43 % |
| SP500_buy_hold | 211.42 % | 16.71 % | 0.99 | -33.42 % | 1.58 % |
| equal_weight | 141.45 % | 12.74 % | 1.15 | -20.47 % | 4.10 % |

Cette periode inclut le developpement, la selection et le controle final. Elle decrit le gagnant retrospectif et ne constitue pas une validation supplementaire.

[Courbes completes](comparison/full/comparison.png) · [Tableau complet](comparison/full/summary.csv).

## Limites et verdict pratique

Le resultat final ne garantit aucune performance future et ne constitue pas
une demonstration permettant de devenir riche. Cette histoire etait deja connue
dans le projet ; univers choisi retrospectivement et uniquement parmi des
fonds encore disponibles. Les prix ont ete telecharges aujourd'hui, et ne
constituent pas des vintages archives aux dates anciennes. Une seule source
pour les nouveaux vehicules ; exposition devises sous-jacente conservee.
Le Sharpe utilise un taux sans risque nul, comme les autres etudes du projet.

L'or et les emergents ont deux trous fournisseur confirmes (24 octobre 2025,
6 mars 2026). Les fenetres consecutives de 252 seances excluent longtemps ces
actifs : aucun cours n'est interpole. Une decision peut continuer avec d'autres
actifs tout en signalant ces refus. Le nombre de decisions finales avec au moins
un input refuse est **51**.
C'est une limite de deployabilite et de representativite du test.

Les titres sont traites en compte EUR : les nouveaux vehicules ne forment
pas un univers PEA. Xetra-Gold est un ETC, pas un ETF UCITS. XDBC a change
d'indice le 21 mai 2021. L'identifiant technique ETF_EURO_GOV designe en fait
des obligations mondiales couvertes EUR.
Voir [la notice des donnees](../../research/SA15_GPT-6.1/data.md).

La transcription de l'hypothese dans le registre central a suivi l'essai 1 ;
le protocole local avait ete ecrit avant. Le code est un travail non commite :
la provenance le declare DIRTY, avec le commit de depart et les empreintes
des donnees/configurations. Aucun resultat anterieur n'a ete remplace.
Le source exact et les metadonnees sont archives avant le gel dans
[source.zip](source/source.zip), avec [manifest des empreintes](source/manifest.json).
Cette archive financiere originale est conservee ; le correctif ulterieur de rendu
est archive separement dans [postprocessing](postprocessing/). Il ne change aucune
decision, transaction, selection ni metrique financiere sauvegardee.

## Sources et reproduction

- [Moskowitz, Ooi et Pedersen — Time Series Momentum](https://fairmodel.econ.yale.edu/ec439/mosk.pdf).
- [Keller et Keuning — Hybrid Asset Allocation](https://ssrn.com/abstract=4346906).
- [Moreira et Muir — Volatility Managed Portfolios](https://conference.nber.org/confer/2016/LTAMs16/Moreira_Muir.pdf).
- [Forum Bogleheads — Dual Momentum Investing](https://www.bogleheads.org/forum/viewtopic.php?start=100&t=158297).

Ces travaux ont inspire l'hypothese ; leurs performances ne sont pas
attribuees a notre implementation. Les forums fournissent des objections
pratiques, pas des preuves.

```bash
uv run python scripts/SA15_download_data.py
CANDIDATES=research/SA15_GPT-6.1/candidates
OUT=runs/sa15_reproduction
# Utiliser un nouveau dossier de sortie ; reprendre ensuite les essais 02 a 10, dans l'ordre.
CANDIDATE="$CANDIDATES/trial_01.json"
uv run python scripts/SA15_run_gpt61_study.py --candidate "$CANDIDATE" --output "$OUT"
uv run python scripts/SA15_run_gpt61_study.py --final --output "$OUT"
# Regenerer uniquement les exports deja calcules, sans aucun backtest :
uv run python scripts/SA15_run_gpt61_study.py --render-only --output "$OUT"
uv run python scripts/SA15_robustness_gpt61.py --output "$OUT"
uv run python scripts/SA15_report_gpt61.py --output "$OUT"
```

[Courbes finales](comparison/final/comparison.png) ·
[Tableau final](comparison/final/summary.csv) ·
[Tous les essais](iterations.csv) · [Selection gelee](selected.json).


[Vérifications du code et des artefacts](validation.md).
