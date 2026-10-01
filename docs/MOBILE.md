# Mobile architecture

Dragon Tory is API-first so Android, iOS and future project-specific mobile apps can use the same core memory safely.

## Memory synchronization

Each memory record contains:

- `owner_id` — account namespace;
- `scope` — personal or project;
- `project_id` — mandatory for project memory;
- `device_id` and `session_id` — origin tracking;
- `client_mutation_id` — retry-safe write identifier;
- `revision` — optimistic concurrency control;
- `updated_at` — delta synchronization cursor;
- `deleted_at` — soft-delete tombstone propagated to other devices.

The mobile client should generate a unique `client_mutation_id` before creating a memory. Retrying the same operation returns the same record instead of creating a duplicate.

Updates require `expected_revision`. A stale phone or PC receives HTTP 409 instead of silently overwriting a newer memory.

`POST /v1/memory/sync` returns ordered deltas for exactly one memory scope. Project synchronization always requires a `project_id`, so one project's memory cannot be mixed into another project.

## Offline-first roadmap

A mobile app can keep a local SQLite cache and an outgoing operation queue:

1. write locally;
2. assign `client_mutation_id`;
3. send queued operations when internet becomes available;
4. pull deltas from `/v1/memory/sync`;
5. resolve HTTP 409 conflicts in the client or with a future memory-merger service.

## Security boundary

The current development server binds to `127.0.0.1`. Before exposing Dragon Tory to mobile devices over the internet, authentication must be added and `owner_id` must come from the authenticated identity, never directly from an untrusted client.

API keys for DeepSeek or Cloud.ru must stay on the backend and must never be embedded in Android or iOS applications.
