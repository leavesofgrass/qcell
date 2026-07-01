# Optimization re-scout (2026-07-01)

A follow-up to the earlier optimization scout (8 findings; the safe 3 plus the
AST cache shipped, the lower-ranked ones were never revisited). This pass
re-profiles the current engine with `benchmarks/profile_abax.py` and records
what is — and is not — still worth doing.

## Method

`py benchmarks/profile_abax.py` on the current tree: formula parse/eval
microbench, cached-AST eval, and a 50k×12 (600k-cell) CSV load, each with a
cProfile cumulative breakdown.

## Findings

| # | Area | Verdict | Notes |
|---|------|---------|-------|
| 1 | **Bulk-load anchor rescan** | **FIXED this pass** | The new spill engine added a second full pass (`_rebuild_anchor_cells`) over every cell on `set_cells_bulk` — ~12% of a 600k-cell CSV load, and pure overhead for literal-only data. Folded the anchor detection into the existing bulk loop (same rule as `set_cell`). Bulk load dropped ~120 ms. |
| 2 | Tokenizer (43% of the full parse pipeline) | Not worthwhile | Real recalc never re-tokenizes — the parsed AST is cached per cell (original scout finding #1, shipped). Tokenization only runs on a formula *edit*, which is not a hot path. Optimizing it trades risk for no user-visible win. |
| 3 | Parser recursive-descent chain (comparison→…→primary, 6 call levels even for a bare number) | Not worthwhile | Also AST-cached. A precedence-climbing rewrite would flatten the chain but is a high-risk change to a correct, well-tested parser for a path that runs once per edit. |
| 4 | Cached-AST eval (~9.7 µs/op) | Already optimal | The `evaluate` isinstance chain is already ordered by node frequency (documented in `evaluator.py`); a dict dispatch was measured slower. `_lazy_if` overhead is inherent to lazy `IF`. No safe win left. |
| 5 | `Cell` object per literal (≈199 bytes/cell) | Not worthwhile now | `Cell` already uses `__slots__`. Storing bare literals without a `Cell` wrapper would cut memory but is a large, invasive change to the storage model with wide blast radius. Defer unless memory becomes a real constraint. |

## Conclusion

The AST cache that shipped from the first scout neutralizes the parse/tokenize
findings (2, 3) — they only matter on edit, not recalc, so they are no longer
worth the risk. The single concrete, safe win this pass was **finding #1**, a
regression the spill work introduced, now fixed and re-measured. The remaining
items (4, 5) are either already optimal or too invasive for their payoff.

No further optimizations are recommended at this time.
