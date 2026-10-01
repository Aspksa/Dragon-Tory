# Memory Intelligence Layer

Memory Intelligence sits between raw conversations and Memory Engine v4.

Its job is to decide whether information deserves durable memory before the
database is changed.

## Decision pipeline

1. Receive conversation messages plus one strict personal/project scope.
2. Retrieve only relevant existing memory from that same scope.
3. Ask the primary analyzer for structured decisions.
4. For high-impact facts, preferences, goals, instructions, decisions or
   updates, ask the reviewer when available.
5. Validate the JSON contract.
6. Reject update targets outside the active owner/scope/project.
7. Apply only validated create/update decisions.
8. Leave ignored/transient content out of long-term memory.

Default provider roles are:
- DeepSeek: primary memory analyzer;
- DeepSeek: separate second-pass reviewer for high-impact memory.

The providers are addressed through AIRouter, so the memory system itself does
not depend on either vendor.

## Safe fallback

If no AI provider is registered, or an AI call/JSON response fails, the layer
uses the conservative local extractor. This keeps Dragon Tory usable offline
and prevents a provider outage from breaking memory writes.

The fallback deliberately saves less rather than saving every sentence.

## AI contract

The analyzer returns JSON decisions with:

- action: ignore / create / update;
- durable normalized content;
- memory kind;
- stable key when useful;
- importance;
- confidence;
- tags;
- optional target_memory_id for update;
- a short reason.

AI output is treated as untrusted data and validated before use.

## Update protection

An AI-proposed target_memory_id is valid only when it belongs to the same
owner, memory scope and project as the active request. A target from another
project is never updated.

Updates use the Memory Engine revision mechanism, preserving history.

## API

POST /v1/memory/intelligence

Set auto_apply=false to inspect decisions without changing memory.

Set use_ai=false to force the local conservative analyzer.

## Current integration state

The intelligence orchestration, provider routing contract, reviewer flow,
fallback, validation and tests are implemented.

DeepSeek is the only configured cloud AI provider. Until DeepSeek is registered
with a valid local API key, the layer automatically uses the local fallback.
