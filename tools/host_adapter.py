"""Compatibility shim: the adapter now ships as aiinvite.host."""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aiinvite.host import (  # noqa: E402,F401
    CARD_HEADER,
    CONTEXT_HEADER,
    INPUT_HEADER,
    PERSONA_HEADER,
    RULE_HEADER,
    HostSession,
    main,
)

if __name__ == "__main__":
    raise SystemExit(main())
