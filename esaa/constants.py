"""Shared constants for the ESAA runtime."""

SCHEMA_VERSION = "0.4.0"

# Event ID format: EV-00000001
EVENT_ID_PREFIX = "EV-"
EVENT_ID_WIDTH = 8

# Directory / file names
ROADMAP_DIR = ".roadmap"
ACTIVITY_FILE = "activity.jsonl"
ROADMAP_FILE = "roadmap.json"
ISSUES_FILE = "issues.json"
LESSONS_FILE = "lessons.json"
SNAPSHOTS_DIR = "snapshots"

# Actions reserved for agents (cannot be emitted by orchestrator as actor=orchestrator)
ALLOWED_AGENT_ACTIONS = frozenset({"claim", "complete", "review", "issue.report"})

# Actions reserved for the orchestrator
ORCHESTRATOR_ACTIONS = frozenset({
    "run.start",
    "run.end",
    "task.create",
    "hotfix.create",
    "issue.resolve",
    "output.rejected",
    "orchestrator.file.write",
    "orchestrator.view.mutate",
    "verify.start",
    "verify.ok",
    "verify.fail",
})

# Fields agents are FORBIDDEN from including in activity_event
PROHIBITED_AGENT_FIELDS = frozenset({
    "schema_version",
    "event_id",
    "event_seq",
    "ts",
    "actor",
    "payload",
    "assigned_to",
    "started_at",
    "completed_at",
})

# Valid task statuses
TASK_STATUSES = frozenset({"todo", "in_progress", "review", "done"})

# Valid task kinds
TASK_KINDS = frozenset({"spec", "impl", "qa"})

# Terminal states (immutable)
TERMINAL_STATES = frozenset({"done"})

# Valid issue severities
ISSUE_SEVERITIES = frozenset({"low", "medium", "high", "critical"})
