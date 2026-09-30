# Tooru Memory Guardian v1

Memory Guardian is the hidden policy AI that sits above Memory Intelligence and
below the future Chat Pipeline.

The user does not chat with Guardian directly. Its role is to protect and
improve long-term memory.

## Pipeline

Conversation turn
→ Memory Intelligence
→ Guardian risk policy
→ optional Claude review
→ validated Memory Engine mutation
→ Guardian audit event

## Risk levels

- LOW — ordinary low-impact durable information; can be automated.
- MEDIUM — updates, useful tasks, relationships, or important facts; requires
  sufficient confidence.
- HIGH — critical decisions, instructions, or very important memory; requires
  reviewer confirmation before automatic application.
- PROTECTED — pinned memory targeted by an automatic update. Guardian blocks it.

## Outcomes

- ignored — not worth durable memory;
- applied — safely written to Memory Engine;
- pending — retained as an audit decision but not automatically written;
- blocked — policy refused an unsafe automatic mutation.

## Provider roles

Memory Intelligence uses AIRouter.

Default roles:
- DeepSeek — primary analyzer;
- Claude — reviewer for high-impact memory.

When those network providers are not registered, local heuristic analysis still
works. High-impact fallback decisions wait in pending instead of silently
modifying critical long-term memory.

## Protection

Pinned memory cannot be overwritten automatically by Guardian.

Memory Intelligence already protects owner/scope/project boundaries. Guardian
adds a second policy layer on top of that boundary validation.

## Audit

Every Guardian decision is persisted in memory_guardian_events with:

- owner/scope/project;
- risk;
- outcome;
- analyzer;
- reviewer;
- structured decision;
- policy reason;
- timestamp.

This supports future UI such as "Why did Tooru remember this?"

## Internal API

POST /v1/memory/guardian/process
GET  /v1/memory/guardian/status
GET  /v1/memory/guardian/events

These endpoints are currently local because Dragon Tory binds to 127.0.0.1 by
default.

## Future Chat Pipeline

The future chat pipeline should call Memory Guardian after a completed user/AI
turn. Guardian should remain hidden from the visible chat surface.

Authorization and central mobile synchronization remain deliberately deferred.


## Guardian v2: durable pending queue

HIGH-risk or low-confidence memory no longer exists only as an in-process
pending result. Guardian persists it in memory_guardian_queue.

Each queue record stores:
- owner / scope / project;
- risk;
- structured memory decision;
- source conversation messages;
- analyzer and reviewer;
- attempts and max attempts;
- next retry time;
- last error;
- timestamps.

A SHA-256 fingerprint deduplicates identical pending decisions so repeated chat
turns do not flood the review queue.

## Autonomous review worker

MemoryGuardianAutomation runs separately from ordinary MemoryAutomation.

Default cadence is 15 minutes. It only processes queue items whose retry time
is due, in a bounded batch.

Lifecycle:

pending -> reviewer retry -> applied / rejected
                     \-> retry later
                     \-> dead after max attempts

When the configured reviewer is not registered in AIRouter, the queue remains
safe and durable. It is deferred instead of being lost or applied without
review.

## Manual local control

Pending decisions can be approved or rejected through local API endpoints.

Manual approval still passes owner/scope/project validation and cannot
auto-overwrite pinned protected memory.

## Dead-letter protection

Repeated reviewer failures are bounded by max_attempts. After the limit, the
queue item becomes dead and stops consuming review attempts automatically.

## Guardian v2 API

GET  /v1/memory/guardian/queue
POST /v1/memory/guardian/queue/{queue_id}/retry
POST /v1/memory/guardian/queue/{queue_id}/approve
POST /v1/memory/guardian/queue/{queue_id}/reject

POST /v1/memory/guardian/automation/run
GET  /v1/memory/guardian/automation/status

GET  /v1/memory/guardian/status now also reports durable queue counts for
pending, applied, rejected and dead records.
