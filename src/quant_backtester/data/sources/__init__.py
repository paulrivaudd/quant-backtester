"""Provider adapters: the only place in the project performing network I/O.

Each adapter returns what the provider sent, untouched. Interpreting it is the
normalizer's job, and keeping the two apart is what lets us answer "is this
wrong because the provider is wrong, or because we mangled it?".
"""
