"""Deterministic projection verification via SHA-256 replay.

Algorithm (per ESAA spec v0.4.0):
    1. Parse event store (activity.jsonl)
    2. Replay project(events) — pure function
    3. Compute SHA-256 of canonical hash_input:
           { "indexes": {...}, "project": {...},
             "schema_version": "0.4.0", "tasks": [...] }
       (meta.run excluded to avoid self-reference)
    4. Compare computed hash with roadmap.json#meta.run.projection_hash_sha256

Status outcomes:
    ok         — projection is consistent with event store
    mismatch   — computed hash differs from stored hash
    corrupted  — event store is malformed / cannot be parsed
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from esaa.constants import ROADMAP_DIR, ROADMAP_FILE
from esaa.core.canonical import canonical_json
from esaa.core.event_store import parse_event_store, get_last_seq, EventStoreError
from esaa.core.projection import project

VerifyStatus = Literal["ok", "mismatch", "corrupted"]


def compute_projection_hash(state: dict[str, Any]) -> str:
    """Compute SHA-256 of the canonical hash_input (excludes meta.run).

    Hash input = canonical JSON of:
        { "indexes": ..., "project": ..., "schema_version": ..., "tasks": ... }

    Returns:
        Lowercase hex digest string.
    """
    hash_input = {
        "schema_version": state.get("schema_version", ""),
        "project": state.get("project", {}),
        "tasks": state.get("tasks", []),
        "indexes": state.get("indexes", {}),
    }
    raw = canonical_json(hash_input)          # UTF-8 bytes, sorted keys, final LF
    return hashlib.sha256(raw).hexdigest()


def verify(roadmap_dir: str = ROADMAP_DIR) -> dict[str, Any]:
    """Run full integrity verification.

    Steps:
        1. Parse event store
        2. project(events) deterministically
        3. compute_projection_hash(projected)
        4. Load stored hash from roadmap.json
        5. Compare

    Returns:
        {
            "verify_status": "ok" | "mismatch" | "corrupted",
            "computed_hash": str,
            "stored_hash": str | None,
            "last_event_seq": int,
            "detail": str,
        }
    """
    result: dict[str, Any] = {
        "verify_status": "corrupted",
        "computed_hash": "",
        "stored_hash": None,
        "last_event_seq": 0,
        "detail": "",
    }

    # Step 1: Parse event store
    try:
        events = parse_event_store(roadmap_dir)
    except EventStoreError as exc:
        result["detail"] = f"event store parse error: {exc}"
        return result
    except Exception as exc:
        result["detail"] = f"unexpected error reading event store: {exc}"
        return result

    result["last_event_seq"] = get_last_seq(events)

    # Step 2: Replay projection
    try:
        projected = project(events)
    except Exception as exc:
        result["detail"] = f"projection error: {exc}"
        return result

    # Step 3: Compute hash
    try:
        computed = compute_projection_hash(projected)
        result["computed_hash"] = computed
    except Exception as exc:
        result["detail"] = f"hash computation error: {exc}"
        return result

    # Step 4: Load stored hash from roadmap.json
    roadmap_path = Path(roadmap_dir) / ROADMAP_FILE
    if not roadmap_path.exists():
        result["verify_status"] = "mismatch"
        result["detail"] = "roadmap.json not found — cannot compare hash"
        return result

    try:
        roadmap_data = json.loads(roadmap_path.read_text(encoding="utf-8"))
        stored = (
            roadmap_data
            .get("meta", {})
            .get("run", {})
            .get("projection_hash_sha256", "")
        )
        result["stored_hash"] = stored
    except Exception as exc:
        result["detail"] = f"failed to read roadmap.json: {exc}"
        return result

    # Step 5: Compare
    if computed == stored:
        result["verify_status"] = "ok"
        result["detail"] = "projection is consistent with event store"
    else:
        result["verify_status"] = "mismatch"
        result["detail"] = (
            f"hash mismatch — computed={computed[:16]}… stored={str(stored)[:16]}…"
        )

    return result
