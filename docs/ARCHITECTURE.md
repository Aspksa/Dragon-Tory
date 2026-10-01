# Dragon Tory architecture

## Core rule

Memory belongs to Dragon Tory, not to the external DeepSeek service.

AI providers are replaceable. Personal and project memory remain persistent
and isolated when providers change.

## Layers

1. API — FastAPI backend.
2. Memory Engine v6 — structured, versioned, self-maintaining long-term memory with hybrid semantic/lexical/graph retrieval.
3. Memory Intelligence — decides what deserves durable memory.
4. Tooru Memory Guardian — hidden risk/policy controller for automatic memory writes.
5. AI provider registry — internal DeepSeek connection layer.
6. Tool Registry — controlled tools with permissions.
7. Web UI — desktop/browser interface.
8. Mobile clients — planned clients using the same backend contracts.

## Memory Engine v6 / Cognitive Core V

Capabilities:
- hybrid semantic and lexical recall;
- persistent embeddings index;
- importance, confidence, recency and usage ranking;
- pinning and expiry;
- active, archived and superseded lifecycle;
- exact and near-duplicate prevention;
- contradiction and supersession tracking;
- relation graph;
- automatic conversation extraction;
- automatic summaries;
- full revision snapshots;
- recall reinforcement from usage and feedback;
- scheduled local maintenance.

Additional cognitive layers:

- Working Memory — recent chat window plus persistent rolling summary.
- Episodic Memory — successful task/result episodes.
- Temporal Truth — observed/event/validity timestamps.
- Provenance — evidence records linked to durable memory.
- Truth Engine — explainable confidence/evidence/temporal/conflict assessment.
- Graph Retrieval — one-hop expansion over typed memory relationships.
- Temporal Conflict Resolver — distinguishes contradiction from succession in time.
- Reasoning Planner — creates a bounded execution plan for complex chat tasks.
- Result Verifier — checks the answer against the task, plan and available context.
- Experience Learning — proposes reusable rules only from repeated verified outcomes.
- Guardian Gate — learned rules remain high-impact candidates until reviewed.
- Grey Matter — metacognitive layer above Memory Engine.
- Semantic Memory — optional local multilingual FastEmbed vectors.
- Entity Resolution — canonical entities plus aliases and SAME_ENTITY links.
- Causal Memory — typed CAUSES / REQUIRES chains.
- Uncertainty Engine — explicit uncertainty and competing facts.
- Hierarchical Memory — summary/PART_OF hierarchy.
- Goal Graph — GOAL/TASK progress and DEPENDS_ON dependencies.
- Multi-hop Retrieval — typed graph traversal beyond direct neighbors.
- Source Reliability — learned source reputation integrated into Truth Engine.
- Correction Learning — LESSON memory from user corrections.
- Counterfactual Verification — alternative explanations and assumption checks.
- Skill Memory — reviewed reusable procedures learned from verified outcomes.

See docs/MEMORY_ENGINE.md.

## AI provider

AIRouter does not own memory. It is now a small internal provider registry.

Dragon Tory uses one cloud model:
- DeepSeek V4 Flash — the only configured chat and memory AI provider.

Important memory is checked with a second independent DeepSeek pass.

## Deliberately deferred

Remote user authentication and a central mobile synchronization service are
not part of this stage.


## Memory write path

The preferred memory mutation path is:

Chat Pipeline → Memory Guardian → Memory Intelligence → Memory Engine.

Guardian is responsible for risk classification, reviewer requirements,
protection of pinned memories, and audit logging. Direct Memory Intelligence
endpoints remain useful for diagnostics and development.
