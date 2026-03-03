"""ESAA MCP Server — exposes the orchestrator runtime as MCP tools.

Run with:
    python -m esaa.mcp_server

Transport: stdio (default for Claude Code MCP integration).

Tools exposed:
    esaa_get_state              Return current projected state + eligible tasks
    esaa_validate_and_persist   Full 7-layer validate → persist → project → verify cycle
    esaa_verify                 Standalone integrity audit
    esaa_init                   Bootstrap .roadmap/ scaffolding
"""

import json
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from esaa.constants import ROADMAP_DIR
from esaa.core.event_store import (
    append_events,
    get_last_seq,
    parse_event_store,
)
from esaa.core.projection import (
    get_eligible_tasks,
    project,
    write_projections,
)
from esaa.core.verification import compute_projection_hash, verify as run_verify
from esaa.core.validation import validate_agent_output, ValidationError
from esaa.cli import cmd_init as _cli_init


mcp = FastMCP("esaa-orchestrator-server")


# ---------------------------------------------------------------------------
# Tool: esaa_get_state
# ---------------------------------------------------------------------------

@mcp.tool()
def esaa_get_state(roadmap_dir: str = ROADMAP_DIR) -> str:
    """Return the current projected state of the ESAA project.

    Reads the event store, projects the state, and returns:
    - Current roadmap (tasks, indexes, meta)
    - Eligible tasks (status=todo with all depends_on done)
    - Open issues
    - Active lessons

    Args:
        roadmap_dir: Path to the .roadmap directory (default: .roadmap)

    Returns:
        JSON string with keys: roadmap, eligible_tasks, issues, lessons
    """
    try:
        events = parse_event_store(roadmap_dir)
        state = project(events)
        eligible = get_eligible_tasks(state["tasks"])

        result = {
            "roadmap": {
                "schema_version": state["schema_version"],
                "meta": state["meta"],
                "project": state["project"],
                "tasks": state["tasks"],
                "indexes": state["indexes"],
            },
            "eligible_tasks": eligible,
            "issues": state.get("issues", []),
            "lessons": state.get("lessons", []),
        }
        return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool: esaa_validate_and_persist
# ---------------------------------------------------------------------------

@mcp.tool()
def esaa_validate_and_persist(
    agent_output_json: str,
    task_id: str,
    agent_name: str = "agent",
    roadmap_dir: str = ROADMAP_DIR,
) -> str:
    """Validate agent output (7-layer) and persist events if valid.

    Full pipeline:
        1. Parse event store → project current state
        2. Locate task by task_id
        3. Run 7-layer validation
        4. On failure: append output.rejected event, return error
        5. On success:
           a. Append agent action event
           b. Append orchestrator.file.write for each file_update
           c. Append orchestrator.view.mutate
           d. Re-project views
           e. Compute hash, write roadmap.json
           f. Append verify.start + verify.ok/fail
           g. Return result

    Args:
        agent_output_json: Raw JSON string from the agent.
        task_id: The task ID the agent is operating on.
        agent_name: Actor name for the agent (e.g. 'agent-spec').
        roadmap_dir: Path to the .roadmap directory.

    Returns:
        JSON string with: status, events_appended, verify_result (or error details)
    """
    try:
        # Step 1: Parse + project
        events = parse_event_store(roadmap_dir)
        state = project(events)
        last_seq = get_last_seq(events)

        # Step 2: Find the task
        current_task = next(
            (t for t in state["tasks"] if t.get("task_id") == task_id),
            None,
        )
        if current_task is None:
            return json.dumps({"error": f"task '{task_id}' not found in roadmap"})

        # Step 3: Validate
        try:
            validated = validate_agent_output(
                raw_json=agent_output_json,
                current_task=current_task,
                roadmap_tasks=state["tasks"],
            )
        except ValidationError as ve:
            # Step 4: Reject
            reject_payload = {
                "task_id": task_id,
                "error_code": ve.error_code,
                "layer": ve.layer,
                "detail": ve.detail,
                "attempt_count": current_task.get("attempt_count", 0) + 1,
            }
            append_events(
                roadmap_dir,
                [{"actor": "orchestrator", "action": "output.rejected", "payload": reject_payload}],
                last_seq=last_seq,
            )
            return json.dumps({
                "status": "rejected",
                "error_code": ve.error_code,
                "layer": ve.layer,
                "detail": ve.detail,
            })

        # Step 5a: Agent action event
        ae = validated["activity_event"]
        action = ae["action"]
        agent_payload = {k: v for k, v in ae.items() if k != "action"}
        agent_payload["task_id"] = task_id

        new_events_data: list[dict[str, Any]] = [
            {"actor": agent_name, "action": action, "payload": agent_payload}
        ]

        # Step 5b: orchestrator.file.write for each file_update
        for fu in validated.get("file_updates", []) or []:
            new_events_data.append({
                "actor": "orchestrator",
                "action": "orchestrator.file.write",
                "payload": {"path": fu["path"], "task_id": task_id},
            })

        # Step 5c: orchestrator.view.mutate
        new_events_data.append({
            "actor": "orchestrator",
            "action": "orchestrator.view.mutate",
            "payload": {"views": ["roadmap.json", "issues.json", "lessons.json"]},
        })

        appended = append_events(roadmap_dir, new_events_data, last_seq=last_seq)
        last_seq = appended[-1].event_seq

        # Step 5d: Re-project
        all_events = parse_event_store(roadmap_dir)
        new_state = project(all_events)

        # Step 5e: Compute hash and write
        h = compute_projection_hash(new_state)
        new_state["meta"]["run"]["projection_hash_sha256"] = h
        new_state["meta"]["run"]["verify_status"] = "ok"
        write_projections(roadmap_dir, new_state)

        # Step 5f: verify.start + verify.ok
        verify_result = run_verify(roadmap_dir)
        verify_action = "verify.ok" if verify_result["verify_status"] == "ok" else "verify.fail"
        append_events(
            roadmap_dir,
            [
                {"actor": "orchestrator", "action": "verify.start", "payload": {"strict": True}},
                {
                    "actor": "orchestrator",
                    "action": verify_action,
                    "payload": {
                        "verify_status": verify_result["verify_status"],
                        "projection_hash_sha256": verify_result["computed_hash"],
                        "last_event_seq": last_seq,
                    },
                },
            ],
            last_seq=last_seq,
        )

        return json.dumps({
            "status": "accepted",
            "action": action,
            "task_id": task_id,
            "events_appended": len(appended),
            "files_written": [fu["path"] for fu in validated.get("file_updates", []) or []],
            "verify_result": verify_result,
        }, ensure_ascii=False)

    except Exception as exc:
        return json.dumps({"error": f"unexpected error: {exc}"}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool: esaa_verify
# ---------------------------------------------------------------------------

@mcp.tool()
def esaa_verify(roadmap_dir: str = ROADMAP_DIR) -> str:
    """Run a standalone integrity verification (SHA-256 replay).

    Returns:
        JSON string with: verify_status, computed_hash, stored_hash, last_event_seq, detail
    """
    try:
        result = run_verify(roadmap_dir)
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool: esaa_init
# ---------------------------------------------------------------------------

@mcp.tool()
def esaa_init(
    project_name: str = "ESAA Project",
    audit_scope: str = "",
    run_id: str = "RUN-0001",
    roadmap_dir: str = ROADMAP_DIR,
    force: bool = False,
) -> str:
    """Bootstrap a new ESAA project (creates .roadmap/ scaffolding).

    Creates:
    - All contract YAML files
    - All JSON schemas
    - Initial activity.jsonl (run.start + verify.ok)
    - Initial roadmap.json, issues.json, lessons.json

    Args:
        project_name: Human-readable project name.
        audit_scope: Short description of the audit scope.
        run_id: Run ID for the initial run.start event.
        roadmap_dir: Target .roadmap directory path.
        force: If True, overwrite existing directory.

    Returns:
        JSON string with: status, message, files_created
    """
    import argparse as _argparse

    # Reuse the CLI command logic
    fake_args = _argparse.Namespace(
        roadmap_dir=roadmap_dir,
        project_name=project_name,
        audit_scope=audit_scope,
        run_id=run_id,
        force=force,
    )

    try:
        exit_code = _cli_init(fake_args)
        if exit_code == 0:
            files = list(Path(roadmap_dir).iterdir())
            return json.dumps({
                "status": "ok",
                "message": f"Project '{project_name}' initialised in '{roadmap_dir}'",
                "files_created": [f.name for f in files],
            })
        else:
            return json.dumps({
                "status": "error",
                "message": f"Init failed (exit code {exit_code}). Use force=True to overwrite.",
            })
    except Exception as exc:
        return json.dumps({"status": "error", "message": str(exc)})


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the MCP server on stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
