# Résultats et analyses du 10 octobre 2026

Un rapport par stratégie, écrit par `scripts/write_strategy_reports.py` à
partir des exports de `scripts/run_garch_study.py`, après mise à jour du
magasin jusqu'au 2026-10-09.

Chaque fichier `strategy<CODE>_ResultsAndAnalysis_10102026.md` a trois
sections : (1) les indicateurs de résultat globaux, à côté du fonds détenu ;
(2) l'analyse — faits mesurés, points forts, points faibles, pire et meilleure
période, situations de marché les plus risquées ; (3) l'historique séance par
séance du sous-jacent, des indicateurs lus par la stratégie, de ses poids et de
sa valeur.

## Classement commun

Période 2021-04-01 → 2026-10-09 (1 416 séances), 100 000 EUR, commission 5 pb
(minimum 1 EUR), demi-spread 3 pb, slippage 2 pb, quantités fixées à la
décision, cash non rémunéré. Score `QUALITY_V1` contre `ETF_WORLD` détenu,
déflaté par 10 essais.

| Rang | Stratégie | Score | Net | Sharpe | Perte max. | Coûts (EUR) | Rapport |
|---:|---|---:|---:|---:|---:|---:|---|
| 2 | EWMA 0,94 (témoin de SA11, sans code) | 53,6 % | +73,4 % | 0,93 | -15,4 % | 1 519 | [rapport](strategyEWMA94control_ResultsAndAnalysis_10102026.md) |
| 3 | SA6 - vol control | 52,0 % | +67,4 % | 0,90 | -15,7 % | 1 445 | [rapport](strategySA6_ResultsAndAnalysis_10102026.md) |
| 4 | SA10 - ensemble | 51,1 % | +32,1 % | 0,86 | -11,8 % | 1 986 | [rapport](strategySA10_ResultsAndAnalysis_10102026.md) |
| 5 | SA3 - smooth MA | 49,0 % | +57,9 % | 0,79 | -21,6 % | 680 | [rapport](strategySA3_ResultsAndAnalysis_10102026.md) |
| 6 | **SA11 - GARCH vol control** | 48,6 % | +66,0 % | 0,87 | -16,5 % | 3 749 | [rapport](strategySA11_ResultsAndAnalysis_10102026.md) |
| 7 | SA2 - dual momentum | 44,1 % | +69,2 % | 0,78 | -22,8 % | 4 629 | [rapport](strategySA2_ResultsAndAnalysis_10102026.md) |
| 8 | SA5 - relative tilt | 29,4 % | +72,8 % | 0,76 | -22,9 % | 20 517 | [rapport](strategySA5_ResultsAndAnalysis_10102026.md) |
| 9 | SA1 - std MA20 | 0,0 % | +20,5 % | 0,42 | -18,9 % | 15 730 | [rapport](strategySA1_ResultsAndAnalysis_10102026.md) |
| 9 | SA4 - pullback | 0,0 % | +4,4 % | 0,41 | -3,4 % | 4 572 | [rapport](strategySA4_ResultsAndAnalysis_10102026.md) |
| 9 | SA9 - VIX relief | 0,0 % | -0,7 % | -0,04 | -8,0 % | 2 041 | [rapport](strategySA9_ResultsAndAnalysis_10102026.md) |
| — | ETF_WORLD détenu (étalon, non noté) | — | +94,8 % | 0,93 | -21,6 % | 100 | — |

Le rang 1 revient à la référence « 50/50 rebalancé » (77,9 %, +103,3 %), qui
n'est pas une stratégie du catalogue et n'a pas de rapport. Trois scores nuls
partagent le rang 9. Le score est un indice composite, pas une probabilité de
gain, et le registre des essais ne contient pas les variantes des exercices
antérieurs : le classement est exploratoire.

## SA11 : l'hypothèse est réfutée

`SA11` a la meilleure prévision de variance (QLIKE -8,6225 contre -8,6033 pour
l'EWMA et -8,5649 pour l'estimateur de `SA6`) et aucun repli sur 1 416
décisions. Mais son Sharpe net (0,87) est sous celui de `SA6` (0,90) et du
témoin EWMA (0,93), sa perte maximale est plus profonde, et elle coûte deux
fois et demie plus. À coûts doublés l'écart avec l'EWMA exclut zéro. La règle
simple est conservée ; `SA11` reste au catalogue comme référence fixe. Détail :
[SA11_study_10102026.md](SA11_study_10102026.md).

## Hors classement

- **ML1** ([rapport](strategyML1_ResultsAndAnalysis_10102026.md)) : son
  information s'arrête au 2024-12-31. Il est mesuré sur 2025-01-02 →
  2026-10-09 (+13,4 % contre +24,5 % pour le fonds, Sharpe 0,76 contre 0,93) et
  ses chiffres ne se comparent pas à ceux du tableau.
- **SA7** (factor blend) et **SA8** (monetary carry) n'ont pas été exécutées :
  leurs instruments ne sont pas enregistrés dans le magasin.

## Reproduire

```bash
uv sync --extra ml --extra stats
uv run python scripts/update_market_data.py
uv run python scripts/run_garch_study.py --output results/garch_study
uv run python scripts/write_strategy_reports.py \
    --study results/garch_study --output research/reports/2026-10-10
```

Le commentaire rédigé est dans [commentary.toml](commentary.toml) ; les
tableaux et les faits mesurés sont recalculés à chaque exécution. Tout est une
évaluation rétrospective : l'historique d'`ETF_WORLD` a déjà été regardé, et la
vérification prospective de `SA11` commence à la première séance XPAR après le
2026-10-10.
