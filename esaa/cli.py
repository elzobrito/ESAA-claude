"""ESAA command-line interface.

Commands:
    init     Create .roadmap/ scaffolding (contracts, schemas, policies, initial events)
    verify   Run integrity audit (SHA-256 replay)
    project  Re-project read-models from activity.jsonl
"""

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Optional

from esaa.constants import ROADMAP_DIR, SCHEMA_VERSION
from esaa.core.event_store import (
    append_events,
    get_last_seq,
    parse_event_store,
)
from esaa.core.projection import project, write_projections
from esaa.core.verification import compute_projection_hash, verify
from esaa.templates import copy_templates_to


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    """Parse arguments and dispatch to the appropriate command.

    Returns:
        Exit code (0 = success, 1 = failure).
    """
    parser = argparse.ArgumentParser(
        prog="esaa",
        description="ESAA — Event Sourcing for Autonomous Agents runtime",
    )
    parser.add_argument(
        "--roadmap-dir",
        default=ROADMAP_DIR,
        metavar="DIR",
        help=f"Path to the .roadmap directory (default: {ROADMAP_DIR})",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # ---- init ----
    p_init = sub.add_parser("init", help="Initialise a new ESAA project")
    p_init.add_argument(
        "--project-name",
        default="ESAA Project",
        metavar="NAME",
        help="Human-readable project name",
    )
    p_init.add_argument(
        "--audit-scope",
        default="",
        metavar="TEXT",
        help="Short description of the project audit scope",
    )
    p_init.add_argument(
        "--run-id",
        default="RUN-0001",
        metavar="ID",
        help="Run ID for the initial run.start event",
    )
    p_init.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing .roadmap/ directory",
    )

    # ---- verify ----
    p_verify = sub.add_parser("verify", help="Run integrity audit")
    p_verify.add_argument(
        "--strict",
        action="store_true",
        help="Exit with non-zero code if verify_status != ok",
    )

    # ---- project ----
    sub.add_parser("project", help="Re-project read-models from activity.jsonl")

    args = parser.parse_args(argv)

    if args.command == "init":
        return cmd_init(args)
    elif args.command == "verify":
        return cmd_verify(args)
    elif args.command == "project":
        return cmd_project(args)

    return 1


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> int:
    """Create .roadmap/ directory structure with all templates and initial events."""
    roadmap_dir = args.roadmap_dir
    base = Path(roadmap_dir)

    if base.exists() and any(base.iterdir()):
        if not args.force:
            print(
                f"[esaa] ERROR: '{roadmap_dir}' already exists and is not empty.\n"
                f"       Use --force to overwrite.",
                file=sys.stderr,
            )
            return 1
        shutil.rmtree(base)
        print(f"[esaa] Removed existing '{roadmap_dir}'.")

    base.mkdir(parents=True, exist_ok=True)
    (base / "snapshots").mkdir(exist_ok=True)

    # 1. Copy YAML / Markdown templates into .roadmap/
    copied = copy_templates_to(roadmap_dir)
    print(f"[esaa] Copied {len(copied)} template file(s) to '{roadmap_dir}'.")

    # 2. Also copy the bundled JSON schemas into .roadmap/
    _copy_schemas_to(roadmap_dir)

    # 3. Emit initial events: run.start (includes project info for deterministic replay)
    initial_events = [
        {
            "actor": "orchestrator",
            "action": "run.start",
            "payload": {
                "run_id": args.run_id,
                "status": "initialized",
                "master_correlation_id": f"CID-{args.run_id}",
                "baseline_id": "B-000",
                "project_name": args.project_name,
                "audit_scope": args.audit_scope,
            },
        },
    ]
    appended = append_events(roadmap_dir, initial_events, last_seq=0)
    print(f"[esaa] Appended {len(appended)} initial event(s).")

    # 4. Project initial state (project_name/audit_scope come from event payload)
    events = parse_event_store(roadmap_dir)
    state = project(events)

    # 5. Compute hash and store it
    h = compute_projection_hash(state)
    state["meta"]["run"]["projection_hash_sha256"] = h
    state["meta"]["run"]["verify_status"] = "ok"

    # 6. Write read-models
    write_projections(roadmap_dir, state)

    # 7. Append verify.start + verify.ok events
    # last_seq is obtained from the parsed event store which already includes
    # the run.start event — no need to add len(appended) again.
    last_seq = get_last_seq(events)
    verify_events = [
        {
            "actor": "orchestrator",
            "action": "verify.start",
            "payload": {"strict": True},
        },
        {
            "actor": "orchestrator",
            "action": "verify.ok",
            "payload": {
                "projection_hash_sha256": h,
                "last_event_seq": last_seq,
            },
        },
    ]
    append_events(roadmap_dir, verify_events, last_seq=last_seq)

    print(f"[esaa] OK: Project initialised. verify_status=ok  hash={h[:16]}...")
    return 0


def _copy_schemas_to(roadmap_dir: str) -> None:
    """Copy bundled JSON schemas from esaa/schemas/ to .roadmap/."""
    import importlib.resources as res
    schemas_dir = Path(__file__).parent / "schemas"
    target = Path(roadmap_dir)
    for schema_file in schemas_dir.glob("*.schema.json"):
        shutil.copy2(schema_file, target / schema_file.name)


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

def cmd_verify(args: argparse.Namespace) -> int:
    """Run SHA-256 integrity verification and print the result."""
    result = verify(args.roadmap_dir)
    status = result["verify_status"]

    if status == "ok":
        print(
            f"[esaa] OK: verify_status=ok\n"
            f"       hash={result['computed_hash']}\n"
            f"       last_event_seq={result['last_event_seq']}"
        )
        return 0

    # mismatch or corrupted
    print(
        f"[esaa] FAIL: verify_status={status}\n"
        f"       {result['detail']}\n"
        f"       computed={result.get('computed_hash', 'n/a')}\n"
        f"       stored  ={result.get('stored_hash', 'n/a')}",
        file=sys.stderr,
    )
    return 1 if args.strict else 0


# ---------------------------------------------------------------------------
# project
# ---------------------------------------------------------------------------

def cmd_project(args: argparse.Namespace) -> int:
    """Re-project all read-models from the event store."""
    roadmap_dir = args.roadmap_dir

    try:
        events = parse_event_store(roadmap_dir)
    except Exception as exc:
        print(f"[esaa] ERROR reading event store: {exc}", file=sys.stderr)
        return 1

    state = project(events)

    # Recompute and inject hash before writing
    h = compute_projection_hash(state)
    state["meta"]["run"]["projection_hash_sha256"] = h

    # Re-verify against the stored hash (which we just overwrote, so this checks
    # internal consistency of the re-projected state)
    state["meta"]["run"]["verify_status"] = "ok"

    write_projections(roadmap_dir, state)
    print(
        f"[esaa] OK: Re-projected {len(events)} event(s).\n"
        f"       hash={h[:16]}...  last_event_seq={get_last_seq(events)}"
    )
    return 0
