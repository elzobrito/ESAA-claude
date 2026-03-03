"""Schema loader with LRU cache — schemas are loaded once and reused."""

import json
from functools import lru_cache
from pathlib import Path

_SCHEMAS_DIR = Path(__file__).parent


@lru_cache(maxsize=None)
def load_schema(name: str) -> dict:
    """Load a JSON schema by base name (e.g. 'agent_result').

    Looks for {name}.schema.json in the schemas directory.

    Raises:
        FileNotFoundError: If the schema file does not exist.
    """
    path = _SCHEMAS_DIR / f"{name}.schema.json"
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)
