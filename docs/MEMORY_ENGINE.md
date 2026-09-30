# Memory Engine v3

Memory is a first-class subsystem of Dragon Tory. Claude and DeepSeek consume
memory, but neither provider owns it.

## Retrieval pipeline

1. Enforce owner/scope/project isolation.
2. Build a query embedding.
3. Load a bounded candidate set from SQLite.
4. Compare semantic vectors.
5. Rerank using semantic similarity, lexical similarity, importance,
   confidence and recency.
6. Return the highest scoring memories to the AI context builder.

POST /v1/memory/recall exposes scores for debugging and tuning.

## Embeddings

The default hash embedder is fully offline, deterministic and dependency-free.
It keeps memory indexing functional before a paid embeddings service is chosen.

A stronger neural embedding service can later use the OpenAI-compatible
provider through environment settings without changing the memory API.

## Duplicate and contradiction handling

Exact normalized duplicates are not inserted twice.

Memories sharing the same explicit key but different content are retained.
The new memory receives contradicts and supersedes graph links to the previous
value instead of silently deleting history.

## Relationship graph

memory_links supports related, duplicate, contradicts, supersedes and
summarizes relations.

Related memories are linked automatically when semantic similarity crosses the
configured threshold.

## Conversation extraction

POST /v1/memory/extract inspects user conversation messages and creates durable
memory candidates. The first implementation is intentionally conservative and
offline. It extracts likely preferences, decisions, tasks, instructions and
facts.

The extractor is isolated from storage so a Claude/DeepSeek-backed extractor
can replace it later.

## Consolidation

POST /v1/memory/consolidate creates a durable summary from important memories
inside exactly one personal/project scope. The summary is linked to its source
memories.

## Mobile note

The existing revision, cursor and device fields remain compatible with future
mobile clients. This stage intentionally does not add remote authentication or
a central internet synchronization service.
