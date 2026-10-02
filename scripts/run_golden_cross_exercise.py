"""Exercice « Moving-Average Crossover » : lancer GoldenCrossETF et lire ses résultats.

Squelette des étapes 4 et 5 de ``exercice_moving_average_crossover.pdf``.
Depuis la racine du dépôt, une fois le store rempli (étape 1) :

    uv run python scripts/run_golden_cross_exercise.py --output golden_cross_output

Les tests sont dans ``tests/strategies/test_golden_cross_etf.py``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import pandas as pd

from quant_backtester.analytics.comparison import BenchmarkBasis, BenchmarkSpec
from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.backtest.runner import StrategyResult, StrategyRunner
from quant_backtester.data.calendars import CalendarRegistry
from quant_backtester.data.instruments import InstrumentRegistry
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.repository import MarketDataRepository
from quant_backtester.execution.costs import CostModel
from quant_backtester.execution.model import ExecutionModel, Sizing
from quant_backtester.provenance import git_source_state
from quant_backtester.strategies import GoldenCrossETF

REPOSITORY = Path(__file__).resolve().parents[1]
"""Racine du dépôt : son commit et son ``uv.lock`` sont enregistrés avec le run."""

STORE = REPOSITORY / "market_data"
"""Racine du store : ``metadata/`` commité, ``raw/`` et ``clean/`` locaux."""

UNIVERSE = ("ETF_WORLD",)
"""L'univers de trading de l'exercice (question 4.1 : pourquoi une liste statique ?)."""

PERIOD = ("2019-04-01", "2026-09-17")
"""La période mesurée, bornes incluses."""

STRATEGY = GoldenCrossETF(instrument_id="ETF_WORLD", fast_sessions=50, slow_sessions=200)
"""La stratégie de l'exercice, ses trois paramètres écrits et non laissés à leur défaut."""

TABLE_ROWS = 10
"""Lignes affichées par table : les premières et les dernières au-delà."""

FIGURE_DPI = 160
"""Résolution des figures enregistrées."""

REFERENCE_CALENDAR = "XPAR"
"""Le calendrier sur lequel le run avance : celui de la place où l'ETF se négocie."""

BASE_CURRENCY = "EUR"
"""La devise du livre."""

INITIAL_CASH = 100_000.0
"""Le capital de départ, en EUR."""

EXECUTION = ExecutionModel(
    costs=CostModel(
        commission_rate=0.0005,
        minimum_commission=1.0,
        half_spread_rate=0.0002,
        slippage_rate=0.0001,
    ),
    minimum_trade_value=500.0,
    sizing=Sizing.AT_AUCTION,
)
"""Les coûts de §1.4, en fraction du montant négocié sauf le plancher, en EUR.

Commission de 5 points de base avec un minimum de 1 EUR par ordre, demi-spread
de 2 points de base, slippage de 1 point de base ; un ordre de moins de 500 EUR
n'est pas envoyé.
"""

ANALYTICS = AnalyticsConfig(sessions_per_year=255, risk_free_rate=0.02, minimum_sessions=60)
"""255 séances par an, taux sans risque de 2 % par an, pour l'annualisation et le Sharpe."""

BENCHMARK = BenchmarkSpec("ETF_WORLD", basis=BenchmarkBasis.TOTAL_RETURN)
"""Le run est mesuré contre l'ETF lui-même, détenu sans y toucher."""


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
    instruments = InstrumentRegistry.from_toml(root / "metadata" / "instruments.toml")
    calendars = CalendarRegistry.from_directory(root / "metadata" / "calendars")
    reader = MarketDataReader(
        repository=MarketDataRepository(root),
        instruments=instruments,
        calendars=calendars,
        reference_calendar_id=REFERENCE_CALENDAR,
    )
    return StrategyRunner(
        reader=reader,
        calendars=calendars,
        reference_calendar_id=REFERENCE_CALENDAR,
        base_currency=BASE_CURRENCY,
        analytics=ANALYTICS,
        execution=EXECUTION,
        initial_cash=INITIAL_CASH,
        source=git_source_state(REPOSITORY),
        benchmark=BENCHMARK,
        lockfile=REPOSITORY / "uv.lock",
    )


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
    source = result.source.definition()
    print(f"run_id       {result.run_id}")
    print(f"strategy     {result.strategy_id}")
    print(f"fingerprint  {result.fingerprint}")
    print(f"period       {result.start} to {result.end}, {len(result.records())} sessions")
    print(f"source       {source['source_state']} {source['git_commit']}")
    print()
    print(result.report().render())
    print()
    print(result.compare().render())
    tables: dict[str, Callable[[], pd.DataFrame]] = {
        "orders": result.orders,
        "fills": result.fills,
        "rejects": result.rejects,
        "weights": result.weights,
        "costs": result.costs,
    }
    for name, table in tables.items():
        frame = table()
        print(f"\n== {name}: {len(frame)} rows ==")
        print(frame.to_string(max_rows=TABLE_ROWS) if len(frame) else "(none)")


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
    directory.mkdir(parents=True, exist_ok=True)
    result.plot().savefig(directory / "equity.png", dpi=FIGURE_DPI)
    result.plot_drawdown().savefig(directory / "drawdown.png", dpi=FIGURE_DPI)


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
    arguments = parser.parse_args(argv)

    result = build_runner(STORE).run(STRATEGY, UNIVERSE, *PERIOD)
    print_run(result)
    save_figures(result, arguments.output)
    print(f"\nFigures written to {arguments.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
