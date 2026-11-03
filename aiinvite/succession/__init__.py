"""AI Invite succession: legacy capsules, redaction records and inheritance (M15).

A legacy capsule ships evidence, the exact compilation policy, plain-text
letters, a redaction record and a succession declaration. It never ships an
executable "continue running" path: the successor re-derives identity from the
evidence it is handed.
"""

from __future__ import annotations

from aiinvite.succession.errors import SuccessionError
from aiinvite.succession.legacy import export_legacy, import_legacy, verify_legacy
from aiinvite.succession.model import (
    LegacyInfo,
    Letter,
    load_policy,
    policy_bytes,
    recompute_kid,
)

__all__ = [
    "LegacyInfo",
    "Letter",
    "SuccessionError",
    "export_legacy",
    "import_legacy",
    "load_policy",
    "policy_bytes",
    "recompute_kid",
    "verify_legacy",
]
