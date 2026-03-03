# ESAA Projection Specification v0.4.0

## Overview

Projections are deterministic read-models derived purely from the event store
(`activity.jsonl`). The function `project(events)` replays all events in order
and produces `roadmap.json`, `issues.json`, and `lessons.json`.

## Determinism Contract

Given the same ordered sequence of events, `project()` MUST always produce
identical output. This is verified by SHA-256 hashing of the canonical JSON
serialization.

## Hash Input

The hash is computed over the canonical JSON of:

```json
{
  "indexes":        {...},
  "project":        {...},
  "schema_version": "0.4.0",
  "tasks":          [...]
}
```

`meta.run` is **excluded** to avoid self-reference (the hash cannot include itself).

## Canonical Serialization

- Encoding: UTF-8
- Keys: sorted alphabetically (`sort_keys=True`)
- Separators: `(',', ':')` — no spaces
- Final character: LF newline (`\n`)

## State Machine

```
         claim              complete          review(approve)
[todo] ─────────► [in_progress] ─────────► [review] ─────────► [done] ✗
                       ▲                       │                   (immutable)
                       └───────────────────────┘
                          review(request_changes)
```

## Indexes

- `by_status`: maps each status to a count of tasks in that status
- `by_kind`: maps each task_kind to a count of tasks of that kind

## Event Handlers

| Action                    | Effect on projection                         |
|---------------------------|----------------------------------------------|
| `run.start`               | Sets meta.run.run_id, status                 |
| `run.end`                 | Sets meta.run.status                         |
| `task.create`             | Appends new task (status=todo)               |
| `hotfix.create`           | Appends hotfix task (is_hotfix=true)         |
| `claim`                   | task: todo → in_progress; sets assigned_to   |
| `complete`                | task: in_progress → review; sets verification|
| `review(approve)`         | task: review → done; sets completed_at       |
| `review(request_changes)` | task: review → in_progress; attempt_count++  |
| `issue.report`            | Appends/updates issue in issues[]            |
| `issue.resolve`           | issue.status = resolved                      |
| `output.rejected`         | task: attempt_count++                        |
| `verify.ok`               | Sets meta.run.projection_hash_sha256         |
| `verify.fail`             | Sets meta.run.verify_status                  |
