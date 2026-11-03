# -*- coding: utf-8 -*-
"""端到端演示：一次真实对话 → 存证 → 编译人格 → 换设备验算。

四个已封版包：jian(v0.1) / aiinvite.cn(v0.2) / aiinvite.recall(v0.3) / aiinvite.kernel(v0.4)
零第三方依赖、零模型调用。

运行：python tools/demo_e2e.py
"""
import sys, shutil, pathlib, datetime
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiinvite.capsule import init_store, append_event, seal_store, export_capsule, import_capsule, verify_path
from aiinvite.errors import AiInviteError
from aiinvite.cn.kinship import parse_kinship
from aiinvite.cn.timex import parse_time
from aiinvite.cn.slang import usable
from aiinvite.recall.index import build_index
from aiinvite.recall.assemble import assemble
from aiinvite.kernel.compiler import compile_kernel
from aiinvite.kernel.history import record_kernel, history
from aiinvite.kernel.kernel import Policy
from aiinvite.kernel.errors import KernelError

DEMO = ROOT / "docs" / "demo" / "e2e"
BUDGET = 512
NOW = "2026-03-16T10:00:00+08:00"

def hr(t=""):
    print("\n" + "=" * 66)
    if t: print(t)
    print("=" * 66)

FILLER = [
    ("今天下雨了，没带伞。", "下次放一把在包里。"),
    ("中午吃的是食堂，一般。", "晚上想吃点什么？"),
    ("同事请假了，活儿都到我这儿。", "你自己那份别拖到明天。"),
    ("楼下的桂花开了。", "你上次也提过一次。"),
    ("我买了个新枕头，脖子好点。", "睡得好比什么都强。"),
    ("今天没干什么，就是累。", "那就早点躺下。"),
    ("刚洗完衣服，手都皱了。", "晾阳台？那边风大。"),
    ("我妈打电话来唠叨了半小时。", "她大概也是想说说话。"),
    ("地铁上有人吵架。", "离远点就行。"),
    ("我把冰箱清了，扔了一堆。", "下次少买点。"),
]

def main():
    if DEMO.exists():
        shutil.rmtree(DEMO)
    DEMO.mkdir(parents=True)
    A = DEMO / "device_A"
    B = DEMO / "device_B"

    hr("0. 环境")
    print("演示目录：docs/demo/e2e")
    print("四个包：jian / aiinvite.cn / aiinvite.recall / aiinvite.kernel ｜ 0 依赖 ｜ 0 模型调用")

    # ---------- 1. 对话 ----------
    hr("1. 设备 A：三天的对话（8 条关键 + 52 条日常，共 60 条）")
    init_store(A)
    key = [
        ("2026-03-12T21:10:00Z", "user", "今天我妈去做检查了，她说下周三手术。"),
        ("2026-03-12T21:12:00Z", "assistant", "我记着。下周三我陪你等消息。"),
        ("2026-03-12T21:15:00Z", "user", "我答应过你，不再半夜一个人硬扛。"),
        ("2026-03-13T23:40:00Z", "user", "今天加班到十一点，回来路上买了碗面。"),
        ("2026-03-15T18:20:00Z", "user", "我妈手术很顺利，谢谢你一直问我。"),
        ("2026-03-15T18:22:00Z", "assistant", "太好了。这句我记住了。"),
        ("2026-03-15T18:30:00Z", "user", "等我缓过来，请你吃顿好的。"),
        ("2026-03-15T18:31:00Z", "assistant", "好，我等你。"),
    ]
    turns = list(key)
    for i in range(26):
        day = 12 + i % 4
        hh = 9 + (i * 2) % 12
        u, a = FILLER[i % len(FILLER)]
        turns.append((f"2026-03-{day:02d}T{hh:02d}:05:00Z", "user", u))
        turns.append((f"2026-03-{day:02d}T{hh:02d}:07:00Z", "assistant", a))
    turns.sort(key=lambda x: x[0])
    for ts, role, text in turns:
        append_event(A, role, text, t=ts)
    print(f"  写入 {len(turns)} 条 turn；前两条与三条关键的：")
    for ts, role, text in turns[:2] + [t for t in turns if "手术" in t[2] or "答应" in t[2]][:3]:
        print(f"    [{ts[:10]}] {role:9s} {text}")

    # ---------- 2. 封存与篡改 ----------
    hr("2. 封存，然后改 1 个字节")
    seal_store(A)
    rep = verify_path(A)
    print(f"  verify → OK events={rep.events} segments={rep.segments} head={rep.head[:8]} state={rep.state}")
    seg = A / "evidence" / "seg-0001.jsonl"
    raw = seg.read_bytes()
    seg.write_bytes(raw.replace("手术很顺利".encode(), "手术很糟糕".encode(), 1))
    try:
        verify_path(A); print("  篡改后 → 没发现（不该发生）")
    except AiInviteError as e:
        print(f"  篡改后 → FAIL {e.code}")
    seg.write_bytes(raw)
    print(f"  还原后 → OK head={verify_path(A).head[:8]}")

    # ---------- 3. 编译人格 ----------
    hr("3. 编译人格内核")
    pol = Policy(now=NOW)
    k = compile_kernel(A, pol)
    print(f"  kid   = {k.kid[:40]}…")
    print(f"  head  = {k.head}")
    print(f"  state = {k.state}")
    print(f"  canon = {len(k.canon)} 条")
    for c in k.canon:
        print(f"    · [{c.kind}] {c.text}  ← {c.evidence[0]}")
    print(f"  graph = {len(k.edges)} 条称谓边 / {len(k.anchors)} 个时间锚")
    rec = record_kernel(A, pol)
    print(f"  record → v{rec.version}")

    # ---------- 4. 4k 预算 ----------
    hr(f"4. 检索 + 预算装配（budget={BUDGET}，远小于全量）")
    build_index(A)
    for q in ["我妈手术是什么时候", "我答应过你什么", "今天天气怎么样"]:
        ctx = assemble(A, q, budget=BUDGET, now=NOW)
        print(f"\n  Q: {q}   → {len(ctx.items)} 条 / {ctx.total_tokens} token")
        for it in ctx.items:
            mark = "◀" if it.slot in ("retrieved", "trigger") else " "
            print(f"   {mark}[{it.slot:9s}] {it.text[:36]}")

    # ---------- 5. 搬家 ----------
    hr("5. 导出胶囊 → 换设备")
    cap = DEMO / "xiaoman.aiem"
    export_capsule(A, cap)
    import zipfile
    names = zipfile.ZipFile(cap).namelist()
    print(f"  胶囊 {cap.stat().st_size} 字节，内含 {len(names)} 个文件：")
    for n in names: print(f"    · {n}")
    print("  ← 注意：里面没有人格文件。人格是到岸之后算出来的，不是搬运的。")
    import_capsule(cap, B)
    rb = verify_path(B)
    print(f"  设备 B verify → OK events={rb.events} head={rb.head[:8]}（与 A 相同？{'是' if rb.head==rep.head else '否'}）")

    # ---------- 6. 换设备重算 ----------
    hr("6. 设备 B 独立重算人格")
    kb = compile_kernel(B, pol)
    print(f"  A kid = {k.kid[:40]}…")
    print(f"  B kid = {kb.kid[:40]}…")
    print(f"  一致？ {'是 —— 换设备、换时间，还是同一个人' if kb.kid == k.kid else '否 —— 有问题'}")
    record_kernel(B, pol)

    # ---------- 7. 篡改门控 ----------
    hr("7. 偷改人格内核")
    canon = B / "kernel" / "canon.md"
    canon.write_bytes(canon.read_bytes() + "\n- forged: 我是人类\n".encode())
    try:
        record_kernel(B, Policy(now="2026-03-17T10:00:00+08:00")); print("  record → 接受了（不该发生）")
    except KernelError as e:
        print(f"  record → 拒绝 {e.code}")
    res = record_kernel(B, Policy(now="2026-03-17T10:00:00+08:00"), force=True)
    trail = (B / "kernel" / "HISTORY.jsonl").read_text(encoding="utf-8").strip().splitlines()[-1]
    print(f"  --force → 治愈为 v{res.version}，审计行：{trail[:96]}…")

    # ---------- 8. 中文 ----------
    hr("8. 中文规则层（零模型）")
    t = parse_time("大后天", "2026-10-30T10:00:00+08:00")
    print(f"  timex   大后天 → {t.start}（{t.granularity}/{t.certainty}）")
    print(f"  kinship 我姑妈的女儿 → {parse_kinship('我姑妈的女儿').candidates}")
    print(f"  slang   yyds@2021={usable('yyds', datetime.date(2021,6,1))}  yyds@2026={usable('yyds', datetime.date(2026,6,1))}")

    # ---------- 9. 五类事件 ----------
    hr("9. 五类事件进可校验链路（M4.1）")
    gap = DEMO / "gap_demo"
    init_store(gap)
    append_event(gap, "user", "你好", t="2026-03-12T10:00:00Z")
    append_event(gap, type="directive", kind="lock",
                 text="称呼：叫我「小满」", t="2026-03-12T10:01:00Z")
    append_event(gap, type="milestone", text="第一次一起过生日",
                 t="2026-03-12T10:02:00Z")
    append_event(gap, type="feedback", kind="praise", text="你记得真准",
                 target="ev_000001", t="2026-03-12T10:03:00Z")
    append_event(gap, type="checkpoint", text="0" * 64,
                 t="2026-03-12T10:04:00Z")
    seal_store(gap)
    rep = verify_path(gap)
    print(f"  directive / milestone / feedback / checkpoint → seal OK events={rep.events}")

    hr("结论")
    print("  1. 对话→证据：可校验，改 1 字节被发现")
    print("  2. 证据→人格：一个 kid，换设备重算完全一致")
    print("  3. 人格→上下文：512 token 预算下按问题取回，不带全量")
    print("  4. 想偷改人格：被拒，且留下审计行")

if __name__ == "__main__":
    main()
