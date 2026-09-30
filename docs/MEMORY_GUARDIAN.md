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
