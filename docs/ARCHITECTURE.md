# Dragon Tory architecture — Ver 00.00.02

## Core rule

Memory belongs to Dragon Tory, not to Claude or DeepSeek.

AI providers are replaceable. Personal and project memory must remain persistent and isolated when providers change.

## Initial layers

1. **API** — FastAPI backend.
2. **Memory Engine** — persistent personal/project memory.
3. **AI Router** — provider-independent routing layer.
4. **Tool Registry** — controlled tools with permissions (next stage).
5. **Web UI** — user interface (after the core API is stable).

## Memory isolation

- `personal`: global user memory; `project_id` must be null.
- `project`: memory owned by exactly one project; `project_id` is mandatory.
- The database enforces this rule with a CHECK constraint.
- Search always includes scope and project filters.

The first implementation uses SQLite because the project is intended to run locally from removable storage. Semantic embeddings, reranking and a vector index will be added behind the same memory layer without changing the public API.

## AI routing

`AIRouter` does not store memory. It only invokes registered providers.

Planned providers:
- DeepSeek V4 Flash — default economical model.
- Claude — advanced reasoning / architecture / review.

No API secrets are committed to Git.
