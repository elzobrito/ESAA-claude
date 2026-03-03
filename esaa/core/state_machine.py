"""Task state machine for ESAA.

Valid transitions:
    todo        + claim             → in_progress
    in_progress + complete          → review
    review      + approve           → done
    review      + request_changes   → in_progress

done is terminal (immutable).
"""

from typing import Optional

# (from_status, action_key) → to_status
# For 'review' action, use decision ('approve' or 'request_changes') as action_key.
TRANSITIONS: dict[tuple[str, str], str] = {
    ("todo", "claim"): "in_progress",
    ("in_progress", "complete"): "review",
    ("review", "approve"): "done",
    ("review", "request_changes"): "in_progress",
}

TERMINAL_STATES: frozenset[str] = frozenset({"done"})


def validate_transition(
    current_status: str,
    action: str,
    decision: Optional[str] = None,
) -> tuple[bool, Optional[str]]:
    """Check if a state transition is valid.

    Args:
        current_status: Current task status.
        action: The agent action ('claim', 'complete', 'review', 'issue.report').
        decision: For 'review' action, the decision ('approve' or 'request_changes').

    Returns:
        (is_valid, new_status) — new_status is None if invalid.
    """
    if current_status in TERMINAL_STATES:
        return False, None

    # 'issue.report' does not change task status
    if action == "issue.report":
        return True, current_status

    # For 'review', the key is the decision
    action_key = decision if action == "review" else action
    if action_key is None:
        return False, None

    new_status = TRANSITIONS.get((current_status, action_key))
    if new_status is None:
        return False, None

    return True, new_status


def is_terminal(status: str) -> bool:
    """Return True if the status is terminal (immutable)."""
    return status in TERMINAL_STATES
