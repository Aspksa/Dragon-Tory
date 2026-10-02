# Cognitive Core VIII — Adaptive Learning & Proactive Intelligence

Project version: **00.00.38**

Cognitive Core VIII closes the loop around the existing Adaptive Reasoning
Router. Dragon Tory no longer only chooses Chain, Tree or Hybrid for one
request: it records outcome metadata, evaluates its own readiness, learns a
bounded routing policy from verified outcomes, maintains a typed work graph
and periodically looks for evidence-backed anomalies.

## Architecture

The cognition layer is deliberately separated from long-term user memory.

- `data/cognition/tooru_cognition.sqlite3` stores reasoning outcomes,
  bounded policy history, work-graph snapshots, proactive insights and
  automation state.
- `data/memory/tooru_memory.sqlite3` remains the source of personal/project
  semantic memory and Guardian-reviewed lessons.
- `data/cloud/tooru_cloud.sqlite3` remains the source of documents, garage,
  counterparties, employees, document DNA and document intelligence.
- Observability records only technical cognition events and IDs, not hidden
  reasoning traces.

This separation prevents technical learning statistics from polluting the
user's factual memory.

## 1. Self-learning Reasoning Router

Each completed chat can save:

- task bucket;
- selected Chain / Hybrid / Tree mode;
- complexity;
- memory uncertainty;
- contradiction count;
- Result Verifier score and uncertainty;
- whether the route escalated;
- approximate number of AI calls;
- end-to-end duration;
- optional later user feedback.

The original task and hidden chain-of-thought are **not** stored in cognition
experience rows.

### Bounded policy learning

The policy does not edit source code. It can only tune a small set of numeric
thresholds inside hard safety bounds:

- Hybrid complexity: 0.30–0.60;
- Tree complexity: 0.60–0.88;
- Hybrid uncertainty: 0.20–0.50;
- Tree uncertainty: 0.40–0.75;
- verifier escalation score: 0.72–0.92;
- verifier uncertainty threshold: 0.20–0.55.

Automatic adaptation waits for at least 24 verified/feedback-bearing episodes.
One cycle changes thresholds only in small steps. Every policy version is
persisted in history and can be audited.

## 2. Metacognitive Control

Before the main answer Dragon Tory estimates:

- evidence coverage from memory and document matches;
- current uncertainty;
- contradiction pressure;
- complexity-dependent evidence need;
- readiness to answer.

A simple low-complexity message is not escalated merely because no memory was
found. A complex task with weak evidence, high uncertainty or multiple
contradictions can be promoted automatically from Chain to Hybrid or Tree.

After Result Verifier, the same metacognitive layer evaluates the result again.
A weak verified result can trigger one bounded Tree escalation and a second
verification.

## 3. Work graph

The cognition graph is rebuilt from local structured sources and currently
supports typed nodes for:

- people;
- vehicles;
- documents;
- companies/counterparties;
- parts and material lines detected in indexed document chunks;
- work/service lines;
- money;
- events.

Edges include, among others:

- DRIVES;
- INVOLVES_COMPANY;
- MENTIONS_COMPANY;
- INVOLVES_PERSON;
- REFERENCES_VEHICLE;
- HAS_AMOUNT;
- HAS_EVENT;
- DESCRIBES_PART;
- DESCRIBES_WORK;
- existing SmartDrive document relations.

Unknown VINs are not automatically treated as errors. This is intentional:
parts and services can refer to equipment outside the user's garage.

## 4. “Тоору сама заметила”

The proactive scanner creates evidence-backed, deduplicated insights. Each
insight has a rule ID, severity, confidence, evidence, related entity IDs and a
lifecycle:

`open → acknowledged → resolved`

or

`open → dismissed`

Dismissed insights stay dismissed for the same fingerprint. A resolved insight
can reopen if the same condition later returns.

Current local detectors include:

- duplicate VIN/plate identities in active garage cards;
- expired or soon-expiring insurance;
- warnings produced by Document Intelligence v2;
- counterparty mismatch between document DNA and extracted text;
- past document deadlines;
- service memos that contain request/action language and have no linked
  continuation after 12 days;
- plain invoices with no found contract for the same counterparty (LOW
  severity because the invoice may legitimately stand alone);
- duplicate document numbers;
- frequent repair documents for the same VIN in a 90-day window;
- unusually high document totals relative to similar documents;
- large changes in repeated part/work line amounts. These are explicitly
  described as line-amount signals, not proof of unit-price changes.

## 5. Learning from corrections

If the user explicitly corrects the previous assistant answer, the correction
can become a project `LESSON` candidate. It is never written directly to
durable memory: it goes through Memory Guardian using the structured intake
path.

## 6. Automatic cycle

`CognitionAutomation` runs locally in the background. Default interval:
15 minutes.

One cycle:

1. evaluates whether enough verified reasoning outcomes exist to adapt policy;
2. rebuilds the typed work graph;
3. runs proactive detectors;
4. resolves stale automatic insights whose condition disappeared;
5. records cycle state and observability metadata.

The first cycle starts shortly after application startup and never requires a
manual Chain/Tree/Hybrid button.

Environment controls:

- `TOORU_COGNITION_AUTOMATION_ENABLED=true`
- `TOORU_COGNITION_INTERVAL_SECONDS=900`

## 7. API

Read-only/state endpoints:

- `GET /v1/cognition/status`
- `GET /v1/cognition/policy`
- `GET /v1/cognition/experiences`
- `GET /v1/cognition/insights`
- `GET /v1/cognition/graph`

Feedback/actions:

- `POST /v1/cognition/experiences/{id}/feedback`
- `POST /v1/cognition/insights/{id}/status`
- `POST /v1/cognition/cycle`

The reasoning mode itself remains automatic and is not user-switchable.

## 8. Safety invariants

Cognitive Core VIII must not:

- expose or store hidden chain-of-thought;
- silently rewrite Python/JavaScript/project source code as “learning”;
- bypass Memory Guardian;
- merge personal and project memory scopes;
- treat an external vehicle reference as a garage inconsistency by default;
- turn a low-confidence anomaly into an asserted fact;
- execute external side effects merely because an anomaly was detected.

It may learn bounded routing parameters, source/outcome statistics and
Guardian-reviewed lessons. Proactive findings remain evidence-bearing signals
until confirmed or resolved.
