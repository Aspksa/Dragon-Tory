# Dragon Tory architecture

## Core rule

Memory belongs to Dragon Tory, not to the external DeepSeek service.

AI providers are replaceable. Personal and project memory remain persistent
and isolated when providers change.

## Layers

1. API — FastAPI backend.
2. Memory Engine v6 — structured, versioned, self-maintaining long-term memory with hybrid semantic/lexical/graph retrieval.
3. Memory Intelligence — decides what deserves durable memory.
4. Tooru Memory Guardian — hidden risk/policy controller for automatic memory writes.
5. AI provider registry — internal DeepSeek connection layer.
6. Tool Registry — controlled tools with permissions.
7. Web UI — desktop/browser interface.
8. Cognitive Core VIII — adaptive reasoning control, work graph and proactive insight engine.
9. Mobile clients — planned clients using the same backend contracts.

## Memory Engine v6 / Cognitive Core VIII

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

Additional cognitive layers:

- Working Memory — recent chat window plus persistent rolling summary.
- Episodic Memory — successful task/result episodes.
- Temporal Truth — observed/event/validity timestamps.
- Provenance — evidence records linked to durable memory.
- Truth Engine — explainable confidence/evidence/temporal/conflict assessment.
- Graph Retrieval — one-hop expansion over typed memory relationships.
- Temporal Conflict Resolver — distinguishes contradiction from succession in time.
- Reasoning Planner — creates a bounded execution plan for complex chat tasks.
- Result Verifier — checks the answer against the task, plan and available context.
- Experience Learning — proposes reusable rules only from repeated verified outcomes.
- Guardian Gate — learned rules remain high-impact candidates until reviewed.
- Grey Matter — metacognitive layer above Memory Engine.
- Semantic Memory — optional local multilingual FastEmbed vectors.
- Entity Resolution — canonical entities plus aliases and SAME_ENTITY links.
- Causal Memory — typed CAUSES / REQUIRES chains.
- Uncertainty Engine — explicit uncertainty and competing facts.
- Hierarchical Memory — summary/PART_OF hierarchy.
- Goal Graph — GOAL/TASK progress and DEPENDS_ON dependencies.
- Multi-hop Retrieval — typed graph traversal beyond direct neighbors.
- Source Reliability — learned source reputation integrated into Truth Engine.
- Correction Learning — LESSON memory from user corrections.
- Counterfactual Verification — alternative explanations and assumption checks.
- Skill Memory — reviewed reusable procedures learned from verified outcomes.
- Adaptive Retrieval — auto-selects lexical/semantic/graph/temporal/causal profiles.
- Historical Recall — evaluates truth at an optional as_of timestamp.
- Confidence Calibration — stores truth-feedback and reports Brier/ECE metrics.
- Contradiction Clusters — connected competing facts with lifecycle-aware resolution state.
- Temporal Causality — prevents CAUSES edges from pointing backward in known event time.
- Guardian Entity Merge — entity identity changes require reviewed proposal + finalize.
- Adaptive Forgetting — conservative reinforcement, decay and audited archive for safe memory kinds.
- Scale Benchmark — manual 1k/10k/100k retrieval benchmark with Hit@K and MRR.
- Adaptive Reasoning Router — automatically selects Chain, Tree or Hybrid from task complexity and memory risk.
- Chain Fast Path — simple tasks avoid Planner/Tree/Verifier overhead when unnecessary.
- Bounded Reasoning Tree — 3–5 short evidence/risk branches with a hard one-escalation limit.
- Hybrid Escalation — starts linear and invokes Tree only after low verifier score, contradictions or high uncertainty.
- Reasoning Observability — internal route is recorded without exposing a manual mode toggle.
- Adaptive Learning Policy — learns bounded routing thresholds from verified outcome metadata.
- Metacognitive Control — estimates evidence coverage, uncertainty and contradiction pressure before and after Verifier.
- Cognition Store — keeps technical learning statistics isolated from personal/project durable memory.
- Work Graph — links people, vehicles, documents, companies, parts, work, money and events.
- Proactive Insight Engine — detects evidence-backed anomalies and manages open/acknowledged/resolved/dismissed lifecycle.
- Cognition Automation — periodically adapts policy, rebuilds the work graph and scans for new anomalies.

See docs/MEMORY_ENGINE.md and docs/COGNITIVE_CORE_VIII.md.

## AI provider

AIRouter does not own memory. It is now a small internal provider registry.

Dragon Tory uses one cloud model:
- DeepSeek V4 Flash — the only configured chat and memory AI provider.

Important memory is checked with a second independent DeepSeek pass.

## Deliberately deferred

Remote user authentication and a central mobile synchronization service are
not part of this stage.


## Memory write path

The preferred memory mutation path is:

Chat Pipeline → Memory Guardian → Memory Intelligence → Memory Engine.

Guardian is responsible for risk classification, reviewer requirements,
protection of pinned memories, and audit logging. Direct Memory Intelligence
endpoints remain useful for diagnostics and development.


## Cognitive Core IX / Machine Report (00.00.39)

The local Settings surface can export a machine-readable support snapshot via
`/v1/settings/system-report/download`. The report is assembled from existing
runtime sources rather than a second shadow state: Memory health/Guardian,
Grey Matter capability contract, Adaptive Reasoning policy/outcomes, Cognitive
Core graph/insights, Cloud document metadata/provenance, Document Intelligence,
AI runtime counters, observability and update state.

Fatal chat-document study errors are persisted as
`chat_document_study_failed` provenance plus observability error events. The
original document remains stored. Report generation is best-effort per section,
so one broken subsystem becomes a diagnostic finding instead of preventing the
snapshot from downloading.

The support report never exports API credentials, chat bodies, full document
text or hidden chain-of-thought.
