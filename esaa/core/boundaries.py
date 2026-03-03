"""Write boundary enforcement for ESAA agents.

Boundaries by task_kind (prefix_match semantics):
    spec  → write: docs/**          forbidden: src/**, tests/**, .roadmap/**
    impl  → write: src/**, tests/** forbidden: .roadmap/**, docs/spec/**
    qa    → write: docs/qa/**,      forbidden: src/**, .roadmap/**
                   tests/**

Hotfix tasks additionally restrict writes to the scope_patch prefix list.

The .roadmap/ directory is ALWAYS forbidden for agents regardless of task_kind.
"""

from typing import Optional

# Boundaries per task_kind.
# write patterns use glob-style "prefix/**" — enforcement converts to prefix string.
BOUNDARIES: dict[str, dict[str, list[str]]] = {
    "spec": {
        "read": [".roadmap/**", "docs/**"],
        "write": ["docs/**"],
        "forbidden": ["src/**", "tests/**", ".roadmap/**"],
    },
    "impl": {
        "read": [".roadmap/**", "docs/**", "src/**", "tests/**"],
        "write": ["src/**", "tests/**"],
        "forbidden": [".roadmap/**", "docs/spec/**"],
    },
    "qa": {
        "read": [".roadmap/**", "docs/**", "src/**", "tests/**"],
        "write": ["docs/qa/**", "tests/**"],
        "forbidden": ["src/**", ".roadmap/**"],
    },
}


def _pattern_to_prefix(pattern: str) -> str:
    """Convert a glob pattern like 'src/**' or 'src/*' to a path prefix 'src/'."""
    return pattern.replace("/**", "/").replace("/*", "/")


def check_write_boundary(
    task_kind: str,
    path: str,
    scope_patch: Optional[list[str]] = None,
    is_hotfix: bool = False,
) -> tuple[bool, Optional[str]]:
    """Check if a write to `path` is allowed for the given task_kind.

    Args:
        task_kind: One of 'spec', 'impl', 'qa'.
        path: The file path being written (relative, forward-slash).
        scope_patch: For hotfix tasks, the list of allowed path prefixes.
        is_hotfix: Whether this is a hotfix task.

    Returns:
        (is_allowed, error_reason) — error_reason is None if allowed.
    """
    # Normalise path separators
    path = path.replace("\\", "/")

    # Hardcoded invariant: .roadmap/ is ALWAYS forbidden for agents
    if path.startswith(".roadmap/") or path == ".roadmap":
        return False, "direct write to .roadmap/ is forbidden for agents"

    # Hotfix: scope_patch prefix_match overrides normal task_kind boundaries
    if is_hotfix:
        if not scope_patch:
            return False, "hotfix task has no scope_patch defined"
        for prefix in scope_patch:
            norm = prefix.replace("\\", "/")
            if path.startswith(norm):
                return True, None
        return False, f"path '{path}' is outside hotfix scope_patch {scope_patch}"

    # Normal task_kind boundary check
    boundaries = BOUNDARIES.get(task_kind)
    if boundaries is None:
        return False, f"unknown task_kind: '{task_kind}'"

    write_prefixes = [_pattern_to_prefix(p) for p in boundaries["write"]]
    if any(path.startswith(prefix) for prefix in write_prefixes):
        return True, None

    return (
        False,
        f"task_kind='{task_kind}' cannot write to '{path}'. "
        f"Allowed write prefixes: {boundaries['write']}",
    )


def get_boundaries(task_kind: str) -> Optional[dict[str, list[str]]]:
    """Return the boundary definition for a task_kind, or None if unknown."""
    return BOUNDARIES.get(task_kind)
