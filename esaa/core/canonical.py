"""Canonical JSON serialization for deterministic hashing.

Rules (per ESAA spec v0.4.0):
- Encoding: UTF-8
- Keys: sorted alphabetically (sort_keys=True)
- Separators: (',', ':') — no spaces
- Final character: LF newline (\\n)
"""

import json
from typing import Any


def canonical_json(obj: Any) -> bytes:
    """Serialize obj to canonical JSON bytes (UTF-8, sorted keys, compact, final LF)."""
    text = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return (text + "\n").encode("utf-8")


def canonical_json_str(obj: Any) -> str:
    """Serialize obj to canonical JSON string (no trailing LF — for inline use)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
