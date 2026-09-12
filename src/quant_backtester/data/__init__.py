"""Market data access: providers, local Parquet storage, trading calendars.

Responsibilities:
- Fetch raw daily observations from one or more providers and archive each
  response immutably.
- Normalise them into two canonical schemas - ``BAR`` for traded instruments,
  ``LEVEL`` for published series - and store them as Parquet under the market
  data root.
- Expose them to the rest of the system only through a reader frozen at one
  decision instant.

Nothing downstream of this package may perform network I/O.

Three invariants hold the design together:

1. **Availability is carried by the field, not by the row.** The opening auction
   publishes the open; high, low, close and volume are only final at the close.
   A single timestamp per row would leak one or hide the other.
2. **Nothing restated is stored.** Prices are raw and unadjusted; corporate
   actions live in their own table and adjustment happens at read time, using
   only the actions knowable at the decision instant.
3. **The clean layer is derived.** It is a pure function of the raw archive, the
   committed configuration and the calendars, and can be deleted and rebuilt
   byte for byte.

This is a *stable, reproducible canonical history*, not a bitemporal
point-in-time store: it holds the currently accepted value of each observation,
not the value as it was known at every past date. Vintages remain reconstructible
from the raw archive if a revisable macro series ever makes that necessary.
"""
