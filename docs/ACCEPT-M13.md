# M13 终验：动作闸门（第二次验收）

> 结论：**真实 `text_v1` 投影不再被自己的约束拦住；真实 `action_v1` 违规轨迹发不出去，`sink=0` 并留下 `refusal` 证据。**
> 全量 `286` 个测试全绿、`0 skipped`；`jian_cn/`、`jian_recall/`、`jian_pcs/` 零 diff。

## 0. 第一次验收为什么没签

第一次的手工记录用的是**手工构造**的轨迹，掩盖了一个真实缺陷：

```
内核 canon = ['别叫我宝贝']
project_text -> '[self] …' + '[canon] directive: 别叫我宝贝'
闸门按子串命中「宝贝」 -> 拒绝
```

结果就是「我在遵守这条约束」这句话被这条约束拦住，真实 `text_v1` 投影永远过不了闸门。
根因不是规则词表，是**闸门不区分「自述 / 约束 / 话语」**。

## 1. 修法与三处改动

1. `Segment` 增加 `role` 字段：`speech` / `description` / `constraint`（默认 `speech`）。
2. `project_text`：自述段标 `description`，约束段标 `constraint`。`project_action` 的
   动作 / 等待段保持 `speech`（那就是要发出的动作本身）。
3. 闸门只检查 `role == "speech"` 的片段；`description` / `constraint` 不参与文本禁词与长度判定。

> 契约变化：`Segment.to_payload()` 现在包含 `role`，`Trace.to_bytes()` 的字节随之变化。
> 这是规格要求的显式变更，不是投影结果漂移；同一内核仍逐字节可复现。

## 2. 手工记录（真实投影器输出，未手工构造轨迹）

内核证据：`turn` + `directive lock 别叫我宝贝` + `directive lock 别复述`，`compile_kernel` 得到：

```
kid = d1eea45b882f6b7aa5bfa9a2bc2ff8847712e564f7a12be6609e5825cf05412e
canon = ['别叫我宝贝', '别复述']

project_text(kernel):
  [0] role=description  '[self] # Self …'
  [1] role=constraint   '[canon] directive: 别叫我宝贝'
  [2] role=constraint   '[canon] directive: 别复述'
  emit -> allowed=True  sink=1  事件数=3   （自述/约束不被当作话语）

project_action(kernel):
  [0] kind=action role=speech value='hold'
  [1] kind=action role=speech value='nod'
  [2] kind=wait   role=speech value=''
  emit -> allowed=False rule=不复述 index=1 detail=action nod is forbidden
          sink=0  事件数=3→4  verify=通过

内核去掉该约束后（canon=['今晚十点睡']）
  同一条真实 action 轨迹 -> allowed=True sink=1
```

拒绝事件的真实字节：

```json
{"ep": "seg-0001", "hash": "78de55e053e0b7f24284fbaa287ef7ea75d4696421aef08ce07510c3a84d2668",
 "id": "ev_000004", "kind": "gate", "prev": "c26e6316060c4d07ccb68afa26f501e7a9fdedc23bc9d7703671f6d47e9a30ab",
 "t": "2026-11-01T07:23:29Z", "target": "action", "text": "不复述", "type": "refusal",
 "trace": "sha256:dc1563c23825eae59509cefde698555662a768c3c5c527004bf9ec8a0e6fd7b1", "v": 1}
```

`trace` 等于 `trace_digest(project_action(kernel))`，即真实被拒轨迹的规范化摘要；
`text` 是命中的规则名；`target` 是准备发出的形态。

## 3. 验收结果

| # | 测试 | 结果 |
|---|---|---|
| V1 | `test_gate_schema`（3 个） | Verdict 四字段冻结；未知 scope → `E_PR_GATE_SCOPE`；缺字段 / 未知字段 / 坏上限 / 无禁止条件 → `E_PR_GATE_RULES` |
| V2 | `test_gate_pure`（3 个） | `check(trace, kernel)` 只接两个参数；假内核可判定；`100/100` 判定相同；真实 action 轨迹首违 index=0 |
| V3 | `test_gate_allows_real_text_projection` | `project_text()` 真实输出含「宝贝」，但全是 description / constraint → 放行，`sink=1`，证据不变 |
| V4 | `test_gate_refuses_real_action_projection` / `test_gate_refuses_without_store` / `test_refusal_rejects_bad_shape` | `project_action()` 真实违规轨迹 → `sink=0`，证据 `+1`，`verify` 通过；无 store 仍返回拒绝；非法 target / trace → `E_SCHEMA` |
| V5 | `test_gate_rules_are_data` | 往 `gate_rules.json` 加一条禁止 `nod` 的规则 → 同一真实轨迹从放行变拒绝；还原数据后恢复放行 |
| V6 | `test_gate_no_canon_no_gate` | 内核 canon 没有对应约束时，同一条真实轨迹放行，`sink=1` |
| V7 | `test_all_regression` | `Ran 286 tests ... OK`；冻结套件 `178 / 0 / 0 / 0` |

**本文件所有「能不能发出」的测试都使用 `project_text()` / `project_action()` 的真实输出，
不再出现手工构造的 `Trace`/`Segment`。**

## 4. 规格硬点对应到代码

| 硬点 | 落点 |
|---|---|
| 违规时 `sink` 次数必须为 0 | [`emit()`](file:///d:/projects/Memory/jian_projection/emit.py) 先 `check`，拒绝直接返回，`sink` 那一行不可达 |
| 内核没有对应约束就不启用闸门 | [`_enabled()`](file:///d:/projects/Memory/jian_projection/gate.py) 要求 `canon_keywords` 出现在 canon 才评估该规则 |
| 只判话语，不判自述/约束 | [`_first_violation()`](file:///d:/projects/Memory/jian_projection/gate.py) 跳过 `role != "speech"` |
| 规则是数据，不许写死 | [`data/gate_rules.json`](file:///d:/projects/Memory/jian_projection/data/gate_rules.json)；`gate.py` 只解释字段 |
| `check` 是纯函数 | 签名只有 `trace, kernel`；不读 store、不读时间、不用随机 |
| 拒绝必留痕 | [`append_refusal()`](file:///d:/projects/Memory/jian/capsule.py) 写 `refusal` 事件，进哈希链、过 `verify` |

判定顺序：规则按文件顺序、片段按轨迹顺序、**首违即停**，返回第一个违规片段位置。

## 5. 数据结构与错误码

`Segment(kind, value, dur_ms, source=None, role="speech")`；`role` 只允许
`speech` / `description` / `constraint`，非 `text` 片段只能是 `speech`。

`Verdict(allowed, rule, segment_index, detail)`，frozen dataclass。

`gate_rules.json` 每条规则支持：

```
canon_keywords    非空字符串列表；出现在 canon 任一原文才启用该规则
forbid_text       话语文本片段含任一子串即违规
forbid_action     话语动作片段命中任一原语即违规
max_text_chars    话语文本累计长度超过上限即违规（记录越界的那一段）
scope             text / action / both
```

本轮新增数据规则 `不复述`（canon 含「别复述」→ 禁止 `nod`）。它让「拒绝」也能
用真实 `action_v1` 输出验证，而不是靠假轨迹。

错误码：`E_PR_GATE_RULES`（规则数据非法）、`E_PR_GATE_SCOPE`（未知 scope / emit mode）。

## 6. 已知边界

1. `refusal` 已进证据层并通过 `verify`，但 `jian_kernel/compiler.py` 的 `read_evidence`
   仍只接受 M4 五类事件；已写 refusal 的 store 再次 `compile_kernel` 会报 `E_KN_IO`。
   规格 §7.5 禁止改编译器语义，本轮未动。
2. `forbid_action` 只能命中动作白名单内的原语；规格示例的
   `message_user` / `call_user` 不在白名单，这条示例规则对真实 `action_v1` 永不触发
   （`不复述` 用的是白名单内的 `nod`）。
3. `emit` 只支持 v1 证据 store 写 refusal；v2 载荷 store 的 v1/v2 不混写规则未放宽。
4. 闸门只做字面包含判定，规则词表质量决定误报/漏报。
5. `text_v1` 目前**没有** `speech` 片段，所以它永远只会被放行；真正的「话语投影器」
   属于后续里程碑。

## 7. 数字

```
测试        286 全绿（M13 前 274 + 本轮 12；0 skipped）
冻结套件     178 / 0 / 0 / 0
六个包       jian / jian_projection 的改动全部在 ALLOWED_CHANGES 声明
             jian_cn / jian_recall / jian_pcs 零 diff
新增文件     jian_projection/gate.py、jian_projection/emit.py、
            jian_projection/data/gate_rules.json、tests/test_gate.py
```

## 8. 结论

```
机制：通过（真实投影器 + 违规 sink=0 + 无约束放行 + 规则数据驱动）
证据：通过（refusal 入链、过 verify）
诊断/话语分离：通过（自述与约束不再被闸门当成要说出口的话）
验收：通过
```

建议打 tag `v0.16-m13`。

---

# M13 终验（通过，待打 tag）

> 286 测试全绿；`role` 修复后，真实投影不再被自己的约束拦住。
> 我用上轮报失败的**真实 `text_v1` 输出**复跑通过。

## 1. 修复复核（用真实投影器，不自造轨迹）

| 用例 | 结果 |
|---|---|
| 真实 `text_v1`：`[self]` 标 description、`[canon]` 标 constraint | 判定 **allowed=True** |
| 真实投影发出 | `sink` 调用 **1** 次 |
| `speech` 片段含「宝贝」 | **allowed=False，`sink` 调用 0 次**，写入 `refusal`，`verify` 通过 |
| 同内容标 `description` | 放行（按设计，诊断文本不是话语） |
| `action` 片段标 `description` | `E_PR_SCHEMA: 只有 text 片段可以是 description 或 constraint` |

**第一条是关键**：上一轮它就是 False，现在为 True。

## 2. 手工记录已改用真实输出

`ACCEPT-M13.md` 现在贴的是 `project_text()` 与 `project_action()` 的真实片段：

```
text_v1   [0] description  [self] …
          [1] constraint   [canon] directive: 别叫我宝贝
          [2] constraint   [canon] directive: 别复述
action_v1 [0] speech action=hold
```

并写明：第一次的记录用手工轨迹，**掩盖了真实缺陷**。

## 3. 一个仍然存在的边界（P2，不阻塞）

```
闸门只检查 role == speech
但 Trace 可以在进程内手工构造，role 由调用方决定
⇒ 一个粗心或恶意的适配器把违规文本标成 description，即可绕过
```

**这不是漏洞，是契约边界**：M13 保证的是「它自己投影出的speech 不会违规」，
不是「防恶意适配器」。建议后续加一条便捷入口：

```
emit_speech(text, kernel, sink, ...)   # 由库负责包装成 speech，适配器不接触 role
```

并写进文档：**role 由投影器决定，适配器不得手搭轨迹**。

## 4. 结论

```
机制：通过
端到端：通过（真实投影可发出，违规 speech 被物理拒绝）
测试：286 全绿
边界：role 可被误标（P2，建议加 emit_speech 与文档约束）
```

打 tag `v0.16-m13`。

## 5. AUDIT-01 的 P1-A3 已关闭

```
原缺口：动作与拒绝无留痕
现状：refusal 事件进哈希链，verify 通过，可回答「它拒绝过什么、依据哪条约束」
仍缺：成功发出不留痕（刻意为之，避免证据爆炸）
```
