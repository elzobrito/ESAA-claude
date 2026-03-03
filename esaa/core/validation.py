"""7-layer validation pipeline for agent outputs.

Layer | Check                        | Error code
------|------------------------------|-----------------------------
 4a   | JSON parse                   | schema_violation
 4b   | Schema (agent_result.json)   | schema_violation
 4c   | Action vocabulary            | unknown_action
 4d   | State machine transition     | invalid_transition
 4e   | Write boundary by task_kind  | boundary_violation
 4f   | Done immutability            | immutable_done_violation
 4g   | Verification gate            | verification_gate

All layers run in strict order. First failure raises ValidationError.
"""

import json
from typing import Any, Optional

import jsonschema

from esaa.constants import (
    ALLOWED_AGENT_ACTIONS,
    PROHIBITED_AGENT_FIELDS,
    TERMINAL_STATES,
)
from esaa.core.state_machine import validate_transition, is_terminal
from esaa.core.boundaries import check_write_boundary
from esaa.schemas import load_schema


class ValidationError(Exception):
    """Raised when an agent output fails any validation layer."""

    def __init__(self, layer: str, error_code: str, detail: str) -> None:
        self.layer = layer
        self.error_code = error_code
        self.detail = detail
        super().__init__(f"[{layer}] {error_code}: {detail}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def validate_agent_output(
    raw_json: str,
    current_task: dict[str, Any],
    roadmap_tasks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run the full 7-layer validation pipeline on raw agent JSON.

    Args:
        raw_json: The raw JSON string produced by the agent.
        current_task: The task dict the agent is operating on.
        roadmap_tasks: Full tasks list from the current projection.

    Returns:
        Parsed and validated agent output dict.

    Raises:
        ValidationError: On the first layer that fails.
    """
    parsed = _layer_4a_parse(raw_json)
    _layer_4b_schema(parsed)
    _layer_4c_action_vocabulary(parsed)
    _layer_4d_state_transition(parsed, current_task)
    _layer_4e_boundary(parsed, current_task)
    _layer_4f_immutability(parsed, roadmap_tasks)
    _layer_4g_verification_gate(parsed, current_task)
    return parsed


# ---------------------------------------------------------------------------
# Individual layers
# ---------------------------------------------------------------------------

def _layer_4a_parse(raw_json: str) -> dict[str, Any]:
    """4a — JSON parse."""
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValidationError("4a", "schema_violation", f"invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValidationError("4a", "schema_violation", "agent output must be a JSON object")
    return parsed


def _layer_4b_schema(parsed: dict[str, Any]) -> None:
    """4b — Schema validation against agent_result.schema.json.
    Also checks for prohibited fields in activity_event.
    """
    schema = load_schema("agent_result")
    try:
        jsonschema.validate(instance=parsed, schema=schema)
    except jsonschema.ValidationError as exc:
        raise ValidationError(
            "4b", "schema_violation", exc.message
        ) from exc

    # Prohibited fields check (cannot be expressed cleanly in JSON Schema)
    ae = parsed.get("activity_event", {})
    forbidden_found = PROHIBITED_AGENT_FIELDS & set(ae.keys())
    if forbidden_found:
        raise ValidationError(
            "4b",
            "schema_violation",
            f"activity_event contains prohibited fields: {sorted(forbidden_found)}",
        )


def _layer_4c_action_vocabulary(parsed: dict[str, Any]) -> None:
    """4c — Action must be in ALLOWED_AGENT_ACTIONS."""
    action = parsed.get("activity_event", {}).get("action", "")
    if action not in ALLOWED_AGENT_ACTIONS:
        raise ValidationError(
            "4c",
            "unknown_action",
            f"action '{action}' is not an allowed agent action. "
            f"Allowed: {sorted(ALLOWED_AGENT_ACTIONS)}",
        )


def _layer_4d_state_transition(
    parsed: dict[str, Any], current_task: dict[str, Any]
) -> None:
    """4d — State machine transition must be valid for current task status."""
    ae = parsed["activity_event"]
    action = ae["action"]
    current_status = current_task.get("status", "")
    decision = ae.get("decision")

    valid, _ = validate_transition(current_status, action, decision)
    if not valid:
        desc = f"action='{action}'"
        if decision:
            desc += f" decision='{decision}'"
        raise ValidationError(
            "4d",
            "invalid_transition",
            f"cannot apply {desc} to task with status='{current_status}'",
        )


def _layer_4e_boundary(
    parsed: dict[str, Any], current_task: dict[str, Any]
) -> None:
    """4e — All file_updates paths must satisfy write boundaries."""
    file_updates: list[dict] = parsed.get("file_updates", []) or []
    if not file_updates:
        return

    task_kind = current_task.get("task_kind", "")
    is_hotfix = current_task.get("is_hotfix", False)
    scope_patch: Optional[list[str]] = current_task.get("scope_patch")

    for fu in file_updates:
        path = fu.get("path", "")
        allowed, reason = check_write_boundary(
            task_kind=task_kind,
            path=path,
            scope_patch=scope_patch,
            is_hotfix=bool(is_hotfix),
        )
        if not allowed:
            raise ValidationError("4e", "boundary_violation", reason or "boundary violation")


def _layer_4f_immutability(
    parsed: dict[str, Any], roadmap_tasks: list[dict[str, Any]]
) -> None:
    """4f — The target task must not be in a terminal (done) state."""
    task_id = parsed["activity_event"].get("task_id", "")
    target = next((t for t in roadmap_tasks if t.get("task_id") == task_id), None)
    if target and is_terminal(target.get("status", "")):
        raise ValidationError(
            "4f",
            "immutable_done_violation",
            f"task '{task_id}' has status='done' and is immutable. "
            "Corrections require the hotfix workflow.",
        )


def _layer_4g_verification_gate(
    parsed: dict[str, Any], current_task: dict[str, Any]
) -> None:
    """4g — verification.checks requirements for 'complete' action.

    impl (non-hotfix): >= 1 check
    impl (hotfix):     >= 2 checks + issue_id + fixes
    """
    ae = parsed["activity_event"]
    if ae.get("action") != "complete":
        return

    task_kind = current_task.get("task_kind", "")
    is_hotfix = current_task.get("is_hotfix", False)

    # Only impl tasks require verification gate
    if task_kind != "impl":
        return

    verification = ae.get("verification", {})
    checks: list = (verification or {}).get("checks", [])

    min_checks = 2 if is_hotfix else 1

    if not checks or len(checks) < min_checks:
        raise ValidationError(
            "4g",
            "verification_gate",
            f"complete on {'hotfix ' if is_hotfix else ''}impl task requires "
            f"verification.checks with >= {min_checks} item(s), got {len(checks)}",
        )

    if is_hotfix:
        if not ae.get("issue_id"):
            raise ValidationError(
                "4g",
                "verification_gate",
                "hotfix complete requires 'issue_id' in activity_event",
            )
        if not ae.get("fixes"):
            raise ValidationError(
                "4g",
                "verification_gate",
                "hotfix complete requires 'fixes' in activity_event",
            )
