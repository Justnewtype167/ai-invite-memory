"""AI Invite · Memory: a portable memory and persona kernel for AI companions."""
from __future__ import annotations

import pathlib
import re

__all__ = ["__version__"]


def _resolve_version() -> str:
    """Return the version: a checkout reads pyproject, an install reads metadata."""
    pyproject = pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml"
    if pyproject.is_file():
        match = re.search(r'^version = "([^"]+)"', pyproject.read_text(encoding="utf-8"), re.M)
        if match:
            return match.group(1)
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("ai-invite-memory")
    except PackageNotFoundError:
        return "0.0.0"


__version__ = _resolve_version()
