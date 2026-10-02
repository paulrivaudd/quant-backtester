"""Exercice « Moving-Average Crossover » : une stratégie mono-ETF MM50 / MM200.

Squelette de l'exercice ``exercice_moving_average_crossover.pdf`` (étape 3).
Les corps lèvent ``NotImplementedError`` : à vous de les écrire, dans l'ordre
2.1 (le signal), 3.1 (le contrat), 3.2 (la décision), puis 3.3 (l'export dans
``strategies/examples/__init__.py`` et ``strategies/__init__.py``).

À l'étape 3.3, un test existant vous attend : une stratégie exportée par le
paquet doit aussi figurer dans la liste ``runnable`` de
``tests/strategies/test_examples.py::test_every_strategy_this_package_exports_can_be_run_as_it_stands``,
qui vérifie qu'elle déclare tout ce qu'elle lit. Lisez ce test pour choisir des
longueurs que son marché de dix séances peut servir.

Les tests sont dans ``tests/strategies/test_golden_cross_etf.py``. Ils sont
sautés (``pytest.skip("Exercice MA …")``) : retirez le ``skip`` d'un test quand
la partie qu'il vérifie est écrite, puis lancez
``uv run pytest tests/strategies/test_golden_cross_etf.py``.

Rappel du cahier des charges (§1.2 et §1.3) :

- signal ``s_t = MA50(t) / MA200(t) - 1``, calculé après la clôture de ``t`` ;
- poids cible de l'ETF ``1`` si ``s_t > 0``, ``0`` si ``s_t <= 0`` ou si le
  signal est indisponible ; le reste est du cash ;
- la cible est exécutée à l'ouverture suivante, par le moteur et non par vous.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.base import Signal
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.price.trend import MovingAverageCrossSignal
from quant_backtester.signals.types import PriceBasis, SignalStatus, require_identifier
from quant_backtester.strategies.base import Strategy


@dataclass(frozen=True, slots=True)
class GoldenCrossETF(Strategy):
    """Détenir un ETF tant que sa moyenne mobile rapide est au-dessus de la lente.

    Attributes
    ----------
    instrument_id : str
        L'ETF étudié.
    fast_sessions : int
        Longueur de la moyenne rapide, en séances.
    slow_sessions : int
        Longueur de la moyenne lente, en séances.
    strategy_id : str
        Nom sous lequel la configuration est enregistrée.

    Notes
    -----
    Exercice MA 3.1. Le contrat minimum est fixé par l'énoncé ; les champs
    ci-dessus en sont la transcription. Demandez-vous ce qui doit être refusé à
    la construction (un nom vide, des longueurs incohérentes…) et où ce contrôle
    est déjà fait dans le projet.
    """

    instrument_id: str = "ETF_WORLD"
    fast_sessions: int = 50
    slow_sessions: int = 200
    strategy_id: str = "golden_cross_etf"

    def __post_init__(self) -> None:
        """Reject a configuration that cannot be computed."""
        require_identifier(self.instrument_id, "instrument_id")
        require_identifier(self.strategy_id, "strategy_id")
        # The signal refuses an average of one price and two equal lengths;
        # building it here is how those rules are applied without a copy.
        self.signal()
        # The signal takes either order. The names of this strategy do not: a
        # "fast" average longer than the "slow" one holds the fund in a
        # downtrend while being recorded as a golden cross.
        if self.fast_sessions > self.slow_sessions:
            raise ValueError(
                f"fast_sessions ({self.fast_sessions}) must be below slow_sessions "
                f"({self.slow_sessions})"
            )

    def signal(self) -> MovingAverageCrossSignal:
        """Return the signal this strategy reads.

        Returns
        -------
        MovingAverageCrossSignal
            ``ma50_over_ma200`` : moyenne rapide sur moyenne lente, moins 1.

        Notes
        -----
        Exercice MA 2.1. Configurez le signal existant, ne recopiez pas sa
        formule. L'énoncé fixe l'identifiant, les deux longueurs, la base de
        prix et le champ. Relisez la docstring de ``MovingAverageCrossSignal``
        (``signals/price/trend.py``) pour l'ordre des deux longueurs.
        """
        return MovingAverageCrossSignal(
            signal_id=f"ma{self.fast_sessions}_over_ma{self.slow_sessions}",
            first_sessions=self.fast_sessions,
            second_sessions=self.slow_sessions,
            price_basis=PriceBasis.ADJUSTED,
        )

    def required_signals(self) -> Sequence[Signal | SignalRequest]:
        """Return the signals the engine computes before each decision.

        Returns
        -------
        Sequence[Signal | SignalRequest]
            Le signal de :meth:`signal`, calculé sur l'ETF étudié seulement.

        Notes
        -----
        Exercice MA 3.1. Un ``Signal`` nu est calculé sur tout l'univers de
        trading ; l'énoncé demande de restreindre le calcul à l'ETF étudié.
        Voir ``SignalRequest`` dans ``signals/engine.py``.
        """
        return (SignalRequest(signal=self.signal(), instruments=(self.instrument_id,)),)

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Return the target for the next open.

        Parameters
        ----------
        ctx : StrategyContext
            Tout ce que la décision peut voir, figé à l'instant de décision.

        Returns
        -------
        TargetAllocation
            100 % de l'ETF, ou 100 % cash.

        Notes
        -----
        Exercice MA 3.2. Trois cas, dans l'ordre de l'énoncé. Le statut du
        signal se lit avant sa valeur : pourquoi ? (question 2.2.4). Le contexte
        sait lire un signal, son statut, et construire une cible investie ou
        vide ; voir ``backtest/context.py``. Ni fichier, ni calendrier, ni
        historique : tout ce dont la décision a besoin est dans ``ctx``.
        """
        signal_id = self.signal().signal_id
        if ctx.signal_status(signal_id, self.instrument_id) is not SignalStatus.OK:
            return ctx.cash()
        if ctx.signal_value(signal_id, self.instrument_id) <= 0:
            return ctx.cash()
        return ctx.weights({self.instrument_id: 1.0})
