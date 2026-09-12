"""Signal research: transform market data into forecasts.

A signal maps information available *strictly before* a decision timestamp to a
numeric score per instrument. Signals never see future bars and never size
positions - that is the portfolio layer's job.
"""
