# Dragon Tory architecture — Ver 00.00.02

## Core rule

Memory belongs to Dragon Tory, not to Claude or DeepSeek.

AI providers are replaceable. Personal and project memory remain persistent
and isolated when providers change.

## Layers

1. API — FastAPI backend.
2. Memory Engine v4 — structured, versioned, self-maintaining long-term memory.
3. Memory Intelligence — decides what deserves durable memory.
4. Tooru Memory Guardian — hidden risk/policy controller for automatic memory writes.
5. AI Router — provider-independent routing layer.
4. Tool Registry — controlled tools with permissions.
5. Web UI — desktop/browser interface.
6. Mobile clients — planned clients using the same backend contracts.

## Memory Engine v4

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

See docs/MEMORY_ENGINE.md.

## AI routing

AIRouter does not own memory. It invokes registered providers.

Planned providers:
- DeepSeek V4 Flash — economical default model;
- Claude — advanced reasoning, architecture and review.

## Deliberately deferred

Remote user authentication and a central mobile synchronization service are
not part of this stage.


## Memory write path

The preferred memory mutation path is:

Chat Pipeline → Memory Guardian → Memory Intelligence → Memory Engine.

Guardian is responsible for risk classification, reviewer requirements,
protection of pinned memories, and audit logging. Direct Memory Intelligence
endpoints remain useful for diagnostics and development.
