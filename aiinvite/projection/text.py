"""text_v1: project a kernel into a persona narrative plus constraints."""

from __future__ import annotations

from aiinvite.projection.errors import E_PR_EMPTY, ProjectionError
from aiinvite.projection.trace import Segment, Trace

PROJECTOR = "text_v1"
NARRATIVE_PREFIX = "[self] "
CONSTRAINT_PREFIX = "[canon] "


def project_text(kernel: object) -> Trace:
    """Project a kernel object into text segments only.

    The projector reads ``self_md`` and ``canon`` from the kernel object and
    never receives a store, a path or evidence. This is a diagnostic view:
    the narrative is ``description`` and every canon restatement is
    ``constraint``, so a gate judging spoken words never mistakes "I obey
    this rule" for saying the forbidden word.
    """
    segments: list[Segment] = []
    narrative = str(kernel.self_md).strip()
    if narrative:
        segments.append(
            Segment(
                "text", NARRATIVE_PREFIX + narrative, None, role="description"
            )
        )
    for entry in kernel.canon:
        segments.append(
            Segment(
                "text",
                CONSTRAINT_PREFIX + f"{entry.kind}: {entry.text}",
                None,
                entry.text,
                role="constraint",
            )
        )
    if not segments:
        raise ProjectionError(E_PR_EMPTY, "内核没有可投影的人格内容")
    return Trace(
        kid=kernel.kid, projector=PROJECTOR, segments=tuple(segments)
    )
