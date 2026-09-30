# Dragon Tory architecture — Ver 00.00.02

## Core rule

Memory belongs to Dragon Tory, not to Claude or DeepSeek.

AI providers are replaceable. Personal and project memory must remain persistent
and isolated when providers change.

## Layers

1. API — FastAPI backend.
2. Memory Engine v3 — structured, versioned, searchable long-term memory.
3. AI Router — provider-independent routing layer.
4. Tool Registry — controlled tools with permissions.
5. Web UI — desktop/browser interface.
6. Mobile clients — planned clients using the same backend contracts.

## Memory Engine v3

Isolation dimensions are owner_id, scope and project_id.

Memory kinds are fact, preference, decision, task, event, note, instruction,
relationship and summary.

Memory intelligence now includes embeddings, a persistent vector index, hybrid
semantic/lexical recall, reranking, conversation extraction, exact duplicate
prevention, contradiction tracking, a relation graph, automatic summaries and
revision-aware multi-device records.

See docs/MEMORY_ENGINE.md.

## AI routing

AIRouter does not own memory. It only invokes registered providers.

Planned providers:
- DeepSeek V4 Flash — default economical model.
- Claude — advanced reasoning, architecture and review.

No AI API secrets are committed to Git.

## Deliberately deferred

Remote user authentication and a central mobile synchronization service are
not part of this stage.
