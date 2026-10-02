# Cognitive Core IX — Self-Diagnostics & Machine Report

Project version: **00.00.39**

Cognitive Core IX adds a support-grade diagnostic surface on top of Cognitive
Core VIII. The goal is to make failures reproducible without exposing private
document bodies, chat transcripts, API secrets or hidden reasoning.

## 1. Machine-readable report

Settings contains **«Скачать полный отчёт JSON»**. The backend builds a fresh
snapshot at download time:

- `GET /v1/settings/system-report` — JSON preview/API;
- `GET /v1/settings/system-report/download` — attachment download.

Schema: `dragon-tory.machine-report.v1`.

The report includes:

- project/version/release and module registry;
- runtime/Python/OS/SQLite and database sizes;
- Tesseract/LibreOffice availability and document-parser package versions;
- implementation map with the repository files responsible for each pipeline;
- sanitized configuration and DeepSeek runtime counters;
- chat counts and active request count;
- document storage totals and per-document technical state;
- document AI Contract, current local analysis metadata, warnings,
  provenance and activity;
- Memory Engine deep health;
- Memory Automation and Memory Guardian queues/status;
- Grey Matter capability map;
- current Chain/Hybrid/Tree config and learned cognition policy;
- recent reasoning outcome metadata (never chain-of-thought);
- Cognitive Core status, proactive insights and typed graph statistics;
- observability summary, recent events and failures;
- update state/history;
- derived `diagnostic_findings`.

## 2. Document study states

Each active document in the report receives one of:

- `studied` — chat study completed, including durable memory path;
- `degraded` — local extraction/index succeeded but optional DeepSeek study
  reported an error;
- `failed` — fatal chat-document study failed;
- `analyzed` — Document Intelligence exists, but there is no completed
  chat-study provenance;
- `pending` — current version has no Document Intelligence result.

A fatal chat-study error now writes
`chat_document_study_failed` to document provenance and an
`chat_document_study` error event to observability. The original uploaded
file remains available. If cognition automation is enabled, a debounced cycle
is triggered so local analysis can be retried independently.

## 3. Diagnostic findings

The report derives high-signal findings without making autonomous external
changes. Current findings include:

- DeepSeek not configured/registered or last runtime AI error;
- Memory health warning/error;
- Guardian dead-letter queue;
- Memory/Guardian/Cognition automation failures;
- fatal/degraded/pending document-study counts;
- recent observability errors, blocks or interrupted work;
- report sections that could not be collected;
- missing OCR/legacy Office engines when those document paths may need them.

Every detailed subsystem section remains available even if another section
fails. Report generation is deliberately best-effort: a broken module should
become evidence in the report, not prevent the report itself from downloading.

## 4. Privacy and safety

The machine report is designed for technical support and deliberately excludes:

- API keys, tokens, passwords, cookies and authorization headers;
- complete document body text;
- chat message bodies;
- prompts and system prompts;
- hidden chain-of-thought;
- raw extracted text/excerpts.

The report can still contain technical identifiers needed for diagnosis:
document IDs and names, technical warning text, vehicle/counterparty identifiers
that appear in warnings, local error messages and data-path metadata.

## 5. Reasoning and Grey Matter transparency

The report describes **how** the cognitive pipeline is configured and what
outcomes it produced, but not private internal reasoning traces.

It exports:

- Chain/Hybrid/Tree thresholds;
- learned bounded reasoning policy;
- technical outcome metrics such as mode, verifier score, uncertainty,
  escalation, AI call count and duration;
- Grey Matter capability map: entities, hierarchy, causality, uncertainty,
  multi-hop, truth calibration, contradiction clusters, adaptive forgetting,
  consolidation, goals/tasks and skills;
- cognition graph counts by node/edge type.

It does **not** export the hidden reasoning used to form a particular answer.

## 6. Intended support workflow

1. Reproduce the document/chat issue.
2. Open **Настройки**.
3. Download the machine-readable JSON report.
4. Attach the JSON to a support/debugging chat.
5. Diagnose by `diagnostic_findings`, then inspect the affected document
   record, provenance, observability trace, Guardian/Memory state and AI
   runtime counters.
6. Fix the cause while preserving original documents and memory separation.
