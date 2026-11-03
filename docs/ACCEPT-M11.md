# M11 终验：轨迹与双投影

> 结论：**同一份 kid，驱动两段完全不同的轨迹，kid 不变。**
> 全量 `264` 个测试全绿、`0 skipped`；五个既有包零 diff。

本轮修掉了首版验收暴露的硬伤：`action_v1` 曾用整句匹配，用户的自由输入必然落空。
现在匹配走**数据文件里的关键词词表**，并且 `_default` 兜底——空轨迹只可能来自空 canon。

## 1. 验收结果

| # | 测试 | 结果 |
|---|---|---|
| T1 | `test_trace_schema` | 非法 kind / 空 segments / 缺 kid / 缺 dur_ms / 未知动作 / 非法 source → 各报对应 `E_PR_*` |
| T2 | `test_projection_pure` | projector 签名只有 `kernel`；假内核对象可投影（无 store / evidence 属性） |
| T3 | `test_kid_unchanged` | 投影前后 `kernel.kid` 不变，两条轨迹的 `kid` 都等于它 |
| T4 | `test_determinism` | 同一内核投影 `100/100` 字节相同；跨进程也相同 |
| T5 | `test_two_forms_differ` | `text_v1` 与 `action_v1` 的 segments 不同，`kid` 相同 |
| T6 | `test_action_map` | 关键词词表合法；每条规则都能投影；未命中走 `_default`；空 canon 才报 `E_PR_EMPTY` |
| T7 | 全量回归 | `Ran 264 tests ... OK`，冻结套件 `178 / 0 / 0 / 0`；五个既有包零 diff |

## 2. 手工记录（用真实风格指令，非映射表原句）

四个 `directive/lock` 事件：`说话短一点`、`别老夸我`、`不用每次都问我在干嘛`、`别叫我宝贝`
（另加一条普通对话作为证据），`Policy(now=2026-10-29T10:00:00+08:00)`。

```
kid = f6b7eb2c538c700fdb8c443060209c0c8f21d501fc81bfd835dbaa2eaa4b7ac9
canon = 4

canon 规则 → 命中规则
  说话短一点                → 简短
  别老夸我                  → 不夸
  不用每次都问我在干嘛        → 不追问
  别叫我宝贝                → 不称呼
关键词命中率：4 / 4

text_v1   → 片段数 5
            首段 kind=text，source=None
            value="[self] # Self\n\n- known_days: 301\n- events: 5\n
                    - active_months: 1\n- top_kinship: -\n- latest_milestone: -"
            末段 "[canon] directive: 别叫我宝贝"

action_v1 → 片段数 5
            action hold         400ms  source=说话短一点
            action neutral_face 400ms  source=别老夸我
            action step_back    500ms  source=不用每次都问我在干嘛
            wait                600ms  source=不用每次都问我在干嘛
            action hold         400ms  source=别叫我宝贝

轨迹字节是否不同：True
  text_v1   sha256 = c912a15f58ffc419bbb8989ba690887a9d6b74cb833ff913d8e9d1c1e58dcb87（728 字节）
  action_v1 sha256 = dc05aad18548115d6af093817ae818cb8da0e46274ebead52622eb38f2e777db（510 字节）
```

`_default` 的独立探针（不属于上面四条规则）：未命中的 `别老叹气` →
`action idle 500ms`，不报错。

这就是「地基通用」的第一份实证：**换了形态，轨迹变了，身份没变。**
首版记录用的三条措辞恰是映射表原句，属于循环论证；本记录改用用户自由输入，
并给出真实命中率。

## 3. 四个不变量对应到代码

| 不变量 | 落点 |
|---|---|
| I1 投影只读内核 | `aiinvite.projection/__init__.py` 只接收 `kernel` 与投影器名；`project_text` / `project_action` 签名只有 `kernel` |
| I2 投影不改身份 | `Kernel` 本身是 frozen dataclass；投影只读 `kid` / `self_md` / `canon` |
| I3 确定性 | `Trace` 不含时间戳、路径、证据；序列化复用 `aiinvite.canonical.dumps`，浮点禁用 |
| I4 形态分离 | 两个投影器输出不同 segments，但 `Trace.kid` 都来自同一个内核 |

## 4. 数据结构与错误码

`Segment(kind, value, dur_ms, source=None)`：`source` 记录该动作/文本来自哪条 canon 原文，
为将来把 PCS 定义到轨迹上留锚点。序列化字段固定为
`{"dur_ms","kind","source","value"}`。

`aiinvite.projection/errors.py` 的固定码：

```
E_PR_SCHEMA              非法片段类型 / 字段类型 / segments 非元组
E_PR_EMPTY               空轨迹；action_v1 仅在内核 canon 为空时抛
E_PR_MISSING_KID          缺 kid
E_PR_UNKNOWN_PROJECTOR   未知投影器
E_PR_UNKNOWN_ACTION      动作不在五元白名单
E_PR_BAD_DURATION        dur_ms 缺失 / 非整数 / 越界 1..60000
E_PR_MAP_INVALID         映射表结构、keywords 或动作非法
```

## 5. 已知边界（未在本轮做）

1. 关键词匹配是**数据驱动的字面包含**，不是语义理解。词表覆盖了常见风格概念，
   未覆盖的措辞走 `_default`（`idle 500ms`）——永不空转，但动作可能不贴切。
2. 映射表与词表的扩充只改 `aiinvite.projection/data/action_map.json`，不改代码。
3. 动作只到“原语 + 时长”，没有真机驱动、没有语音、没有模型调用。
4. `Trace` 尚无解析器（`from_bytes`）；本轮只证明“能稳定产出”。

---

# M11 终验（通过，待打 tag）

> 264 测试全绿；P1 已修，我用**上次失败的那组真实指令**复跑通过。

## 1. P1 修复的独立复核（这是关键）

用的不是实现的测试，而是**我上一轮报失败的那组输入**：

| 用例 | canon | action_v1 | 结果 |
|---|---|---|---|
| 真实风格 4 条 | 4 | hold / neutral_face / step_back+wait / hold | ✅ 5 段，kid 一致 |
| 映射表外（别那么正式 / 更喜欢随意） | 2 | idle / idle | ✅ 走 `_default`，不报错 |
| 空 canon | 0 | — | ✅ `E_PR_EMPTY`（唯一合法失败） |

**语义也对得上**：

```
说话短一点              → hold（简短）
别老夸我                → neutral_face（不夸）
不用每次都问我在干嘛      → step_back + wait（不追问）
别叫我宝贝              → hold（不称呼）
```

## 2. 手工记录已重做（不再是循环论证）

| 项 | 首版 | 现在 |
|---|---|---|
| 输入 | 映射表原句 | **用户自由输入** |
| 命中率 | 未报告 | **4 / 4，明确写出** |
| `_default` | 未测 | **独立探针：`别老叹气` → `idle 500ms`** |
| `source` 溯源 | 无 | **每段带 `source=<canon 原文>`** |

并且明确写了：「首版记录用的三条措辞恰是映射表原句，属于循环论证」。

## 3. 顺带采纳的 P2

`Segment.source` 已加上，动作轨迹现在能追到「这个动作来自哪条 canon」。
这是将来把 PCS 定义到轨迹上的前置条件。

## 4. 数字

```
测试        264 全绿（255 + 9）
冻结套件     178 / 0 / 0 / 0
五个既有包   零 diff
投影测试     9 个（含新增 test_unmatched_rule_uses_default）
```

## 5. 结论

```
机制：通过（四条不变量）
可用性：通过（真实内核可投影，未命中不空转）
验收：通过
```

## 6. 建议

打 tag `v0.14-m11`。

下一步（M12）建议转向**增量编译 + 对账**：
实时与具身形态下，连续流无法承受每次全量重算。
