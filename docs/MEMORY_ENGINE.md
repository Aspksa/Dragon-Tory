# Memory Engine v6

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

The deterministic hash embedding remains a safe fallback. Dragon Tory now also
ships FastEmbed runtime support for local multilingual semantic vectors. Semantic
mode is selected with TOORU_MEMORY_EMBEDDING_PROVIDER=fastembed; the compact
multilingual MiniLM model is the default semantic model when no model name is
provided. OpenAI-compatible embedding endpoints remain supported.

## Grey Matter / metacognition

Cognitive Core V adds a higher layer over Memory Engine without bypassing its
scope isolation or Guardian.

- hierarchical summaries use PART_OF links;
- entity aliases resolve alternate names to canonical ENTITY memory;
- causal chains use CAUSES and REQUIRES;
- uncertainty combines trust, conflicts and missing evidence;
- goal/task state uses PART_OF and DEPENDS_ON;
- ordinary recall performs typed two-hop graph expansion;
- explicit graph exploration supports up to six hops;
- source reliability is learned separately from retrieval helpfulness;
- explicit user corrections create LESSON memory;
- repeated verified procedures become SKILL candidates;
- SKILL candidates are high-impact and require Guardian review;
- the maintenance daemon runs a non-duplicating Grey Matter sleep cycle.

## Truth Engine

Version 00.00.31 adds a deterministic trust assessment for each durable memory.
The score combines memory confidence, evidence confidence, feedback, temporal
status, SUPPORTS links, learned source reliability and a penalty for
CONTRADICTS links. It is intended as
an explainable retrieval signal, not as an absolute claim that a fact is true.

Graph-assisted retrieval expands lexical/semantic candidates through typed
memory relationships. Cognitive Core V performs a decayed two-hop expansion in
ordinary recall, while explicit Grey Matter traversal can go deeper.

`GET /v1/memory/{memory_id}/truth` returns the complete assessment.

## Temporal truth

Memory records can now distinguish four clocks:

- `observed_at` — when Dragon Tory learned the fact;
- `event_at` — when the described event happened;
- `valid_from` — when the fact became true;
- `valid_to` — when the fact stopped being true.

This prevents a newer fact from erasing the historical period in which an older fact was correct.

## Evidence and provenance

Each durable memory can have zero or more evidence records with source type, source reference, document id, page, excerpt, extraction method and confidence.
Structured Memory Intake attaches provenance automatically when a source reference is available. Chat outcome episodes attach the originating chat as evidence.

`GET /v1/memory/{memory_id}/evidence` returns evidence.
`POST /v1/memory/{memory_id}/evidence` adds local evidence.

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
entity, note, instruction, relationship, summary, skill and lesson.


## AI Context Builder

POST /v1/memory/context builds a bounded context pack for DeepSeek.

The builder:
- recalls personal memory separately from project memory;
- never searches another project's memory;
- always includes pinned memories for the selected scope;
- deduplicates memories that appear in both pinned and semantic results;
- respects a maximum character budget;
- labels memory kinds and relevance scores;
- marks kind=instruction as behavioral instructions;
- exposes reviewed kind=skill records as reusable procedures that cannot
  override instructions or system policy.

This is the bridge between long-term memory and the future AI Router. The
models receive selected context instead of the whole database.
