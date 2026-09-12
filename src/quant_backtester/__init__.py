"""A daily-frequency, look-ahead-safe backtesting framework.

Layers, in dependency order:

    data -> signals -> portfolio -> execution -> backtest -> analytics

`strategies` composes the layers above into runnable research configurations.
Each layer depends only on the ones before it.
"""

__version__ = "0.1.0"
