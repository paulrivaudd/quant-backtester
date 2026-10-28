"""Write a compact French SA15 report from saved, completed research runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from SA15_run_gpt61_study import ANALYTICS, DEFAULT_OUTPUT, load_equity, write_json

from quant_backtester.analytics.quality import deflated_sharpe_probability, session_sharpe


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    """Render a small table without adding a formatting dependency."""
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def percent(value: float) -> str:
    """Format fractional returns in percent for the human report."""
    return f"{value * 100:.2f} %"


def report(output: Path) -> None:
    """Summarise all trials, the frozen final result and sampling uncertainty."""
    selected = json.loads((output / "selected.json").read_text())
    trial = selected["candidate"]["number"]
    definition = json.loads((output / "final/SA15_GPT-6.1/strategy.json").read_text())
    parameters = definition["parameters"]
    configuration = json.loads((output / "final/SA15_GPT-6.1/configuration.json").read_text())
    timetable = configuration["timetable"]
    schedule_name = {
        "daily": "quotidienne",
        "weekly": "hebdomadaire",
        "monthly": "mensuelle",
    }[selected["candidate"]["schedule"]]
    parameter_table = markdown_table(
        ["Parametre", "Valeur effective"],
        [[name, json.dumps(value, ensure_ascii=False)] for name, value in parameters.items()],
    )
    iterations = pd.read_csv(output / "iterations.csv")
    final = pd.read_csv(output / "comparison/final/summary.csv", index_col="book")
    yearly = pd.read_csv(output / "comparison/final/yearly.csv", index_col="year")
    uncertainty = json.loads((output / "final/uncertainty.json").read_text())
    stress = json.loads((output / "final/costs_x2/metrics.json").read_text())
    weights = pd.read_csv(output / "final/SA15_GPT-6.1/weights.csv", index_col=0, parse_dates=True)
    monetary_id = parameters["monetary_id"]
    monetary = weights.get(monetary_id, pd.Series(0.0, index=weights.index))
    invested = weights.sum(axis=1)
    exposure = {
        "average_invested_including_monetary": float(invested.mean()),
        "average_monetary_etf": float(monetary.mean()),
        "average_invested_excluding_monetary": float((invested - monetary).mean()),
        "average_cash": float((1.0 - invested).clip(lower=0.0).mean()),
    }
    write_json(output / "final/exposure.json", exposure)
    candidates = []
    curves = []
    for number in iterations["trial"]:
        folder = output / f"trial_{number:02d}"
        candidates.append(json.loads((folder / "candidate.json").read_text()))
        curves.append(load_equity(folder / "validation/equity.csv"))
    sharpes = [session_sharpe(curve, ANALYTICS) for curve in curves]
    dispersion = float(np.std([value for value in sharpes if value is not None], ddof=1))
    dsr = {
        str(spec["number"]): deflated_sharpe_probability(
            curve,
            ANALYTICS,
            trials=len(curves),
            trial_sharpe_std=dispersion,
        )
        for spec, curve in zip(candidates, curves, strict=True)
    }
    write_json(
        output / "selection_diagnostics.json",
        {"trials": len(curves), "session_sharpe_std": dispersion, "validation_dsr": dsr},
    )
    strategy, world, base = (
        final.loc[name] for name in ("SA15_GPT-6.1", "World_buy_hold", "SA1_MA20")
    )
    ahead = strategy["net_return"] > max(world["net_return"], base["net_return"])
    stress_ahead = stress["net_return"] > max(world["net_return"], base["net_return"])
    status = (
        "UNCERTAIN"
        if ahead and (uncertainty["lower_95"] <= 0 or not stress_ahead)
        else "SUPPORTED_RETROSPECTIVE"
        if ahead
        else "NOT_SUPPORTED"
    )
    table = markdown_table(
        ["Livre", "Rendement net", "CAGR", "Volatilite", "Sharpe", "Drawdown max", "Frais EUR"],
        [
            [
                name,
                percent(row["net_return"]),
                percent(row["cagr"]),
                percent(row["volatility"]),
                f"{row['sharpe']:.2f}",
                percent(row["max_drawdown"]),
                f"{row['costs_eur']:.0f}",
            ]
            for name, row in final.iterrows()
        ],
    )
    trial_table = markdown_table(
        [
            "Essai",
            "CAGR dev.",
            "CAGR selection",
            "DD dev.",
            "DD selection",
            "Score",
            "DSR selection",
        ],
        [
            [
                str(int(row["trial"])),
                percent(row["development_cagr"]),
                percent(row["validation_cagr"]),
                percent(row["development_max_drawdown"]),
                percent(row["validation_max_drawdown"]),
                f"{row['score']:.4f}",
                f"{dsr[str(int(row['trial']))]:.3f}",
            ]
            for _, row in iterations.iterrows()
        ],
    )
    reasons = "\n".join(f"{spec['number']}. {spec['reason']}" for spec in candidates)
    year_table = markdown_table(
        ["Annee", "SA15", "World", "SA1", "S&P 500", "Panier equipondere"],
        [
            [str(year)] + [percent(row[name]) for name in final.index]
            for year, row in yearly.iterrows()
        ],
    )
    full_section = ""
    full_path = output / "comparison/full/summary.csv"
    if full_path.is_file():
        full = pd.read_csv(full_path, index_col="book")
        full_table = markdown_table(
            ["Livre", "Rendement net", "CAGR", "Sharpe", "Drawdown max", "Alpha annuel / World"],
            [
                [
                    name,
                    percent(row["net_return"]),
                    percent(row["cagr"]),
                    f"{row['sharpe']:.2f}",
                    percent(row["max_drawdown"]),
                    percent(row["alpha_vs_world"]),
                ]
                for name, row in full.iterrows()
            ],
        )
        full_section = (
            "## Historique complet, du 3 juin 2019 au 9 octobre 2026\n\n"
            + full_table
            + "\n\nCette periode inclut le developpement, la selection et le controle final. "
            "Elle decrit le gagnant retrospectif et ne constitue pas une validation supplementaire."
            "\n\n[Courbes completes](comparison/full/comparison.png) ? "
            "[Tableau complet](comparison/full/summary.csv).\n\n"
        )
    text = f"""# SA15_GPT-6.1 — etude retrospective du 15 octobre 2026

Statut de l'hypothese : **{status}**. Configuration retenue : **essai {trial}**,
choisie uniquement sur developpement 2019-06-03/2022-12-30 et selection
2023-01-02/2024-12-31 parmi **{len(iterations)} configurations**. Le controle
2025-01-02/2026-10-09 est lu apres gel de cette selection.

{table}

L'ecart net total contre World est de
**{(strategy["net_return"] - world["net_return"]) * 100:.2f} points**, et contre SA1 de
**{(strategy["net_return"] - base["net_return"]) * 100:.2f} points**. L'alpha annuel
de regression contre World est {percent(strategy["alpha_vs_world"])}, beta
{strategy["beta_vs_world"]:.2f}. Alpha, surperformance totale et CAGR mesurent
des choses differentes.

Allocation moyenne reellement detenue pendant le controle final :
**{percent(exposure["average_invested_excluding_monetary"])}** en vehicules hors monetaire,
**{percent(exposure["average_monetary_etf"])}** en ETF monetaire et
**{percent(exposure["average_cash"])}** en liquidites.
Le capital investi total inclut le monetaire ; le hors-monetaire inclut aussi
l'or, les matieres premieres et les obligations, et ne mesure pas une exposition actions.

## Strategie retenue et fonctionnement

Sept vehicules possibles : S&P 500, Nasdaq, emergents, or (ETC Xetra-Gold),
obligations souveraines mondiales couvertes EUR, matieres premieres couvertes EUR,
ETF monetaire. Maximum top_k actifs tactiques, plus le coeur et le monetaire
si les parametres le demandent. Aucun levier, aucune vente a decouvert.
Frequence retenue : **{schedule_name}**.
Signaux calcules a **{timetable["decision_time"]}, {timetable["timezone"]}**.
Les ordres de parts entieres sont prepares apres les clotures et executes
au prix d'ouverture de la prochaine seance ; l'instant d'execution du moteur
est **{timetable["execution_time"]}** dans le meme fuseau.
La strategie ne negocie jamais au close qui a produit son signal.

Parametres complets de l'essai retenu :

{parameter_table}

Le score utilise les CAGR et drawdowns des deux premieres periodes, avec une
penalite d'instabilite. Sa formule etait ecrite avant le premier essai dans
[le protocole](../../research/SA15_GPT-6.1/protocol.md). Il n'est ni un rendement
ni une probabilite de reussite.

## Tous les essais

{trial_table}

Les changements et leurs motivations :

{reasons}

Le DSR corrige le Sharpe de selection avec {len(iterations)} essais et une dispersion
empirique de leurs Sharpe par seance de {dispersion:.6f}. Ces essais sont correles ;
le DSR est un diagnostic approximatif, pas une preuve de rendement superieur
a World. Les choix anciens du projet et la selection de l'univers ne sont pas
captures par ce decompte.

## Controle final et robustesse

{year_table}

Les annees extremes du tableau sont partielles. Meme capital initial
100 000 EUR et memes frais pour chaque livre de chaque periode.
Avec commission, spread et slippage doubles, SA15 gagne
**{percent(stress["net_return"])}**, CAGR **{percent(stress["cagr"])}**,
drawdown **{percent(stress["max_drawdown"])}** ; frais
{stress["costs_eur"]:.0f} EUR. Il s'agit d'un second vrai backtest, avec
les memes seuils, pas d'une soustraction de frais a posteriori.
Le statut reste UNCERTAIN si cette version aux frais doubles ne surpasse
plus World et SA1 aux frais standards, meme si l'intervalle bootstrap est positif.
Cette comparaison est volontairement prudente ; le DSR reste un diagnostic
sans nouveau seuil de decision.

Bootstrap apparie de l'exces de rendement moyen annualise contre World :
**{percent(uncertainty["annualised_mean_active_return"])}**, intervalle 95 %
**[{percent(uncertainty["lower_95"])} ; {percent(uncertainty["upper_95"])}]**.
2000 tirages, blocs circulaires de 20 seances, seed 6115. Ce n'est pas un
intervalle du CAGR ni une correction des essais multiples.

Les frais doubles des configurations figurent dans
[le tableau des frais doubles](robustness/costs_x2.csv), et les vrais redemarrages
du gagnant dans [les departs glissants](robustness/starts.csv).
Les variantes proches de ponderation, frequence et horizons sont les essais
publies ci-dessus ; aucune recherche de grille cachee n'a ete realisee.

{full_section}## Limites et verdict pratique

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
un input refuse est **{int(strategy["decisions_with_skipped_inputs"])}**.
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
"""
    (output / "study.md").write_text(text, encoding="utf-8")
    print(f"wrote {output / 'study.md'}")


def main() -> None:
    """Build the human report after final evaluation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    report(parser.parse_args().output)


if __name__ == "__main__":
    main()
