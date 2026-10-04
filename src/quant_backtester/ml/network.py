"""The network that proposes weights, and the objective it is trained on.

The network is small on purpose: one encoder shared by every series turns a
history into a few numbers, and one hidden layer combines those with the
indicators of every series. Its output is a softmax over the tradable funds
and cash: portfolio weights, positive and of sum one, not probabilities of a
rise.

No target weight is ever shown to it. It is trained on the return its own
weights would have earned from the open after the decision to the open after
that, net of a proportional cost on what it traded, less a penalty on the
variance of that return. That return is an approximation made for the
gradient - fractional shares, proportional costs, weights reached exactly at
the open - and never a result: a performance comes from the engine alone.

Everything is ``float64`` and runs on the CPU.
"""

from __future__ import annotations

import numpy as np
import torch
from numpy.typing import NDArray
from torch import Tensor, nn

from quant_backtester.ml.config import NeuralStrategyConfig
from quant_backtester.ml.features import FeatureScaler


class NeuralAllocator(nn.Module):
    """Softmax weights over the tradable funds and cash, from one input.

    Parameters
    ----------
    config : NeuralStrategyConfig
        The layout of the input and the widths of the layers.

    Notes
    -----
    ``Linear(H, E) -> Tanh`` on each series' history with shared parameters;
    then, on the encodings of every series, the indicators of every series and
    the absolute level, ``Linear(M*(E+I)+1, W) -> Tanh -> Dropout ->
    Linear(W, N+1) -> Softmax``. With ``H=100, E=8, I=6, W=16``, seven series
    and two funds, that is 2 459 parameters.
    """

    def __init__(self, config: NeuralStrategyConfig) -> None:
        super().__init__()
        self.series_count = config.series_count
        self.history_sessions = config.history_sessions
        self.block_size = config.block_size
        self.input_size = config.input_size
        combined = self.series_count * (config.encoder_width + config.indicator_count) + 1
        self.encoder = nn.Linear(config.history_sessions, config.encoder_width)
        self.hidden = nn.Linear(combined, config.hidden_width)
        self.dropout = nn.Dropout(config.dropout)
        self.output = nn.Linear(config.hidden_width, len(config.tradable_ids) + 1)
        self.double()

    def forward(self, inputs: Tensor) -> Tensor:
        """Return the proposed weights of a batch of normalised inputs.

        Parameters
        ----------
        inputs : torch.Tensor
            Normalised inputs, one per row, of ``input_size`` components.

        Returns
        -------
        torch.Tensor
            One row per input: the weight of each tradable fund, in order,
            then the weight of cash. Each row is positive and sums to one.

        Raises
        ------
        ValueError
            If the inputs do not have the width the network was built for.
        """
        if inputs.ndim != 2 or inputs.shape[1] != self.input_size:
            raise ValueError(
                f"the network reads rows of {self.input_size} components, got a tensor of "
                f"shape {tuple(inputs.shape)}"
            )
        blocks = inputs[:, :-1].reshape(-1, self.series_count, self.block_size)
        encoded = torch.tanh(self.encoder(blocks[:, :, : self.history_sessions]))
        indicators = blocks[:, :, self.history_sessions :]
        combined = torch.cat([encoded.flatten(1), indicators.flatten(1), inputs[:, -1:]], dim=1)
        hidden = self.dropout(torch.tanh(self.hidden(combined)))
        return torch.softmax(self.output(hidden), dim=1)


def capped_fund_weights(weights: Tensor, max_asset_weight: float) -> Tensor:
    """Return the fund weights of softmax outputs, each capped; cash is what is left.

    Parameters
    ----------
    weights : torch.Tensor
        Softmax outputs, funds then cash, one decision per row.
    max_asset_weight : float
        Largest weight of one fund.

    Returns
    -------
    torch.Tensor
        The fund columns, each at most the cap. What the cap removes is not
        given to the other funds.
    """
    return torch.clamp(weights[:, :-1], max=max_asset_weight)


def proxy_returns(fund_weights: Tensor, forward_returns: Tensor, cost_rate: float) -> Tensor:
    """Return the net return each decision of a sequence is credited with.

    Parameters
    ----------
    fund_weights : torch.Tensor
        Weight of each fund decided at ``t``, one decision per row, in time
        order. Cash is the complement.
    forward_returns : torch.Tensor
        ``y[t, i]``: return of fund ``i`` from the open after decision ``t``
        to the open after that. Cash returns zero.
    cost_rate : float
        Proportional cost of one euro bought or sold.

    Returns
    -------
    torch.Tensor
        ``R[t] = sum_i(w[t, i] * y[t, i]) - cost_rate * sum_i(abs(w[t, i] -
        before[t, i]))``, where ``before[t]`` is ``w[t-1]`` after it drifted
        with ``y[t-1]``, and the book before the first decision is all cash:
        the first purchase pays, and a full switch between two funds trades
        twice the capital.
    """
    drifted = (
        fund_weights
        * (1.0 + forward_returns)
        / (1.0 + (fund_weights * forward_returns).sum(dim=1, keepdim=True))
    )
    before = torch.cat([torch.zeros_like(fund_weights[:1]), drifted[:-1]], dim=0)
    traded = (fund_weights - before).abs().sum(dim=1)
    return (fund_weights * forward_returns).sum(dim=1) - cost_rate * traded


def risk_adjusted_objective(returns: Tensor, risk_aversion: float, annualization: int) -> Tensor:
    """Return ``A*mean(R) - risk_aversion/2 * A*var(R, ddof=1)``.

    Parameters
    ----------
    returns : torch.Tensor
        Per-decision or per-session returns, at least two.
    risk_aversion : float
        Weight of the variance.
    annualization : int
        Sessions per year, ``A``.

    Returns
    -------
    torch.Tensor
        The scalar the training maximises and the validation is scored by.
    """
    return annualization * returns.mean() - 0.5 * risk_aversion * annualization * returns.var(
        unbiased=True
    )


class NeuralRuntime:
    """A frozen network and its normalisation, ready to propose weights.

    Parameters
    ----------
    config : NeuralStrategyConfig
        The configuration the network was calibrated with.
    state : dict[str, torch.Tensor]
        The parameters of the network.
    scaler : FeatureScaler
        The normalisation fitted on the training inputs.

    Raises
    ------
    ValueError
        If the normalisation was not fitted on inputs of the configured width.
    RuntimeError
        If the parameters are not those of the configured architecture.

    Notes
    -----
    Built once, before a run. It holds no file and reads none: a signal that
    loaded its weights while computing would be doing I/O at a decision.
    """

    def __init__(
        self, config: NeuralStrategyConfig, state: dict[str, Tensor], scaler: FeatureScaler
    ) -> None:
        if scaler.mean.shape[0] != config.input_size:
            raise ValueError(
                f"the normalisation was fitted on {scaler.mean.shape[0]} components and the "
                f"configuration lays out {config.input_size}"
            )
        self.config = config
        self.scaler = scaler
        self.model = NeuralAllocator(config)
        self.model.load_state_dict(state, strict=True)
        self.model.eval()

    def propose(self, values: NDArray[np.float64]) -> tuple[NDArray[np.float64], int]:
        """Return the weights the network proposes for one raw input.

        Parameters
        ----------
        values : numpy.ndarray
            One input before normalisation, as the feature builder returns it.

        Returns
        -------
        tuple[numpy.ndarray, int]
            The softmax weights - funds in order, then cash - and the number
            of input components the normalisation clipped.

        Raises
        ------
        ValueError
            If the input is not of the configured width or the output is not
            finite. Neither is a market situation: the run stops rather than
            turn a broken model into a day in cash.
        """
        scaled, clipped = self.scaler.transform(np.asarray(values, dtype=np.float64))
        with torch.inference_mode():
            weights = self.model(torch.from_numpy(scaled).reshape(1, -1))[0].numpy()
        if not np.isfinite(weights).all():
            raise ValueError(f"the network returned weights that are not finite: {weights}")
        return weights.astype(np.float64), clipped
