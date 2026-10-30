"""Shared fixtures for PCS tests: the six persona rules and scripted replies."""

from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import kn_fixtures

from jian_kernel.compiler import compile_kernel
from jian_kernel.kernel import Policy
from jian_kernel.proposer import prompt_sha_for, record_proposal

NOW = "2026-10-29T10:00:00+08:00"
STAMP = "2026-10-29T02:00:00Z"

STYLE_RULES = (
    "回答前先问一句对方现在最在意什么，再给建议",
    "不使用温柔、体贴、善解人意这类形容词",
    "一次回答不超过两句，最多只问一个问题",
)
CONDUCT_RULES = (
    "收到负面经历时先复述对方说的内容，再回应",
    "不追问原因，不评价对错，不说应该",
    "每次回复控制在 40 个字以内",
)

LEGAL = {
    STYLE_RULES[0]: "你现在最在意哪一点？我先不急着给建议。",
    STYLE_RULES[1]: "我在听，你慢慢说。",
    STYLE_RULES[2]: "我在。你先说。",
    CONDUCT_RULES[0]: "你说的是周五那件事，我记住了。",
    CONDUCT_RULES[1]: "这件事确实难受，我在。",
    CONDUCT_RULES[2]: "我在。",
}
VIOLATION = {
    STYLE_RULES[0]: "我建议你早点休息，别多想。",
    STYLE_RULES[1]: "我会温柔地陪着你。",
    STYLE_RULES[2]: "我在。你先说。然后告诉我发生了什么。还需要我做什么吗？",
    CONDUCT_RULES[0]: "别想太多，会过去的。",
    CONDUCT_RULES[1]: "你为什么不去问清楚？他应该道歉。",
    CONDUCT_RULES[2]: (
        "我理解你现在很难受，但你要相信事情总会慢慢好起来的，"
        "不要一直困在情绪里，先睡一觉再说。"
    ),
}


def reply_for(rule: str, obey: bool) -> str:
    """Return the scripted compliant or violating reply for one rule."""
    return LEGAL[rule] if obey else VIOLATION[rule]


def build_self_md() -> str:
    """Compile a store whose self.md carries all six persona rules."""
    root = pathlib.Path(tempfile.mkdtemp(prefix="jian_pcs_self_"))
    try:
        kn_fixtures.write_store(root, kn_fixtures.chat_turns(10))
        for rule in STYLE_RULES:
            record_proposal(
                root, "self.style", rule, "fixture", prompt_sha_for("self.style"),
                STAMP,
            )
        for rule in CONDUCT_RULES:
            record_proposal(
                root, "self.conduct", rule, "fixture",
                prompt_sha_for("self.conduct"), STAMP,
            )
        kernel = compile_kernel(root, Policy(now=NOW))
        return kernel.self_md
    finally:
        shutil.rmtree(root, True)
