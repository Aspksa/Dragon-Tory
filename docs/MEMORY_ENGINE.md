# Memory Engine v5

Dragon Tory owns its memory. DeepSeek is the configured reasoning provider,
but it does not own long-term memory.

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

Retrieval now has independent candidate channels. SQLite FTS5 retrieves textual
matches without first requiring them to appear in the importance/recency window.
Those candidates are merged with the broader semantic candidate set and then
ranked by semantic similarity, lexical overlap, importance, confidence, recency,
usage feedback and pinning.

The default hash embedding remains an offline deterministic fallback. A real
OpenAI-compatible embedding endpoint can be configured when stronger semantic
similarity is required.

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


## AI Context Builder

POST /v1/memory/context builds a bounded context pack for DeepSeek.

The builder:
- recalls personal memory separately from project memory;
- never searches another project's memory;
- always includes pinned memories for the selected scope;
- deduplicates memories that appear in both pinned and semantic results;
- respects a maximum character budget;
- labels memory kinds and relevance scores;
- marks only kind=instruction records as behavioral instructions.

This is the bridge between long-term memory and the future AI Router. The
models receive selected context instead of the whole database.
