"""Jian CN: rule-based Chinese layer (kinship, timex, slang, normalization).

Zero model calls, zero network access, standard library only.
"""

from __future__ import annotations

from jian_cn.errors import CnError
from jian_cn.kinship import Kinship, parse_kinship
from jian_cn.normalize import normalize
from jian_cn.slang import availability, explain, lifespan, usable
from jian_cn.timex import TimeSpan, parse_time

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
