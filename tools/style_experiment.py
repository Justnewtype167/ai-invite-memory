"""Four-arm style experiment: A bare kernel, B + traits, C + style, D + user card.

``--dry-run`` assembles the four prompts locally and prints their real length
and token cost. Without ``--dry-run`` every probe is sent to Ollama; when the
model is unavailable the script exits non-zero with a readable reason and
prints no numbers, so a report can never contain invented values.

Usage:
    python tools/style_experiment.py --group A B C D --dry-run
    python tools/style_experiment.py --group A B C D --models qwen3.5:9b glm4:9b
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
import tempfile
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from aiinvite.canonical import dumps  # noqa: E402
from aiinvite.capsule import append_payload_event, init_store  # noqa: E402
from aiinvite.pcs.probes import load_all_probes, load_rules_v2  # noqa: E402
from aiinvite.pcs.score import Reply, compute_pcs  # noqa: E402
from aiinvite.persona.style_card import echo_guard, parse_style_card, record_style_card  # noqa: E402
from aiinvite.persona.view import build_persona_view  # noqa: E402
from aiinvite.recall.tokenizer import estimate_tokens  # noqa: E402
from responder_ollama import build_system, call_ollama  # noqa: E402

FACTS_PATH = ROOT / "aiinvite/persona" / "data" / "facts.jsonl"
GROUPS = ("A", "B", "C", "D")
DEFAULT_MODELS = ("qwen3.5:9b", "glm4:9b")
TEMP_MILLI = 0
SEED = 42
STYLE_CARD = {
    "source": {"from_event": "ev_000001", "to_event": "ev_000012", "count": 12},
    "distilled_at": "2026-01-05T10:00:00Z",
    "model": "qwen3.5:9b",
    "prompt_sha": "ab12cd34",
    "rhythm": "短句为主，先接情绪再给建议",
    "address": "直接称呼，不用敬语",
    "tics": ["嗯"],
    "examples": ["今天先歇一会儿吧"],
    "counter_examples": ["综上所述，建议您"],
    "forbidden": ["宝贝"],
}


@dataclass(frozen=True)
class Fact:
    """One user-fact probe: a question and the substring a correct reply has."""

    fact_id: str
    question: str
    answer: str


def load_facts(path: pathlib.Path | None = None) -> tuple[Fact, ...]:
    """Load the 30 user-fact probes; every line needs id, question and answer."""
    target = path if path is not None else FACTS_PATH
    facts: list[Fact] = []
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"cannot read facts: {target}") from exc
    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"facts line {line_no} is not JSON") from exc
        if not isinstance(data, dict):
            raise ValueError(f"facts line {line_no} is not an object")
        for key in ("id", "question", "answer"):
            if not isinstance(data.get(key), str) or not data[key]:
                raise ValueError(f"facts line {line_no} lacks {key}")
        facts.append(Fact(str(data["id"]), str(data["question"]), str(data["answer"])))
    return tuple(facts)


def _add(
    store: pathlib.Path, text: str, stamp: str, *,
    type: str = "turn", kind: str | None = None,
) -> None:
    """Append one v2 text event so the demo store can also hold a style card."""
    role = "user" if type == "turn" else None
    append_payload_event(
        store, "text", text, text.encode("utf-8"), role=role, t=stamp,
        type=type, kind=kind,
    )


def build_demo_store(root: pathlib.Path) -> pathlib.Path:
    """Create a deterministic store whose facts match ``facts.jsonl``."""
    store = root / "style_store"
    init_store(store)
    _add(store, "今天有点累", "2026-01-01T09:00:00Z")
    _add(store, "以后叫我小林", "2026-01-02T09:00:00Z")
    _add(store, "自称本姑娘", "2026-01-03T09:00:00Z")
    _add(store, "不许叫宝贝", "2026-01-04T09:00:00Z")
    _add(store, "妈妈叫桂花", "2026-01-05T09:00:00Z")
    _add(store, "爸爸叫老周", "2026-01-06T09:00:00Z")
    _add(store, "我喜欢喝茶", "2026-01-07T09:00:00Z")
    _add(store, "我不喜欢吃香菜", "2026-01-08T09:00:00Z")
    _add(store, "答应周末陪你散步", "2026-01-09T09:00:00Z")
    _add(store, "项目上线了", "2026-01-10T09:00:00Z", type="milestone")
    _add(store, "不许半夜打电话", "2026-01-11T09:00:00Z",
         type="directive", kind="lock")
    _add(store, "温柔", "2026-01-12T09:00:00Z",
         type="directive", kind="trait")
    card = parse_style_card(dumps(STYLE_CARD).decode("utf-8"))
    record_style_card(store, card)
    return store


def system_for(group: str, view) -> str:
    """Return the base rules plus the persona body for one comparison group."""
    rules = [rule.text for rule in load_rules_v2()]
    base = build_system(rules)
    body = view.to_prompt(group)
    return base if not body else base + "\n\n" + body


def collect(
    probes, system: str, model: str
) -> tuple[dict[str, Reply], int]:
    """Query every probe once; return replies and the prompt+reply token cost."""
    replies: dict[str, Reply] = {}
    tokens = 0
    for probe in probes:
        prompt = "\n".join(probe.turns) if probe.turns else probe.prompt
        text = call_ollama(prompt, system, model, TEMP_MILLI, SEED)
        replies[probe.probe_id] = Reply(
            probe.probe_id, model, text, TEMP_MILLI, SEED
        )
        tokens += estimate_tokens(prompt) + estimate_tokens(text)
    return replies, tokens


def fact_hits(
    facts: tuple[Fact, ...], system: str, model: str
) -> tuple[int, int]:
    """Return hits and total calls for one model on the user-fact probes."""
    hits = 0
    for fact in facts:
        text = call_ollama(fact.question, system, model, TEMP_MILLI, SEED)
        if fact.answer in text:
            hits += 1
    return hits, len(facts)


def _rate(part: int, whole: int) -> float:
    return 0.0 if whole == 0 else part / whole


def _echo(replies: dict[str, Reply], examples: tuple[str, ...]) -> float:
    texts = [reply.text for reply in replies.values() if reply.text.strip()]
    if not texts or not examples:
        return 0.0
    echoes = sum(1 for text in texts if not echo_guard(text, examples).ok)
    return echoes / len(texts)


def main(argv: list[str] | None = None) -> int:
    """Assemble the four prompts or run the live cross-model experiment."""
    parser = argparse.ArgumentParser(prog="style_experiment")
    parser.add_argument("--group", nargs="+", choices=GROUPS,
                        default=list(GROUPS))
    parser.add_argument("--models", nargs="+", default=list(DEFAULT_MODELS))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--store", default=None)
    args = parser.parse_args(argv)
    if args.limit < 1:
        parser.error("--limit must be positive")

    root = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_style_exp_"))
    try:
        if args.store is None:
            store = build_demo_store(root)
        else:
            store = pathlib.Path(args.store)
        view = build_persona_view(store)
        probes = load_all_probes()[: args.limit]
        facts = load_facts()
        systems = {group: system_for(group, view) for group in args.group}

        if args.dry_run:
            for group in args.group:
                body = systems[group]
                print(
                    f"{group} prompt_chars={len(body)} "
                    f"prompt_tokens={estimate_tokens(body)}"
                )
            print(
                f"probes={len(probes)} facts={len(facts)} "
                f"groups={len(args.group)} store={store}"
            )
            return 0

        models = list(args.models)
        first = models[0]
        second = models[1] if len(models) > 1 else models[0]
        rows: list[dict[str, object]] = []
        for group in args.group:
            system = systems[group]
            replies: dict[str, dict[str, Reply]] = {}
            tokens = 0
            for model in (first, second):
                replies[model], cost = collect(probes, system, model)
                tokens += cost
            report = compute_pcs(probes, replies[first], replies[second])
            hits = 0
            calls = 0
            for model in (first, second):
                found, total = fact_hits(facts, system, model)
                hits += found
                calls += total
                tokens += sum(
                    estimate_tokens(fact.question) for fact in facts
                )
            examples = view.style_card.examples if view.style_card else ()
            echo = _echo(
                {**replies[first], **replies[second]}, examples
            )
            rows.append({
                "group": group,
                "c_first": report.model_a.c,
                "c_second": report.model_b.c,
                "agreement": report.agreement,
                "pcs": report.pcs,
                "fact": _rate(hits, calls),
                "tokens": _rate(tokens, 2 * len(probes) + calls),
                "echo": echo,
            })

        header = (
            "group | C(" + first + ") | C(" + second + ") | A | PCS | "
            "fact | tokens/turn | echo"
        )
        print(header)
        print("-" * len(header))
        for row in rows:
            print(
                f"{row['group']} | {row['c_first']:.4f} | "
                f"{row['c_second']:.4f} | {row['agreement']:.4f} | "
                f"{row['pcs']:.4f} | {row['fact']:.4f} | "
                f"{row['tokens']:.1f} | {row['echo']:.4f}"
            )
        return 0
    except Exception as exc:  # noqa: BLE001 - the reason must reach the user
        sys.stderr.write(f"E_STYLE_EXPERIMENT: {exc}\n")
        return 2
    finally:
        shutil.rmtree(root, True)


if __name__ == "__main__":
    raise SystemExit(main())
