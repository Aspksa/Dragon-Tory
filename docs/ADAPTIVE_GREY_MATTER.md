# Adaptive Grey Matter 02.00.00

Dragon Tory 00.00.35 adds an adaptive layer above Grey Matter. The goal is to
improve retrieval quality and metacognitive reliability without weakening scope
isolation, Guardian, provenance or audit history.

## Adaptive retrieval

MemorySearch supports auto, balanced, lexical, semantic, graph, temporal and causal modes.
AUTO selects a strategy from the query shape. Exact identifiers prefer lexical
retrieval, causal questions emphasize CAUSES/REQUIRES/DEPENDS_ON, temporal
questions emphasize temporal/supersession links and truth-at-time, and broad
meaning queries emphasize semantic similarity.

Each MemoryRecallHit exposes the strategy actually used.

## Historical truth

MemorySearch accepts an optional as_of ISO-8601 timestamp. Temporal truth is
evaluated at that time instead of only at the current moment.

## Confidence calibration

Explicit truth feedback stores predicted trust before feedback, the confirmed
or rejected outcome, and timestamp. Grey Matter reports Brier score, expected
calibration error and calibration buckets.

## Contradiction clusters

CONTRADICTS links are grouped into connected components. Each cluster contains
competing memories, lifecycle status and trust scores. Superseded facts remain
visible as historical evidence.

## Temporal causality

CAUSES links can be created only when known event timestamps do not put the
cause after the effect. Confirmation increases causal weight; rejection lowers it.

## Guardian entity merge

Entity identity changes use proposal -> Guardian review -> finalize. Finalization
adds SAME_ENTITY and a canonical alias only after the matching Guardian queue item
is applied. Original entity memories remain auditable.

## Adaptive forgetting

Pinned memory and fact/preference/decision/goal/entity/instruction/skill kinds are
protected. Safe low-impact memories can be reinforced, gradually weakened, or
archived when very old and low-value. Every archive is recorded in history.

The normal background sleep cycle runs this pass after ordinary maintenance.

## Scale benchmark

Run:

    python scripts/memory_scale_benchmark.py --corpus 10000

Supported corpus sizes are 1,000, 10,000 and 100,000. Use --provider fastembed
to test local multilingual semantic retrieval. Reports include Hit@1, Hit@5, MRR
and selected retrieval strategies.

## Main API additions

- POST /v1/memory/grey-matter/truth/{memory_id}/feedback
- GET /v1/memory/grey-matter/calibration
- GET /v1/memory/grey-matter/contradictions
- POST /v1/memory/grey-matter/entities/{canonical}/merge/{duplicate}
- POST /v1/memory/grey-matter/entities/{canonical}/merge/{duplicate}/finalize
- POST /v1/memory/grey-matter/causal/{cause}/effect/{effect}/feedback
- POST /v1/memory/grey-matter/forgetting

## Safety invariants

Adaptive logic never permits cross-project graph traversal or entity merge.
Guardian approval is mandatory before identity consolidation. Adaptive forgetting
cannot archive protected memory classes. Historical and contradictory records
remain available for audit.
