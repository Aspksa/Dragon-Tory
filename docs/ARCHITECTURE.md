# Dragon Tory architecture

## Core rule

Memory belongs to Dragon Tory, not to the external DeepSeek service.

AI providers are replaceable. Personal and project memory remain persistent
and isolated when providers change.

## Layers

1. API — FastAPI backend.
2. Memory Engine v5 — structured, versioned, self-maintaining long-term memory with FTS5 hybrid retrieval.
3. Memory Intelligence — decides what deserves durable memory.
4. Tooru Memory Guardian — hidden risk/policy controller for automatic memory writes.
5. AI provider registry — internal DeepSeek connection layer.
6. Tool Registry — controlled tools with permissions.
7. Web UI — desktop/browser interface.
8. Mobile clients — planned clients using the same backend contracts.

## Memory Engine v5.1 / Cognitive Core II

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
