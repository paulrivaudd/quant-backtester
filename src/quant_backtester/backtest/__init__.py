"""Backtest engine: the event loop that ties the layers together.

Walks the trading calendar one decision point at a time, calling data ->
signals -> portfolio -> execution, and records the resulting state. The engine
is the single place allowed to advance time.
"""
