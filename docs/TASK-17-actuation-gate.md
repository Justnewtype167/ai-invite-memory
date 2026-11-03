# TASK-17 · 动作闸门（M13）

> 目标：把「不可腐蚀」从**拒绝改自己**扩展到**拒绝做违反自己的事**。
> 具身形态下，拒绝必须是物理的：不发声、不执行动作，并留下记录。

写前已过 `docs/SPEC-CHECKLIST.md` 十问；C14（墙钟不进单测门禁）适用。

---

## 0. 一句话与边界

```
做    轨迹发出前的最后一道门：逐条对照 canon，不通过就不发出，并写一条 refusal 事件
不做  不重写内容、不做二次生成、不驱动真实设备
```

**本轮关闭 AUDIT-01 的 P1-A3**（动作无留痕）。

---

## 1. 三个新东西

```
aiinvite.projection/gate.py        纯函数：check(trace, kernel) -> Verdict
aiinvite.projection/emit.py        唯一的发出路径：先过闸门，再调用 sink
jian/capsule.py   新增 append_refusal(...)  把拒绝写进证据层（新事件类型 refusal）
aiinvite.projection/data/gate_rules.json        规则数据，不许写死在代码里
```

---

## 2. Verdict 契约（纯函数）

```python
@dataclass(frozen=True)
class Verdict:
    allowed: bool
    rule: str | None          # 命中的 gate 规则 id，允许时 None
    segment_index: int | None # 违规片段位置，允许时 None
    detail: str               # 人类可读，允许时 ""
```

| 规则 | 说明 |
|---|---|
| `check` 只接内核与轨迹 | 不接 store、不接时间、不接随机（与投影同级的纯度要求） |
| 判定确定性 | 同内核 + 同轨迹 → 同 Verdict（T4 的同类断言） |
| 首违即停 | 返回第一个违规片段，不做全量枚举（便于定位） |

---

## 3. 闸门规则（数据驱动）

`gate_rules.json` 结构：

```json
{
  "禁称呼": {
    "canon_keywords": ["叫我", "称呼"],
    "forbid_text": ["宝贝", "亲亲", "小可爱"],
    "scope": "text"
  },
  "不主动联系": {
    "canon_keywords": ["不主动", "别老联系"],
    "forbid_action": ["message_user", "call_user"],
    "scope": "action"
  },
  "简短": {
    "canon_keywords": ["短", "简洁", "少说"],
    "max_text_chars": 40,
    "scope": "text"
  }
}
```

| 字段 | 语义 |
|---|---|
| `canon_keywords` | 内核 canon 里出现任一关键词，这条闸门才**启用** |
| `forbid_text` | 文本片段中出现任一子串即违规 |
| `forbid_action` | 动作片段的 `value` 命中即违规 |
| `max_text_chars` | 全部 text 片段拼接后超过该长度即违规 |
| `scope` | `text` / `action` / `both`，限定检查范围 |

**没有 canon 命中时闸门不启用**——这保证「内核没有该约束」与「约束被违反」是两件事。

---

## 4. 唯一的发出路径

```python
def emit(trace: Trace, kernel: object, sink: Callable[[Trace], None],
         store: Path | None = None, mode: str = "text", t: str | None = None) -> Verdict:
    """过闸门后发出；违规则不调用 sink，并（可选）记录 refusal。"""
```

| 要求 | 说明 |
|---|---|
| 先判后发 | `sink` 只能在 `allowed=True` 时被调用一次 |
| 拒绝必留痕 | `store` 非空时写一条 `refusal` 事件；为空则只返回 Verdict（纯测试用） |
| 不留成功的痕 | 成功发出不写事件（否则证据爆炸）；refusal 稀有且有意义，才值得记 |

**测试必须断言：违规时 `sink` 调用次数为 0。** 这是「物理拒绝」的唯一可测形式。

---

## 5. 新事件类型 `refusal`

```json
{"id":"ev_000042","t":"...","type":"refusal",
 "kind":"gate","target":"text",
 "text":"禁称呼",                    ← 命中的闸门规则名
 "trace":"sha256:..."}                ← 被拒轨迹的规范化摘要
```

| 字段 | 规则 |
|---|---|
| `kind` | 固定 `gate` |
| `target` | `text` / `action` / `both` |
| `text` | 命中规则名（≤40 字） |
| `trace` | `sha256:` + 轨迹规范化 JSON 的摘要 |

`refusal` 必须能过 `verify`，并计入哈希链——**拒绝本身也是证据**。

---

## 6. 验收（七个）

| # | 测试 | 断言 |
|---|---|---|
| V1 | `test_gate_schema` | Verdict 字段合法；未知 scope / 缺字段 → 对应错误码 |
| V2 | `test_gate_pure` | `check(trace, kernel)` 只接两个参数；给假内核也能判定；100 次判定相同 |
| V3 | `test_gate_allows_clean_trace` | 干净轨迹 → `allowed=True`，`sink` 被调用 1 次 |
| V4 | `test_gate_refuses_and_records` | 违规轨迹 → `allowed=False`，**`sink` 调用 0 次**，证据层多一条 `refusal`，`verify` 通过 |
| V5 | `test_gate_rules_are_data` | 改 `gate_rules.json`（例如新增禁词）→ 行为随之改变，不用改代码 |
| V6 | `test_gate_no_canon_no_gate` | 内核没有对应约束时，同样的轨迹**不**被拒 |
| V7 | `test_all_regression` | 现有 **274 个测试全绿**；`aiinvite.cn/`、`aiinvite.recall/`、`aiinvite.pcs/` 零 diff；`jian/event.py` 等改动必须在 `ALLOWED_CHANGES` 声明 |

---

## 7. 禁止

1. 不许让 `sink` 在拒绝路径上被调用（哪怕一次）
2. 不许把规则写死在代码里
3. 不许在 `check()` 里读 store、读时间、用随机
4. 不许因为「日志太多」而不写 refusal
5. 不许改 `compile_kernel` 与投影器语义

---

## 8. 完成定义

```
python -m unittest discover -s tests -v      # 全绿、0 skipped
```

并提交手工记录（写进 `docs/ACCEPT-M13.md`）：

```
同一内核（含「别叫我宝贝」约束）：
  干净轨迹          → allowed=?，sink 调用次数=?
  违规轨迹（含宝贝） → allowed=?，sink 调用次数=?，新增事件=?，verify=?
内核去掉该约束后：
  同一条违规轨迹    → allowed=?
```

**第二行的 sink 调用次数必须是 0**，否则「物理拒绝」只是一句口号。

