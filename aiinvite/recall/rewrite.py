"""Rewrite a question into recall keywords, only when lexical recall fails.

The index is lexical; a question such as "the sad thing I told you about" shares
no term with the memory it asks for. The bridge has to be inference, and the
only inference available without a cloud or a dependency is the user local
model.

This module only talks to an injected caller, so tests never need a model. It
runs on the failure path alone: a question that already hits pays nothing.
"""
from __future__ import annotations

import re

MAX_TERMS = 6
TERM_MIN = 1
TERM_MAX = 8
CJK = re.compile(r"[\u4e00-\u9fff]+")

PROMPT = (
    "用户刚才问：{question}\n"
    "请推断他可能在回忆什么，只输出 3-5 个用于检索旧对话的中文关键词，"
    "用空格分隔，不要解释。"
)


def build_prompt(question):
    """Return the instruction sent to the local model."""
    return PROMPT.format(question=(question or "").strip()[:200])


def sanitize(raw, limit=MAX_TERMS):
    """Turn a model reply into at most limit clean Chinese terms."""
    terms = []
    seen = set()
    for chunk in re.split(r"[\s,，、。；;:：\n]+", raw or ""):
        for piece in CJK.findall(chunk):
            if not (TERM_MIN <= len(piece) <= TERM_MAX):
                continue
            if piece in seen:
                continue
            seen.add(piece)
            terms.append(piece)
            if len(terms) >= limit:
                return tuple(terms)
    return tuple(terms)


def rewrite_query(question, caller):
    """Ask the caller for recall keywords; any failure yields no terms."""
    if caller is None:
        return ()
    try:
        raw = caller(build_prompt(question))
    except Exception:
        return ()
    return sanitize(str(raw or ""))
