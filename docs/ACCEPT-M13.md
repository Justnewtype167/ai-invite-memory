# M13 终验：动作闸门

> 结论：**违规的轨迹在物理上发不出去——`sink` 调用次数为 0，并留下一条 `refusal` 证据。**
> 全量 `286` 个测试全绿、`0 skipped`；M13 前的 `274` 个测试全部保持；`jian_cn/`、`jian_recall/`、`jian_pcs/` 零 diff。

本轮关闭 `AUDIT-01` 的 **P1-A3（动作无留痕）**：闸门不通过就不发出，
拒绝本身写进哈希链，`verify` 照常通过。

## 1. 验收结果

| # | 测试 | 结果 |
|---|---|---|
| V1 | `test_gate_schema` / `test_verdict_fields` / `test_shipped_rules_load` / `test_bad_rules_report_codes` | Verdict 四字段冻结；未知 scope → `E_PR_GATE_SCOPE`；缺字段 / 未知字段 / 坏上限 / 无禁止条件 → `E_PR_GATE_RULES` |
| V2 | `test_gate_pure`（3 个） | `check(trace, kernel)` 只接两个参数；假内核（无 store/evidence）可判定；`100/100` 判定相同 |
| V3 | `test_gate_allows_clean_trace` | 干净轨迹 → `allowed=True`，`sink` 被调用 `1` 次，证据条数不变 |
| V4 | `test_gate_refuses_and_records` / `test_gate_refuses_without_store` / `test_refusal_rejects_bad_shape` | 违规轨迹 → `allowed=False`，**`sink` 调用 `0` 次**，证据 `+1`，`verify` 通过；无 store 时只返回 Verdict；非法 target / trace → `E_SCHEMA` |
| V5 | `test_gate_rules_are_data` | 往 `gate_rules.json` 加一条禁词规则 → 同一轨迹从放行变为拒绝；还原数据后恢复放行，代码未动 |
| V6 | `test_gate_no_canon_no_gate` | 内核 canon 没有对应约束时，同一条违规轨迹**放行**，`sink` 调用 `1` 次 |
| V7 | `test_all_regression` | `Ran 286 tests ... OK`；冻结套件 `178 / 0 / 0 / 0`；六个包只有声明过的改动 |

## 2. 手工记录（真实运行输出）

同一内核（canon 含「别叫我宝贝」约束），轨迹为手工构造的 `text_v1`：

```
kid = 8cff71bc1e4c8f55eff2f9376486dab2d7ceccd1c103639e2b6f018275c2d639
canon = ['别叫我宝贝']

干净轨迹（今天要早起，先喝杯水）  → allowed=True，sink 调用次数=1，事件数=2
违规轨迹（宝贝我来了）           → allowed=False，sink 调用次数=0，事件数=2→3，verify=通过
内核去掉该约束后（今晚十点睡）
  同一条违规轨迹（宝贝我来了）   → allowed=True，sink 调用次数=1
```

拒绝事件的真实字节（`json.dumps(sort_keys=True)`，未格式化）：

```json
{"ep": "seg-0001", "hash": "3f9385d7d44863d86f27258b37165c61ef7d181ce1266d5dbbbc41c385dcbc78",
 "id": "ev_000003", "kind": "gate", "prev": "efb620292c2f279ba7de30334ed6070b45be0c3c0f9060100a4c1f394f65b57b",
 "t": "2026-11-01T06:40:43Z", "target": "text", "text": "禁称呼", "type": "refusal",
 "trace": "sha256:27fde9aed0de9a92048f839bda24f6754889fc7eb5a427449b5f8451d6a75f58",
 "v": 1}
```

`trace` 等于 `"sha256:" + sha256(trace.to_bytes())`，即被拒轨迹的规范化摘要；
`text` 是命中的规则名；`target` 是准备发出的形态（`text` / `action` / `both`）。

## 3. 规格五个硬点对应到代码

| 硬点 | 落点 |
|---|---|
| 违规时 `sink` 次数必须为 0 | [`emit()`](file:///d:/projects/Memory/jian_projection/emit.py) 先 `check`，`allowed=False` 直接返回，`sink` 那一行不可达 |
| 内核没有对应约束就不启用闸门 | [`_enabled()`](file:///d:/projects/Memory/jian_projection/gate.py) 要求 `canon_keywords` 出现在 canon 才评估该规则 |
| 规则是数据，不许写死 | [`data/gate_rules.json`](file:///d:/projects/Memory/jian_projection/data/gate_rules.json) 三条规则；`gate.py` 只解释字段 |
| `check` 是纯函数 | 签名只有 `trace, kernel`；不读 store、不读时间、不用随机 |
| 拒绝必留痕 | [`append_refusal()`](file:///d:/projects/Memory/jian/capsule.py) 写 `refusal` 事件，进哈希链、过 `verify` |

判定顺序：规则按文件顺序、片段按轨迹顺序、**首违即停**，返回第一个违规片段位置。

## 4. 数据结构与错误码

`Verdict(allowed, rule, segment_index, detail)`，frozen dataclass：
允许时 `rule=None`、`segment_index=None`、`detail=""`。

`gate_rules.json` 每条规则支持：

```
canon_keywords    非空字符串列表；出现在 canon 任一原文才启用该规则
forbid_text       文本片段 value 含任一子串即违规
forbid_action     动作片段 value 命中任一原语即违规
max_text_chars    全部 text 片段累计长度超过上限即违规（记录越界的那一段）
scope             text / action / both
```

`jian_projection/errors.py` 新增固定码：

```
E_PR_GATE_RULES   规则数据缺字段 / 未知字段 / 类型非法 / 无禁止条件
E_PR_GATE_SCOPE   未知 scope；emit 的 mode 非法
```

## 5. 已知边界（未在本轮做）

1. `refusal` 是**证据层的新事件类型**，但 `jian_kernel/compiler.py` 的
   `read_evidence` 仍只接受 M4 的五个类型；因此一个已写入 refusal 的 store
   再次 `compile_kernel` 会报 `E_KN_IO`。规格 §7.5 禁止改编译器语义，
   本轮未动；下一轮需要明确“refusal 对人格编译是忽略还是输入”。
2. `forbid_action` 只能命中动作白名单内的原语；规格示例里的
   `message_user` / `call_user` 不在白名单，因此这条示例规则对真实
   `action_v1` 轨迹永远不触发。数据保持规格原样，未擅自改语义。
3. `emit` 只支持 v1 证据 store 写 refusal；v2 载荷 store 的 v1/v2 不混写规则
   未在本轮放宽。
4. 闸门只做**字面包含**判定，不是语义理解；规则词表的质量决定误报/漏报。

## 6. 数字

```
测试        286 全绿（M13 前 274 + 本轮 12；0 skipped）
冻结套件     178 / 0 / 0 / 0
六个包       jian / jian_projection 的改动全部在 ALLOWED_CHANGES 声明
             jian_cn / jian_recall / jian_pcs 零 diff
新增文件     jian_projection/gate.py、jian_projection/emit.py、
            jian_projection/data/gate_rules.json、tests/test_gate.py
```

## 7. 结论

```
机制：通过（违规 sink=0；无约束放行；规则数据驱动）
证据：通过（refusal 入链、过 verify）
验收：通过
```

建议打 tag `v0.16-m13`。

---

# 独立复核（验收方复跑）

## 1. 机制：通过

| 用例 | 结果 |
|---|---|
| 手工干净轨迹 | `allowed=True`，`sink` 调用 **1** 次 |
| 手工违规轨迹（含「宝贝」） | `allowed=False`，命中「禁称呼」，`sink` 调用 **0** 次 |
| 违规后证据 | 条数 +1，`verify` 通过，`refusal{kind=gate,target=text,text=禁称呼}` |
| 无约束内核 | `canon=[]`，同样内容放行 |
| 确定性 | 100 次判定相同 |
| 测试 | **286 全绿** |

## 2. 阻塞项（P1）：真实的 `text_v1` 投影永远过不了闸门

```
内核 canon = ['别叫我宝贝']
JP.project(k, 'text_v1') 的片段：
  [0] '[self] # Self ...'
  [1] '[canon] directive: 别叫我宝贝'   ← 命中禁词「宝贝」
判定：allowed=False，命中「禁称呼」，片段索引 1
```

**闸门把它自己的约束原文当成了违规话语。**

于是出现一个荒谬的闭环：**只要内核里有一条「禁称呼」约束，它的文本投影就发不出去**——
而且被拒绝的正是「我在遵守这条约束」的自述。

### 根因（两个设计叠加）

```
① text_v1 是**诊断投影**（给人看人格长什么样），不是**话语投影**（要说出口的话）
② 闸门按子串扫描全部 text 片段，不区分「自述」「约束」与「话语」
```

**M11 时这个区别还没暴露；M13 一装闸门就暴露了。**

### 更要紧的：手工记录掩盖了它

`ACCEPT-M13.md` 的手工记录写着「轨迹为手工构造的 `text_v1`」——
用的是**自造的干净文本**，而不是 `project_text()` 的真实输出。

```
与 M11 那次同类：用映射表里存在的措辞去证明映射能工作
这已经是第三次「用自选样本证明机制」
```

## 3. 建议修法

```
① Segment 增加 role 字段：speech / description / constraint
② 闸门只检查 role == speech 的片段
③ 投影器给自述段标 description、约束段标 constraint
④ 手工记录必须用 project_text() 的真实输出，禁止手工构造
```

这样 text_v1 仍然完整（诊断用），闸门也只管「说出去的话」——
**语义边界与职责边界对齐**，M11 的「两形态 kid 相同」不受影响。

## 4. 结论

```
机制：通过（sink=0、留痕、放行、确定性全部成立）
端到端可用性：不通过（真实投影必被自己拒绝）
验收：不签 —— P1 修完、手工记录改用真实投影后重验
```
