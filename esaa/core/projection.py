"""Pure projection function: event log → read-models.

project(events) is a pure function — given the same events it always produces
identical output. This determinism is what makes SHA-256 verification possible.

Read-models produced:
    roadmap.json  — tasks, indexes, meta
    issues.json   — open/resolved issues
    lessons.json  — active/archived lessons
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from esaa.constants import (
    SCHEMA_VERSION,
    ROADMAP_DIR,
    ROADMAP_FILE,
    ISSUES_FILE,
    LESSONS_FILE,
)
from esaa.core.event_store import EventEnvelope
from esaa.core.canonical import canonical_json_str


# ---------------------------------------------------------------------------
# Projection entry point
# ---------------------------------------------------------------------------

def project(events: list[EventEnvelope]) -> dict[str, Any]:
    """Replay all events and return the full projected state.

    Returns a dict with keys:
        schema_version, project, tasks, indexes, meta, issues, lessons

    Note: meta.run.projection_hash_sha256 is set to "" here.
    The verification module computes and fills it in after projection.
    """
    state: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "project": {"name": "", "audit_scope": ""},
        "tasks": [],
        "indexes": {"by_status": {}, "by_kind": {}},
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "esaa_version": "1.0.0",
            "immutable_done": True,
            "master_correlation_id": "",
            "run": {
                "run_id": "",
                "status": "unknown",
                "last_event_seq": 0,
                "projection_hash_sha256": "",
                "verify_status": "unknown",
            },
            "updated_at": "",
        },
        "issues": [],
        "lessons": [],
    }

    for event in events:
        state = apply_event(state, event)

    # Final bookkeeping
    state["meta"]["run"]["last_event_seq"] = (
        events[-1].event_seq if events else 0
    )
    state["meta"]["updated_at"] = (
        datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    state["indexes"] = build_indexes(state["tasks"])

    return state


def apply_event(state: dict[str, Any], event: EventEnvelope) -> dict[str, Any]:
    """Apply a single event to the accumulated state. Pure function (mutates a copy)."""
    import copy
    s = copy.deepcopy(state)
    p = event.payload
    action = event.action

    # ---- Orchestrator events ----
    if action == "run.start":
        s["meta"]["run"]["run_id"] = p.get("run_id", "")
        s["meta"]["run"]["status"] = p.get("status", "initialized")
        s["meta"]["master_correlation_id"] = p.get("master_correlation_id", "")
        # Project info is stored in run.start payload so it survives replay
        if "project_name" in p:
            s["project"]["name"] = p["project_name"]
        if "audit_scope" in p:
            s["project"]["audit_scope"] = p["audit_scope"]

    elif action == "run.end":
        s["meta"]["run"]["status"] = p.get("status", "unknown")

    elif action in ("task.create", "hotfix.create"):
        task: dict[str, Any] = {
            "task_id": p.get("task_id", ""),
            "task_kind": p.get("task_kind", "impl"),
            "title": p.get("title", ""),
            "description": p.get("description", ""),
            "status": "todo",
            "depends_on": p.get("depends_on", []),
            "targets": p.get("targets", []),
            "outputs": p.get("outputs", {"files": []}),
            "immutability": {"done_is_immutable": True},
            "attempt_count": 0,
        }
        if action == "hotfix.create":
            task["is_hotfix"] = True
            task["issue_id"] = p.get("issue_id", "")
            task["scope_patch"] = p.get("scope_patch", [])
            task["required_verification"] = p.get("required_verification", [])
        s["tasks"].append(task)

    elif action == "verify.ok":
        s["meta"]["run"]["verify_status"] = "ok"
        s["meta"]["run"]["projection_hash_sha256"] = p.get("projection_hash_sha256", "")

    elif action == "verify.fail":
        s["meta"]["run"]["verify_status"] = p.get("verify_status", "mismatch")

    elif action == "orchestrator.view.mutate":
        pass  # read-model write is tracked in the event but not re-applied here

    elif action == "orchestrator.file.write":
        pass  # file write is tracked but content is not stored in projection

    elif action == "issue.resolve":
        issue_id = p.get("issue_id", "")
        for issue in s["issues"]:
            if issue.get("issue_id") == issue_id:
                issue["status"] = "resolved"
                issue["resolved_at"] = event.ts
                issue["resolved_by_task_id"] = p.get("resolved_by_task_id")

    # ---- Agent events ----
    elif action == "claim":
        task_id = p.get("task_id", "")
        task = _find_task(s["tasks"], task_id)
        if task and task["status"] == "todo":
            task["status"] = "in_progress"
            task["assigned_to"] = event.actor
            task["started_at"] = event.ts

    elif action == "complete":
        task_id = p.get("task_id", "")
        task = _find_task(s["tasks"], task_id)
        if task and task["status"] == "in_progress":
            task["status"] = "review"
            task["verification"] = p.get("verification", {})
            task["notes"] = p.get("notes", "")

    elif action == "review":
        task_id = p.get("task_id", "")
        decision = p.get("decision", "")
        task = _find_task(s["tasks"], task_id)
        if task and task["status"] == "review":
            if decision == "approve":
                task["status"] = "done"
                task["completed_at"] = event.ts
                if p.get("fixes"):
                    task["fixes"] = p["fixes"]
            elif decision == "request_changes":
                task["status"] = "in_progress"
                task["attempt_count"] = task.get("attempt_count", 0) + 1

    elif action == "issue.report":
        issue: dict[str, Any] = {
            "issue_id": p.get("issue_id", ""),
            "status": "open",
            "severity": p.get("severity", "medium"),
            "title": p.get("title", ""),
            "task_id": p.get("task_id", ""),
            "evidence": p.get("evidence", {}),
            "reported_at": event.ts,
            "resolved_at": None,
            "resolved_by_task_id": None,
        }
        # Update existing or append
        existing = next(
            (i for i in s["issues"] if i.get("issue_id") == issue["issue_id"]),
            None,
        )
        if existing:
            existing.update(issue)
        else:
            s["issues"].append(issue)

    elif action == "output.rejected":
        task_id = p.get("task_id", "")
        task = _find_task(s["tasks"], task_id)
        if task:
            task["attempt_count"] = task.get("attempt_count", 0) + 1

    return s


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_task(tasks: list[dict], task_id: str) -> Optional[dict]:
    return next((t for t in tasks if t.get("task_id") == task_id), None)


def build_indexes(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Build by_status and by_kind indexes from the tasks list."""
    by_status: dict[str, int] = {"todo": 0, "in_progress": 0, "review": 0, "done": 0}
    by_kind: dict[str, int] = {"spec": 0, "impl": 0, "qa": 0}

    for task in tasks:
        status = task.get("status", "")
        kind = task.get("task_kind", "")
        if status in by_status:
            by_status[status] += 1
        if kind in by_kind:
            by_kind[kind] += 1

    return {"by_status": by_status, "by_kind": by_kind}


def get_eligible_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return tasks with status=todo where all depends_on tasks are done."""
    done_ids = {t["task_id"] for t in tasks if t.get("status") == "done"}
    return [
        t for t in tasks
        if t.get("status") == "todo"
        and all(dep in done_ids for dep in t.get("depends_on", []))
    ]


# ---------------------------------------------------------------------------
# Write read-models to disk
# ---------------------------------------------------------------------------

def write_projections(
    roadmap_dir: str,
    state: dict[str, Any],
) -> None:
    """Write roadmap.json, issues.json, and lessons.json using canonical JSON.

    Args:
        roadmap_dir: Path to the .roadmap directory.
        state: Full projected state dict from project().
    """
    base = Path(roadmap_dir)
    base.mkdir(parents=True, exist_ok=True)

    # roadmap.json — excludes raw issues/lessons arrays (those live in their own files)
    roadmap = {
        "schema_version": state["schema_version"],
        "meta": state["meta"],
        "project": state["project"],
        "tasks": state["tasks"],
        "indexes": state["indexes"],
    }
    _write_json(base / ROADMAP_FILE, roadmap)

    # issues.json
    issues_doc = {
        "schema_version": SCHEMA_VERSION,
        "issues": state.get("issues", []),
    }
    _write_json(base / ISSUES_FILE, issues_doc)

    # lessons.json
    lessons_doc = {
        "schema_version": SCHEMA_VERSION,
        "lessons": state.get("lessons", []),
    }
    _write_json(base / LESSONS_FILE, lessons_doc)


def _write_json(path: Path, obj: Any) -> None:
    """Write an object as canonical JSON (sorted keys, compact, UTF-8, final LF)."""
    content = canonical_json_str(obj) + "\n"
    path.write_text(content, encoding="utf-8")
