# TASK-15 · 轨迹与双投影（M11）

> 目标只有一句：**同一份 kid，驱动两段完全不同的输出，kid 不变。**
> 这是「地基与形态无关」的第一个实证。

写前已过 `docs/SPEC-CHECKLIST.md` 十问；约束 C14（绝对时延不进单测门禁）适用。

---

## 0. 一句话与边界

```
做    从内核到「轨迹」的确定性投影契约 + 两个形态完全不同的投影器
不做  不接模型、不生成自然语言、不做语音合成、不做真机驱动
```

**为什么现在不做真的输出**：接了模型就无法断言确定性，
而本轮要证明的恰恰是**确定性不随形态改变**。

---

## 1. 新增包：`aiinvite.projection/`

```
aiinvite.projection/
  __init__.py      对外导出 Trace / project
  trace.py         Trace 与 Segment 的数据结构、序列化、校验
  text.py          文本投影器
  action.py        动作投影器
  errors.py        E_PR_* 错误码
  data/action_map.json   人格规则 → 动作原语的映射表
```

**不放进 `aiinvite.kernel/`**：投影属于 L2，内核属于 L1，混在一起会让「内核不依赖形态」这句失效。

---

## 2. Trace 契约

```python
@dataclass(frozen=True)
class Segment:
    kind: str          # text | action | wait
    value: str         # 文本片段 / 动作原语名
    dur_ms: int | None # action/wait 必填，text 为 None

@dataclass(frozen=True)
class Trace:
    kid: str           # 产生它的内核身份，必须原样带上
    projector: str     # text_v1 | action_v1
    segments: tuple[Segment, ...]
```

| 规则 | 说明 |
|---|---|
| `kid` 必填且来自内核 | 轨迹必须能回答「我是从哪个人格投影出来的」 |
| `segments` 非空 | 空轨迹视为投影失败（`E_PR_EMPTY`） |
| `kind` 白名单 | `text` / `action` / `wait`；其余 `E_PR_SCHEMA` |
| `action` 的 `value` 必须在动作白名单内 | `E_PR_UNKNOWN_ACTION` |
| `dur_ms` | `action`/`wait` 必填，`1..60000` |
| 序列化 | 规范化 JSON（复用 `aiinvite.canonical`），浮点禁用 |

**关键**：`Trace` 不含任何证据字段，也不含时间戳——**同一内核两次投影必须字节相同**。

---

## 3. 两个投影器

### 3.1 `text_v1`（文本形态）

```
输入  内核（self.md / canon.md / state）
输出  若干 text 片段：人格自述 + 行为约束清单
特点  长、语义密集、给人读
```

### 3.2 `action_v1`（具身形态）

```
输入  内核的 canon 条目（不可变人格约束）
输出  若干 action / wait 片段：一段可执行的动作序列
映射  由 data/action_map.json 给出，规则 → 动作原语，可审计、可替换
特点  短、离散、给机器执行
```

**映射表示例**（初稿，实现方可建议增补，但必须走规格变更）：

```json
{
  "不主动联系": {"segments": [{"kind": "wait", "dur_ms": 3000}]},
  "先复述":     {"segments": [{"kind": "action", "value": "nod", "dur_ms": 600},
                             {"kind": "wait", "dur_ms": 800}]},
  "不评价":     {"segments": [{"kind": "action", "value": "neutral_face", "dur_ms": 400}]}
}
```

动作白名单（固定五个）：`nod` / `step_back` / `neutral_face` / `hold` / `idle`。

---

## 4. 四条不变量（本轮真正要证明的）

```
I1  投影只读内核：投影器签名不接收证据目录，也不接收 store
I2  投影不改身份：投影前后 kernel.kid 不变（内核是不可变的）
I3  确定性：同一内核 + 同一投影器 → 轨迹字节相同
I4  形态分离：同一内核 + 不同投影器 → 轨迹不同（且都能通过 schema 校验）
```

**I3 与 I4 合起来才是 P1**：换了形态，轨迹变了，身份没变。

---

## 5. 验收（七个）

| # | 测试 | 断言 |
|---|---|---|
| T1 | `test_trace_schema` | Segment/Trace 校验；非法 kind、空 segments、缺 kid、缺 dur_ms、未知动作 → 各报对应错误码 |
| T2 | `test_projection_pure` | `project(kernel, "text_v1")` 只接收内核对象；用假内核对象也能跑（证明不碰 store） |
| T3 | `test_kid_unchanged` | 投影前后 `kernel.kid` 不变；两次投影的 `trace.kid` 都等于该 kid |
| T4 | `test_determinism` | 同一内核投影 100 次 → 规范化 JSON 字节完全相同（跨进程同样成立） |
| T5 | `test_two_forms_differ` | 同一内核：`text_v1` 与 `action_v1` 的 segments 不相同；两者的 `kid` 相同 |
| T6 | `test_action_map` | 映射表引用的动作全部在白名单；每条 canon 规则都能投影；未命中的规则被忽略且不报错 |
| T7 | `test_all_regression` | 现有 **255 个测试仍全绿**；冻结包零 diff（`aiinvite.cn/`、`aiinvite.recall/`、`aiinvite.pcs/`），`aiinvite/` 与 `aiinvite.kernel/` 若改动必须在 `ALLOWED_CHANGES` 声明 |

---

## 6. 禁止

1. 不许调用模型、不许联网、不许随机
2. 不许投影器接收 store 路径或读证据（只给内核对象）
3. 不许在 Trace 里放时间戳、路径、环境信息（会破坏 T4）
4. 不许改 `aiinvite/`、`aiinvite.kernel/`、`aiinvite.cn/`、`aiinvite.recall/`、`aiinvite.pcs/`
5. 不许把动作映射写死在代码里（必须走 `data/action_map.json`）

---

## 7. 完成定义

```
python -m unittest discover -s tests -v      # 全绿、0 skipped
```

并提交一段手工记录（写进 `docs/ACCEPT-M11.md`）：

```
同一份内核：
  kid = ?
  text_v1   → 片段数 ?，首段 ?
  action_v1 → 片段数 ?，首段 ?
  轨迹字节是否不同：?
```

**这段记录就是「地基通用」的第一份实证材料**，将来论文与对外说明都用它。

