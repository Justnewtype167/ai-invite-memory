"""AI Invite CN: rule-based Chinese layer (kinship, timex, slang, normalization).

Zero model calls, zero network access, standard library only.
"""

from __future__ import annotations

from aiinvite.cn.errors import CnError
from aiinvite.cn.kinship import Kinship, parse_kinship
from aiinvite.cn.normalize import normalize
from aiinvite.cn.slang import availability, explain, lifespan, usable
from aiinvite.cn.timex import TimeSpan, parse_time

__all__ = [
    "CnError",
    "Kinship",
    "TimeSpan",
    "availability",
    "explain",
    "lifespan",
    "normalize",
    "parse_kinship",
    "parse_time",
    "usable",
]
