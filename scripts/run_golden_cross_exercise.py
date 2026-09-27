"""Exercice « Moving-Average Crossover » : lancer GoldenCrossETF et lire ses résultats.

Squelette des étapes 4 et 5 de ``exercice_moving_average_crossover.pdf``.
Depuis la racine du dépôt, une fois le store rempli (étape 1) :

    uv run python scripts/run_golden_cross_exercise.py --output golden_cross_output

Les fonctions lèvent ``NotImplementedError`` : à vous de les écrire. Le test de
:func:`build_runner` est dans ``tests/strategies/test_golden_cross_etf.py``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from quant_backtester.backtest.runner import StrategyResult, StrategyRunner

STORE = Path(__file__).resolve().parents[1] / "market_data"
"""Racine du store : ``metadata/`` commité, ``raw/`` et ``clean/`` locaux."""

UNIVERSE = ("ETF_WORLD",)
"""L'univers de trading de l'exercice (question 4.1 : pourquoi une liste statique ?)."""

PERIOD = ("2019-04-01", "2026-09-17")
"""La période mesurée, bornes incluses."""


def build_runner(root: Path) -> StrategyRunner:
    """Return the runner of the exercise, every assumption of §1.4 declared.

    Parameters
    ----------
    root : Path
        Racine du store, qui contient ``metadata/instruments.toml`` et
        ``metadata/calendars/``.

    Returns
    -------
    StrategyRunner
        Calendrier de référence XPAR, livre en EUR, benchmark ETF_WORLD, et les
        hypothèses du chapitre 1 : capital, coûts, ordre minimum, analytics.

    Notes
    -----
    Exercice MA 4. Chargez le registre des instruments, les calendriers, le
    repository et le reader, puis le modèle d'exécution et ``AnalyticsConfig``.
    ``scripts/run_baselines.py`` construit un runner comparable : lisez-le
    pour les imports et les constructeurs, pas pour recopier ses constantes.
    Chaque hypothèse de §1.4 doit être écrite ici, nommée, et non laissée à
    une valeur par défaut.
    """
    raise NotImplementedError("Exercice MA 4")


def print_run(result: StrategyResult) -> None:
    """Print what identifies the run, then its report, comparison and tables.

    Parameters
    ----------
    result : StrategyResult
        Le run terminé.

    Notes
    -----
    Exercice MA 4.2 et 5. Au minimum : le ``run_id``, l'empreinte de la
    stratégie et la période réellement retenue par le moteur ; puis le rapport,
    la comparaison au benchmark, et les tables ``orders``, ``fills``,
    ``rejects``, ``weights`` et ``costs``.
    """
    raise NotImplementedError("Exercice MA 5")


def save_figures(result: StrategyResult, directory: Path) -> None:
    """Save the equity and drawdown curves of the run as PNG files.

    Parameters
    ----------
    result : StrategyResult
        Le run terminé.
    directory : Path
        Dossier de sortie, créé s'il n'existe pas.

    Notes
    -----
    Exercice MA 5. Le résultat sait dessiner ses courbes ; une figure se
    sauvegarde, elle ne s'affiche pas dans un script.
    """
    raise NotImplementedError("Exercice MA 5")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the exercise and print its results.

    Parameters
    ----------
    argv : Sequence[str] | None
        Arguments de la ligne de commande ; ``sys.argv[1:]`` si ``None``.

    Returns
    -------
    int
        Le code de sortie, 0 en cas de succès.

    Notes
    -----
    Exercice MA 4.2. Construisez le runner, lancez ``GoldenCrossETF`` sur
    ``UNIVERSE`` et ``PERIOD``, puis appelez :func:`print_run` et
    :func:`save_figures`.
    """
    parser = argparse.ArgumentParser(description="Run the golden cross exercise.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("golden_cross_output"),
        help="where the equity and drawdown figures are written",
    )
    parser.parse_args(argv)
    raise NotImplementedError("Exercice MA 4.2")


if __name__ == "__main__":
    sys.exit(main())
