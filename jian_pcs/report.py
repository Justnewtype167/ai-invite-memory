"""Deterministic text report for a PCS run."""

from __future__ import annotations

from jian_pcs.score import PcsReport

INSUFFICIENT_NOTE = "insufficient_conformance"


def render_report(report: PcsReport) -> str:
    """Render the four required numbers and the per-rule breakdown.

    The output is byte-stable: no timestamps, no dict iteration leaks, fixed
    two-decimal formatting. ``A`` and ``PCS`` are never printed alone.
    """
    pcs_line = f"PCS         {report.pcs:.2f}"
    if report.insufficient:
        pcs_line += f"        {INSUFFICIENT_NOTE}"
    lines = [
        f"探针        {report.probes}   跳过 {report.skipped}",
        f"C(a)        {report.model_a.c:.2f}",
        f"C(b)        {report.model_b.c:.2f}",
        f"A(a,b)      {report.agreement:.2f}",
        pcs_line,
        "",
        "按 rule 分组：",
    ]
    for rule in report.per_rule:
        lines.append(
            f"- {rule.rule}  探针 {rule.probes}  "
            f"C(a)={rule.c_a:.2f}  C(b)={rule.c_b:.2f}  "
            f"A={rule.a:.2f}  跳过 {rule.skipped}"
        )
    return "\n".join(lines) + "\n"
