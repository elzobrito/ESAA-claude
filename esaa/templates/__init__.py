"""Template loader — copies .roadmap/ scaffolding files to a target directory."""

import shutil
from pathlib import Path

_TEMPLATES_DIR = Path(__file__).parent


def copy_templates_to(target_dir: str) -> list[str]:
    """Copy all template files to target_dir/.

    Skips __init__.py and Python files.

    Returns:
        List of copied file paths (relative to target_dir).
    """
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    for src in _TEMPLATES_DIR.iterdir():
        if src.suffix in (".py", ".pyc") or src.name.startswith("_"):
            continue
        dst = target / src.name
        shutil.copy2(src, dst)
        copied.append(str(dst))

    return copied
