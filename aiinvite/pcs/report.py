"""Deterministic text report for a PCS run."""

from __future__ import annotations

from aiinvite.pcs.score import CollapseScore, PcsReport

INSUFFICIENT_NOTE = "insufficient_conformance"


def _rate(score: CollapseScore) -> str:
    """Format ``R`` with its counts so a skip cannot look like stability."""
    return (
        f"{score.r:.2f}  违规 {score.violating}/{score.replied}"
        f"  跳过 {score.skipped}"
    )


def _depth(score: CollapseScore) -> str:
    """Format normalized ``D``; ``n/a`` when no probe violated."""
    if score.d is None:
        return "n/a  无违规"
    return f"{score.d:.2f}  仅违规探针"


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
    ]
    if report.final_a is not None and report.final_b is not None:
        lines.extend([
            "",
            f"C_final(a)  {report.final_a.c:.2f}",
            f"C_final(b)  {report.final_b.c:.2f}",
            f"R(a)        {_rate(report.collapse_a)}",
            f"R(b)        {_rate(report.collapse_b)}",
            f"D(a)        {_depth(report.collapse_a)}",
            f"D(b)        {_depth(report.collapse_b)}",
        ])
    lines.extend(["", "按 rule 分组："])
    for rule in report.per_rule:
        lines.append(
            f"- {rule.rule}  探针 {rule.probes}  "
            f"C(a)={rule.c_a:.2f}  C(b)={rule.c_b:.2f}  "
            f"A={rule.a:.2f}  跳过 {rule.skipped}"
        )
    return "\n".join(lines) + "\n"
