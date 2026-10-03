"""Exercice « Moving-Average Crossover » : lancer GoldenCrossETF et lire ses résultats.

Squelette des étapes 4 et 5 de ``exercice_moving_average_crossover.pdf``.
Depuis la racine du dépôt, une fois le store rempli (étape 1) :

    uv run python scripts/run_golden_cross_exercise.py --output golden_cross_output

Les tests sont dans ``tests/strategies/test_golden_cross_etf.py``.
"""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Callable, Collection, Sequence
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from matplotlib.figure import Figure

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

PRICE_COLOUR, FAST_COLOUR, SLOW_COLOUR, HELD_COLOUR = "#6b7280", "#c05621", "#1f4e79", "#2f855a"
"""Couleurs du graphe des moyennes : le prix, la rapide, la lente, les séances investies."""

SELL_COLOUR = "#c53030"
"""Couleur de la croix d'une vente ; celle d'un achat est ``HELD_COLOUR``."""

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


def session_date(value: object) -> date:
    """Return an index label as the session date it stands for.

    Raises
    ------
    TypeError
        Si la valeur n'est ni une date ni un horodatage.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError(f"expected a session date, got {value!r}")


def moving_averages(
    closes: pd.Series,  # type: ignore[type-arg]
    sessions: Sequence[date],
    fast: int,
    slow: int,
) -> pd.DataFrame:
    """Return the close and its two moving averages, one row per expected session.

    Parameters
    ----------
    closes : pd.Series
        Clôtures ajustées indexées par date de séance, connues après la clôture
        de la dernière séance de ``sessions``.
    sessions : Sequence[date]
        Les séances attendues du calendrier, dans l'ordre, trous compris.
    fast, slow : int
        Longueurs des deux moyennes, en séances.

    Returns
    -------
    pd.DataFrame
        Colonnes ``close``, ``fast`` et ``slow``, indexées par ``sessions``. La
        moyenne d'une séance ne lit que les clôtures de cette séance et des
        précédentes. Elle vaut ``NaN`` tant que ses N séances consécutives n'ont
        pas toutes une clôture : c'est le contrat du signal, qui refuse une
        fenêtre trouée plutôt que de la compléter avec des séances plus anciennes.
    """
    known = {session_date(day): float(value) for day, value in closes.items()}
    frame = pd.DataFrame(
        {"close": [known.get(day, math.nan) for day in sessions]},
        index=pd.Index(list(sessions), name="session_date"),
    )
    frame["fast"] = frame["close"].rolling(fast, min_periods=fast).mean()
    frame["slow"] = frame["close"].rolling(slow, min_periods=slow).mean()
    return frame


def cross_figure(
    averages: pd.DataFrame,
    held: Collection[date],
    fills: pd.DataFrame,
    *,
    fast: int,
    slow: int,
    title: str,
) -> Figure:
    """Draw the price, its two moving averages and what the run did about them.

    Parameters
    ----------
    averages : pd.DataFrame
        Le résultat de :func:`moving_averages`, réduit à la période à dessiner.
    held : Collection[date]
        Les séances à la clôture desquelles le run détenait l'instrument.
    fills : pd.DataFrame
        Les exécutions du run : colonnes ``session_date`` et ``side``.
    fast, slow : int
        Longueurs des deux moyennes, pour la légende.
    title : str
        Ce que la figure montre.

    Returns
    -------
    Figure
        Le prix, la moyenne rapide et la lente ; un fond coloré sur les séances
        investies ; une croix sur le prix, verte à chaque achat et rouge à chaque vente.

    Raises
    ------
    ValueError
        Si ``averages`` ne contient aucune séance.

    Notes
    -----
    Les courbes expliquent, elles ne décident pas : le fond et les croix
    viennent du run lui-même. Un ordre est exécuté à l'ouverture qui suit le
    croisement, donc une croix tombe une séance après lui.
    """
    if len(averages) == 0:
        raise ValueError("there is nothing to draw: the averages hold no session")
    days = list(averages.index)
    figure = Figure(figsize=(11, 5.5), layout="constrained")
    axes = figure.add_subplot()
    axes.fill_between(
        days,
        0.0,
        1.0,
        where=[day in held for day in days],
        transform=axes.get_xaxis_transform(),
        color=HELD_COLOUR,
        alpha=0.10,
        linewidth=0.0,
        label="invested",
    )
    axes.plot(days, list(averages["close"]), color=PRICE_COLOUR, linewidth=0.9, label="close")
    axes.plot(days, list(averages["fast"]), color=FAST_COLOUR, linewidth=1.5, label=f"MA{fast}")
    axes.plot(days, list(averages["slow"]), color=SLOW_COLOUR, linewidth=1.5, label=f"MA{slow}")
    for side, colour in (("BUY", HELD_COLOUR), ("SELL", SELL_COLOUR)):
        traded = [day for day in fills.loc[fills["side"] == side, "session_date"] if day in days]
        prices = [float(averages.loc[day, "close"]) for day in traded]
        axes.scatter(
            traded,
            prices,
            marker="x",
            color=colour,
            s=90,
            linewidths=2.2,
            zorder=3,
            label=side.lower(),
        )
    axes.set_title(title)
    axes.set_ylabel("adjusted close")
    axes.grid(visible=True, alpha=0.25)
    axes.legend(loc="upper left", frameon=False)
    return figure


def save_figures(result: StrategyResult, directory: Path, strategy: GoldenCrossETF) -> None:
    """Save the equity, drawdown and moving-average figures of the run as PNG files.

    Parameters
    ----------
    result : StrategyResult
        Le run terminé.
    directory : Path
        Dossier de sortie, créé s'il n'existe pas.
    strategy : GoldenCrossETF
        La stratégie du run : l'instrument et les deux longueurs à dessiner.

    Notes
    -----
    Exercice MA 5. Le résultat sait dessiner ses courbes ; une figure se
    sauvegarde, elle ne s'affiche pas dans un script.

    Les moyennes de ``moving_averages.png`` sont recalculées ici sur les
    clôtures ajustées telles qu'elles sont connues après la dernière clôture du
    run, et non telles que chaque décision les voyait. Les deux coïncident pour
    un fonds sans dividende ni division ; sinon une distribution versée depuis
    déplace le niveau des prix antérieurs, pas l'ordre des deux moyennes à
    l'instant où elles ont été lues.
    """
    directory.mkdir(parents=True, exist_ok=True)
    result.plot().savefig(directory / "equity.png", dpi=FIGURE_DPI)
    result.plot_drawdown().savefig(directory / "drawdown.png", dpi=FIGURE_DPI)

    reader = result.reader.at(result.records()[-1].valuation_time)
    closes = reader.adjusted_history(strategy.instrument_id, end=result.end)
    calendar = result.reader.calendars.get(result.reader.reference_calendar_id)
    first = session_date(closes.index[0])
    sessions = [session.session_date for session in calendar.sessions(first, result.end)]
    averages = moving_averages(closes, sessions, strategy.fast_sessions, strategy.slow_sessions)
    weights = result.weights()[strategy.instrument_id]
    figure = cross_figure(
        averages.loc[result.start :],
        held={session_date(day) for day, weight in weights.items() if weight > 0},
        fills=result.fills(),
        fast=strategy.fast_sessions,
        slow=strategy.slow_sessions,
        title=f"{strategy.instrument_id}  MA{strategy.fast_sessions} / "
        f"MA{strategy.slow_sessions}  {result.start} to {result.end}",
    )
    figure.savefig(directory / "moving_averages.png", dpi=FIGURE_DPI)


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
        help="where the equity, drawdown and moving-average figures are written",
    )
    arguments = parser.parse_args(argv)

    result = build_runner(STORE).run(STRATEGY, UNIVERSE, *PERIOD)
    print_run(result)
    save_figures(result, arguments.output, STRATEGY)
    print(f"\nFigures written to {arguments.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
