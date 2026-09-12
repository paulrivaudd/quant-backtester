"""Execution modelling: turn target positions into fills.

Owns the fill-price assumptions (e.g. next European open), slippage models and
the explicit transaction-cost model. Every cost charged to a backtest must
originate here.
"""
