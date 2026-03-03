"""Append-only event store for ESAA.

The event store is the single source of truth: .roadmap/activity.jsonl
Every line is a JSON object representing one event. Events are strictly
ordered by event_seq (monotonic, gap-free, starting at 1).
"""

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from esaa.constants import (
    SCHEMA_VERSION,
    EVENT_ID_PREFIX,
    EVENT_ID_WIDTH,
    ROADMAP_DIR,
    ACTIVITY_FILE,
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class EventStoreError(Exception):
    """Base error for event store problems."""


class SeqGapError(EventStoreError):
    """event_seq is not monotonic or has a gap."""


class DuplicateEventIdError(EventStoreError):
    """Duplicate event_id found in the event store."""


class ParseError(EventStoreError):
    """A line in activity.jsonl is not valid JSON."""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class EventEnvelope:
    """A single validated event from the event store."""

    schema_version: str
    event_id: str
    event_seq: int
    ts: str
    actor: str
    action: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "event_seq": self.event_seq,
            "ts": self.ts,
            "actor": self.actor,
            "action": self.action,
            "payload": self.payload,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def format_event_id(seq: int) -> str:
    """Generate event_id: EV-XXXXXXXX (zero-padded to EVENT_ID_WIDTH digits)."""
    return f"{EVENT_ID_PREFIX}{seq:0{EVENT_ID_WIDTH}d}"


def _now_utc() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _activity_path(roadmap_dir: str) -> Path:
    return Path(roadmap_dir) / ACTIVITY_FILE


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

def parse_event_store(roadmap_dir: str = ROADMAP_DIR) -> list[EventEnvelope]:
    """Parse activity.jsonl line by line.

    Validates:
    - Every line is valid JSON with required fields.
    - event_seq is strictly monotonic starting from 1 (gap-free).
    - event_id is unique across all events.

    Returns:
        List of EventEnvelope objects in event_seq order.

    Raises:
        ParseError: If a line cannot be parsed as JSON.
        SeqGapError: If event_seq is not monotonic / gap-free.
        DuplicateEventIdError: If the same event_id appears more than once.
        EventStoreError: For any other structural problem.
    """
    path = _activity_path(roadmap_dir)

    if not path.exists():
        return []

    events: list[EventEnvelope] = []
    seen_ids: set[str] = set()
    expected_seq = 1

    with path.open(encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            raw = raw.strip()
            if not raw:
                continue

            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ParseError(
                    f"activity.jsonl line {lineno}: invalid JSON — {exc}"
                ) from exc

            # Required fields
            for field in ("schema_version", "event_id", "event_seq", "ts", "actor", "action"):
                if field not in obj:
                    raise EventStoreError(
                        f"activity.jsonl line {lineno}: missing required field '{field}'"
                    )

            seq = obj["event_seq"]
            if not isinstance(seq, int) or seq != expected_seq:
                raise SeqGapError(
                    f"activity.jsonl line {lineno}: expected event_seq={expected_seq}, "
                    f"got {seq!r} — store is corrupted or tampered"
                )

            eid = obj["event_id"]
            if eid in seen_ids:
                raise DuplicateEventIdError(
                    f"activity.jsonl line {lineno}: duplicate event_id '{eid}'"
                )
            seen_ids.add(eid)

            events.append(
                EventEnvelope(
                    schema_version=obj.get("schema_version", SCHEMA_VERSION),
                    event_id=eid,
                    event_seq=seq,
                    ts=obj["ts"],
                    actor=obj["actor"],
                    action=obj["action"],
                    payload=obj.get("payload", {}),
                )
            )
            expected_seq += 1

    return events


def get_last_seq(events: list[EventEnvelope]) -> int:
    """Return the last event_seq, or 0 if the list is empty."""
    return events[-1].event_seq if events else 0


# ---------------------------------------------------------------------------
# Append
# ---------------------------------------------------------------------------

def append_event(
    roadmap_dir: str,
    actor: str,
    action: str,
    payload: dict[str, Any],
    last_seq: int,
) -> EventEnvelope:
    """Append a single event to activity.jsonl.

    Auto-generates event_id (EV-XXXXXXXX), event_seq (last_seq + 1), and ts (now UTC).

    Args:
        roadmap_dir: Path to the .roadmap directory.
        actor: Actor name (e.g. 'orchestrator', 'agent-spec').
        action: Action string (e.g. 'run.start', 'claim').
        payload: Event payload dict.
        last_seq: Current last event_seq (0 if store is empty).

    Returns:
        The newly created EventEnvelope.

    Raises:
        EventStoreError: On write failure.
    """
    next_seq = last_seq + 1
    envelope = EventEnvelope(
        schema_version=SCHEMA_VERSION,
        event_id=format_event_id(next_seq),
        event_seq=next_seq,
        ts=_now_utc(),
        actor=actor,
        action=action,
        payload=payload,
    )

    path = _activity_path(roadmap_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    line = json.dumps(envelope.to_dict(), sort_keys=False, ensure_ascii=False)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")

    return envelope


def append_events(
    roadmap_dir: str,
    events_data: list[dict[str, Any]],
    last_seq: int,
) -> list[EventEnvelope]:
    """Append multiple events sequentially to activity.jsonl.

    Each entry in events_data must have: actor, action, payload.
    event_id, event_seq, ts are auto-generated in order.

    Returns:
        List of newly created EventEnvelope objects.
    """
    appended: list[EventEnvelope] = []
    current_seq = last_seq

    for item in events_data:
        ev = append_event(
            roadmap_dir=roadmap_dir,
            actor=item["actor"],
            action=item["action"],
            payload=item.get("payload", {}),
            last_seq=current_seq,
        )
        appended.append(ev)
        current_seq = ev.event_seq

    return appended
