# Dragon Tory architecture — Ver 00.00.02

## Core rule

Memory belongs to Dragon Tory, not to Claude or DeepSeek.

AI providers are replaceable. Personal and project memory must remain persistent and isolated when providers change.

## Initial layers

1. **API** — FastAPI backend shared by desktop, web and mobile clients.
2. **Memory Engine** — persistent, versioned personal/project memory.
3. **AI Router** — provider-independent routing layer.
4. **Tool Registry** — controlled tools with permissions.
5. **Web UI** — desktop/browser interface.
6. **Mobile clients** — Android/iOS and later project-specific applications.

## Memory Engine v2

Memory is isolated by three dimensions:

- `owner_id` — owner/account namespace;
- `scope` — `personal` or `project`;
- `project_id` — required only for project memory.

Each memory also has a semantic role:

- fact;
- preference;
- decision;
- task;
- event;
- note;
- instruction;
- relationship;
- summary.

Retrieval can rank by importance, confidence and recency. Tags and source metadata are preserved for later semantic retrieval and auditing.

### Multi-device safety

Memory has revision numbers and soft-deletion tombstones. This allows PC and mobile applications to synchronize deltas without losing newer data.

`client_mutation_id` makes create operations idempotent, so a mobile retry cannot create duplicates.

Updates use optimistic concurrency. If a device tries to modify an old revision, the API returns a conflict instead of overwriting newer memory.

### Next memory upgrades

The API is intentionally independent of the retrieval implementation. Planned upgrades can be added without changing Claude/DeepSeek integrations:

- embeddings for semantic recall;
- vector index;
- reranking;
- automatic memory extraction from conversations;
- memory consolidation and summaries;
- duplicate detection;
- contradiction detection;
- relationship graph;
- retention/archival policies;
- encrypted cloud synchronization.

## AI routing

`AIRouter` does not own memory. It only invokes registered providers.

Planned providers:
- DeepSeek V4 Flash — default economical model.
- Claude — advanced reasoning, architecture and review.

No AI API secrets are committed to Git.

## Mobile boundary

Mobile apps use the backend API. They do not receive Claude/DeepSeek credentials and do not access the central database directly.

Before remote/mobile access is enabled, Dragon Tory must add authentication, TLS and authenticated `owner_id` resolution.
