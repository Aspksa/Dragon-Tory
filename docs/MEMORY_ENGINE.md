# Memory Engine v4

Dragon Tory owns its memory. Claude and DeepSeek are replaceable reasoning
providers that consume selected context; they do not own long-term memory.

## Memory lifecycle

Every record can be active, archived or superseded.

A memory can be pinned so automatic maintenance never archives it. Temporary
memories can have an expires_at timestamp. Low-value old notes, events and
episodes can be archived automatically while durable facts, decisions, goals,
preferences and instructions are preserved.

When a new keyed fact or decision replaces an older value, the older memory is
marked superseded instead of being erased. Both versions remain auditable.

## Reinforcement

Recall usage is tracked with access_count and last_accessed_at.

Applications can send helpful or unhelpful feedback. Helpful memories are
reinforced slightly; unhelpful memories are weakened slightly. Retrieval also
uses historical usage as one ranking signal.

Pinned memory receives an explicit ranking boost.

## Hybrid recall

Ranking combines semantic similarity, lexical overlap, importance, confidence,
recency, usage feedback and pinning.

## History and provenance

Every create, edit, feedback change, supersession, archive and delete writes a
revision snapshot to memory_history.

The history API makes changes auditable and prepares the engine for future
rollback tools.

## Automated maintenance

The local backend runs a safe maintenance cycle at a configurable interval.

A cycle can:
- reindex stale or missing embeddings;
- archive expired temporary memory;
- archive old low-value notes, events and episodes;
- create periodic consolidation summaries after enough new memory accumulates;
- store a maintenance report.

Maintenance does not expose the database to the internet and does not implement
mobile synchronization or authentication.

Manual trigger:
POST /v1/memory/maintenance/run

Latest in-process report:
GET /v1/memory/maintenance/latest

## Memory classes

Durable types include fact, preference, decision, task, event, episode, goal,
entity, note, instruction, relationship and summary.
