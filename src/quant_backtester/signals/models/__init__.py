"""Fitted models used as signals.

Nothing here yet, and deliberately: a model brings a training window, a refit
schedule and an artifact to version, none of which can be bolted on afterwards
without putting look-ahead back in.

The first fitted model, the neural allocation, lives in ``signals.ml`` beside
``quant_backtester.ml``, which holds its training window, its artifact and its
information cutoff.
"""
