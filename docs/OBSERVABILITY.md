# Dragon Tory Observability

Version target: **00.00.25**

The System Brain uses a local SQLite event journal to show how work moves through
Dragon Tory without storing prompt bodies, document text, API keys or other
secret payloads.

## Event chain

A trace can contain:

`source -> analysis -> ai -> guardian -> memory`

Every event may include:

- module and operation;
- source type / source identifier;
- Tory Document ID when applicable;
- provider and model for AI calls;
- duration and retry count;
- Guardian outcome and risk metadata;
- Memory ID after a successful durable write;
- status: running, success, pending, blocked, ignored, error or interrupted.

All steps in one operation share a random `trace_id`.

## Privacy

Observability stores technical metadata only. It does not intentionally persist:

- user prompt text;
- extracted document text;
- DeepSeek API keys;
- Vault passphrases;
- complete memory content.

The journal lives at:

`data/observability/tooru_observability.sqlite3`

Default retention is 30 days and can be changed with
`TOORU_OBSERVABILITY_RETENTION_DAYS`.

## API

- `GET /v1/observability/summary`
- `GET /v1/observability/traces/{trace_id}`

The API remains protected by Dragon Tory's loopback-only HTTP policy.

## System Brain

The dashboard shows:

- what Dragon Tory is doing now;
- which module called AI;
- average AI latency;
- retry count over the selected 24-hour window;
- Guardian blocks and pending decisions;
- durable memory write count;
- recent source-to-memory traces;
- live highlighting of active modules and DeepSeek.
