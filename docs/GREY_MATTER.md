# Grey Matter 01.00.00

Grey Matter is the metacognitive layer introduced in Dragon Tory 00.00.34.
It sits above Memory Engine and never bypasses scope isolation, provenance,
temporal history or Memory Guardian.

## 1. Semantic memory

Dragon Tory supports a local FastEmbed provider in addition to the deterministic
hash fallback and the existing OpenAI-compatible embedding provider.

Default semantic model:
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`

Enable it with:

`TOORU_MEMORY_EMBEDDING_PROVIDER=fastembed`

The first semantic-mode start can download the model into the configured cache.
Changing provider/model automatically makes existing vector rows stale and the
normal memory backfill reindexes them.

## 2. Hierarchical memory

Consolidated summaries are linked to their source memories. Grey Matter adds
`PART_OF` edges so facts, episodes, tasks and lessons can be traversed from
detail to higher-level context without deleting the originals.

## 3. Entity resolution

ENTITY memories can have canonical aliases. Entity aliases are isolated by:

- owner;
- personal/project scope;
- project id.

`SAME_ENTITY` links can connect equivalent memories while preserving both
records and their provenance.

## 4. Causal memory

Grey Matter can store:

cause → problem → required action → result

using typed `CAUSES` and `REQUIRES` links. The components are still normal
durable memories and pass through Memory Intake / Guardian.

## 5. Uncertainty Engine

Uncertainty is not the inverse of confidence alone. It incorporates the Truth
Engine result, conflicting memories and evidence availability. The API returns
a low/medium/high uncertainty level plus competing facts.

## 6. Sleep consolidation

The existing maintenance daemon continues to decide when a new summary is due.
Grey Matter then performs a non-duplicating background pass that reinforces
entity/hierarchy structure and metacognitive signals.

## 7. Goal and task memory

GOAL and TASK memories can be connected through `PART_OF`. Tasks can be marked
open/done/blocked and can depend on other tasks through `DEPENDS_ON`.
Goal progress distinguishes executable tasks from dependency-blocked tasks.

## 8. Multi-hop retrieval

Normal hybrid recall expands typed graph candidates to two hops with decay.
The explicit Grey Matter graph endpoint can traverse up to six hops while
enforcing owner/scope/project boundaries.

## 9. Source reliability

Source reliability is stored separately from retrieval helpfulness. Explicit
confirmation/contradiction feedback updates a Bayesian-style smoothed reliability
score. Truth Engine blends this score into trust assessment.

## 10. Correction learning

Explicit user corrections can become LESSON memory. Automatic chat correction
learning records the previous answer and the user's correction but does not
silently overwrite a specific factual memory. A targeted correction endpoint is
available when the exact memory id is known; high-impact corrections still pass
Guardian.

## 11. Counterfactual verifier

Result Verifier now returns:

- alternative explanations;
- counterfactual checks;
- explicit uncertainty.

The verifier is instructed to test whether its conclusion changes if a central
assumption is false.

## 12. Skill memory

Repeated verified outcomes can produce SKILL candidates. Skills are separate
from raw facts and from direct behavioral INSTRUCTION memory. SKILL is treated
as high impact and requires Guardian review before becoming durable.

## Main API

- `GET /v1/memory/grey-matter/status`
- `POST /v1/memory/grey-matter/entities/resolve`
- `POST /v1/memory/grey-matter/entities/{memory_id}/aliases`
- `POST /v1/memory/grey-matter/causal-chain`
- `POST /v1/memory/grey-matter/goals/{goal_id}/tasks/{task_id}`
- `POST /v1/memory/grey-matter/tasks/{task_id}/depends-on/{dependency_id}`
- `POST /v1/memory/grey-matter/tasks/{task_id}/state`
- `GET /v1/memory/grey-matter/goals/{goal_id}/progress`
- `POST /v1/memory/grey-matter/corrections/{memory_id}`
- `POST /v1/memory/grey-matter/sources/{memory_id}/feedback`
- `POST /v1/memory/grey-matter/consolidate`
- `GET /v1/memory/{memory_id}/uncertainty`
- `GET /v1/memory/{memory_id}/multi-hop`

## Safety invariants

- personal and project memory never share aliases or graph traversal;
- graph traversal rejects cross-scope items;
- pinned memories remain protected;
- learned skills require Guardian review;
- explicit corrections do not silently rewrite a fact unless the target memory
  is known and the correction passes Guardian;
- original episodes, documents and revisions remain auditable.
