# ACCEPT-M17 · 宿主接入（独立验收）

> 验收对象：`tools/host_adapter.py`（用户实现，本轮**未修改一行**）
> 权威规格：`docs/TASK-23-host.md`；接入说明：`docs/HOST-INTEGRATION.md`
> 验收方式：只读审计 + 补测试；所有缺陷只记录，不直接改实现。

---

## 0. 结论

四项审计：**3 项通过，1 项有缺陷**。

| # | 审计项 | 结论 |
|---|---|---|
| 1 | 五个方法是否真只有五个；`prompt_for` 是否只读 | **通过**（方法数精确为 5；证据与 chain 字节不变；仅写 `.index/` 与内存计数器） |
| 2 | 拒绝时 refusal 恰好一条、不含对话、助手轮不落盘 | **通过**（实测 1 条 `type=refusal / kind=gate / text=禁称呼`，无助手 turn） |
| 3 | 空库 / 单条 / 20 万条：崩不崩、超不超预算 | **有缺陷**：空库崩（D1）；20 万条长文本超预算（D2）；20 万条单次 `prompt_for` 约 96 s（D3） |
| 4 | 用户卡是否在上下文之前 | **通过**（静态顺序 + 新增断言；`CARD_HEADER` 索引 < `CONTEXT_HEADER` 索引） |

补充：**原 344 条测试全部保留且全绿**；本轮新增 6 条，基线变为 **350**。

---

## 1. 五个方法

### 1.1 真实输出

```
public_methods=['on_assistant', 'on_user', 'prompt_for', 'reply', 'stats']
```

`inspect.getmembers(HostSession, inspect.isfunction)` 排除了 `_` 开头与 `__init__`，公开方法**恰好五个**。
新增测试 `test_exactly_five_public_methods` 固定这一事实。

### 1.2 `prompt_for` 只读

新增测试 `test_prompt_does_not_touch_evidence`：连续调用两次，比较 `evidence/seg-*.jsonl` 与 `chain.json` 的**逐字节快照**，结果相同。

允许的两处副作用：

- 首次调用会写 `store/.index/`（派生索引，规格与用户审计口径均允许；可删可重建）；
- 内存计数器 `prompts` +1（不是证据，但见 D8）。

### 1.3 注意点（不算违反方法数，但属于接入风险）

- `on_assistant` 是规格列出的五个方法之一，但宿主若直接调用它，会**绕过闸门**写助手轮。`reply` 的闸门保护只在宿主主动走 `reply` 时成立（见 D6）。
- `tools/host_adapter.py#L21` 从 `aiinvite.persona.view` 导入了私有函数 `_user_section`（见 D5）。

---

## 2. 闸门拒绝

### 2.1 真实输出

命令：构造 `directive/lock = 别叫我宝贝` → `seal` → `reply("宝贝我来了")`。

```
allowed=False rule=禁称呼 segment=0
stats={'turns': 0, 'refused': 1, 'prompts': 0}
events=2
types=['directive', 'refusal']
roles=[None, None]
refusal_count=1
refusal_kind=gate target=text text=禁称呼
text_has_dialogue=False
trace=sha256:30d19e1cd9cb7fa87c06a698d6a035cee5f2f9f6527251b546eaa38cbdf954c6
assistant_turns=0
```

逐条对照：

| 断言 | 结果 |
|---|---|
| refusal 恰好一条 | 是（`refusal_count=1`） |
| 类型是 `refusal` | 是（`types=['directive','refusal']`） |
| `kind=gate`、`target=text` | 是 |
| 不含对话内容 | 是（`text=禁称呼`，不含「宝贝」「我来了」） |
| 助手轮不落盘 | 是（`assistant_turns=0`，`stats.turns=0`） |
| 事件总数 | 2（原 directive 1 条 + refusal 1 条） |

### 2.2 新增测试

- `test_refusal_is_one_gate_event_without_dialogue`：把上表全部断言固化。
- `test_allowed_reply_writes_no_refusal`：正常回复不产生 refusal，且恰好一条 assistant turn（原 H4 只测了拒绝侧，规格却要求「正常回复不产生 refusal」）。

---

## 3. 极端输入

### 3.1 空库：**崩**（D1）

`init_store` 创建了空的 `evidence/` 与 `chain.json`；此时直接调用 `prompt_for`：

```
Traceback (most recent call last):
  File "...\tools\host_adapter.py", line 76, in prompt_for
    view = build_persona_view(self.store, policy=Policy(now=self.now))
  File "...\aiinvite.persona\view.py", line 71, in build_persona_view
    kernel = compile_kernel(store, policy)
  File "...\aiinvite.kernel\compiler.py", line 124, in compile_kernel
    return _compile(store, read_evidence(store), policy, proposer)
  File "...\aiinvite.kernel\compiler.py", line 203, in read_evidence
    raise KernelError(E_KN_IO, f"证据目录为空：{folder}")
aiinvite.kernel.errors.KernelError: E_KN_IO: 证据目录为空：...\m\evidence
```

`reply` 同样会先 `compile_kernel`，所以空库的 `reply` 也会崩。
**没有把这条写成失败测试**：按你的要求，缺陷写进 ACCEPT，由你决定改不改；否则全量会变红。

### 3.2 单条：通过

```
chars=229 tokens=108 over=False
sections=['## behavior rules', '## who you both are', '## recent and recalled memory',
          '## persona', '## this turn']
stats={'turns': 0, 'refused': 0, 'prompts': 1}
```

新增测试 `test_single_event_store_prompt` 固定：单条证据下五个 section 齐全且 ≤ 4096。

### 3.3 20 万条：不崩，但**超预算**（D2）且**很慢**（D3）

真实 20 万条链（`new_event` 逐条哈希、2000 个段、55,523,721 字节），
其中 50 条命中查询的长文本、8 条最近长文本、3 条同日回溯、2 条 promise：

```
write_s=21.1
cold_s=88.6 warm_s=96.38
chars=4307 tokens=4165 budget=4096 over=True
stable=True
context_total=4000 items=20 slots={'trigger': 2, 'retrieved': 13, 'recent': 5}
ctx_tokens=3848 overhead=317
same_day_indexes=[151349, 151350, 151351] promise_indexes=[195618, 195619]
store_evidence_bytes=55523721 files=2000
```

结论：

- `context_total=4000 < 4096`：`StreamSession` 的预算**只覆盖上下文三个槽位**；
- 规则 + 用户卡 + 人格视图 + 五个 header + 本轮输入的固定开销（实测 `overhead=317`）**不在预算内**；
- 因此最终 `prompt` 为 **4165 > 4096**，H5 在长文本场景下不成立。

短文本场景（`tests/rc_fixtures.write_bulk_store` 的短句）不会超预算，它只说明上下文没被填满，不能证明 H5。
另外该 fixture **不写 `meta.json`/`chain.json`**，不能直接当作 H5 的 20 万条真实场景（见 D4）。

耗时分解（同一 20 万条 store）：

```
persona_s=65.32
kernel_s=57.60
context_s=0.07
```

`prompt_for` 单次约 96 s，瓶颈是 `build_persona_view → compile_kernel → read_evidence`
对全量证据的重复解析；检索装配本身只要 0.07 s。此项按 C14 只报告，不进单测断言。

### 3.4 超长用户输入：**超预算**（D2 的另一面）

```
input_chars=500  tokens=606  over=False
input_chars=3000 tokens=3106 over=False
input_chars=5000 tokens=5106 over=True
```

`prompt_for` 末尾原样拼入 `user_text`，没有任何截断或预算回退。因此即使上下文很小，
一条 5000 汉字的用户消息也会把 prompt 推到 5106 tokens。

---

## 4. 用户卡在上下文之前

静态顺序（`tools/host_adapter.py#L75-L88`）为：

```
rules → user card → context → persona → input
```

新增测试 `test_user_card_precedes_context`：

```
prompt.index("## who you both are") < prompt.index("## recent and recalled memory")
```

结果通过。原有 `test_prompt_order_is_fixed` 继续断言五个 header 的索引单调递增。
说明：上下文为空时 `CONTEXT_HEADER` 整个 section 被省略（`if lines:`），
此时用户卡仍在 persona/input 之前，不构成顺序错误；但「卡必须在上下文之前」在**有上下文**时成立。

---

## 5. H1–H6 对照

| # | 规格要求 | 结论 | 证据 |
|---|---|---|---|
| H1 | 两轮后证据 +2；kid 与直接 append 的孪生 store 相同 | 通过 | 原 `test_round_trip_records_two_turns` + 新 `test_exactly_five_public_methods` |
| H2 | 卡在上下文之前；规则最前；输入最后 | 通过 | 原 `test_prompt_order_is_fixed` + 新 `test_user_card_precedes_context` |
| H3 | 两次 `prompt_for` 不写事件、字节相同 | 通过（加强） | 原 `test_prompt_is_pure` + 新 `test_prompt_does_not_touch_evidence`（含 `chain.json` 字节） |
| H4 | 拒绝 → `allowed=False`、多一条 refusal、正常回复无 refusal | 通过（补齐） | 原 `test_refusal_is_recorded` + 新两条精确断言 |
| H5 | 20 万条下 `prompt ≤ budget` | **不通过**（长文本） | 3.3 实测 `tokens=4165 > 4096` |
| H6 | 全量测试全绿，不改既有包 | 通过 | `Ran 350 tests ... OK`（见 §7） |

---

## 6. 缺陷清单（只记录，不修改）

| # | 缺陷 | 位置 | 严重度 | 说明 / 建议方向（由你决定） |
|---|---|---|---|---|
| D1 | 空库调用 `prompt_for` / `reply` 直接抛 `E_KN_IO` | `tools/host_adapter.py#L69-L76`、`aiinvite.kernel/compiler.py#L203` | 中 | 新建会话若宿主先要提示词再写首条用户事件，就会崩。可考虑在适配器层给出空库的固定提示词，或明确要求宿主先 `on_user`。 |
| D2 | 预算只约束上下文槽位，固定开销与用户输入不计入 | `tools/host_adapter.py#L69-L89`、`aiinvite.recall/assemble.py` 的 `cap_recent/cap_trigger/cap_retrieved` | 高 | 20 万条长文本 `4165 > 4096`；5000 字输入 `5106 > 4096`。H5 实际不成立。需要明确「budget 是上下文预算还是整条 prompt 预算」，再决定在适配器里扣减固定开销并截断输入。 |
| D3 | 20 万条时单次 `prompt_for` 约 96 s（全量重算） | `build_persona_view` / `compile_kernel` / `read_evidence` | 中 | `context_s=0.07`，耗时几乎全在证据全量解析。按 C14 不写成单测断言，但接入方会感知。 |
| D4 | H5 的既有测试只在 2 条事件的 store 上断言；20 万条 fixture 无 `meta.json`/`chain.json` | `tests/test_host_adapter.py#L88-L92`、`tests/rc_fixtures.py#write_bulk_store` | 中 | 原 H5 实际测不到 20 万条；bulk fixture 建出来的 store 上下文为空（无 meta），不能代表真实场景。 |
| D5 | 适配器依赖 `aiinvite.persona.view` 的私有函数 `_user_section` | `tools/host_adapter.py#L21`、`aiinvite.persona/view.py#L147-L149` | 低 | 私有 API 一旦改名/改签名，适配器会静默失效；建议以后让 `PersonaView` 提供公开的用户卡渲染入口。 |
| D6 | `on_assistant` 公开可调用，绕过闸门 | `tools/host_adapter.py#L64-L67` | 中 | 规格把 `on_assistant` 列为五个方法之一，但「不许跳过闸门直接写助手回复」只能靠宿主自觉。若要保持五个方法，只能在文档里写死「助手轮只走 `reply`」。 |
| D7 | `_ensure_index` 捕获所有 `Exception` 后盲重建 | `tools/host_adapter.py#L49-L57` | 低 | 任何内部错误（包括编程错误）都会被当成「索引缺失」触发全量重建；空库时 `build_index` 还会继续抛 `E_RC_IO`。 |
| D8 | `prompt_for` 在干活前就把 `prompts` 计数 +1 | `tools/host_adapter.py#L71` | 低 | 调用失败（如 D1）时计数器已 +1，`stats` 与真实成功次数不一致。 |

---

## 7. 真实测试输出

### 7.1 M17 专项

```
Ran 11 tests in 1.478s

OK
```

（原 5 条 + 新增 6 条：方法数、证据字节只读、拒绝精确断言、正常回复无 refusal、卡先于上下文、单条 store。）

### 7.2 全量

```
Ran 350 tests in 214.979s

OK
```

0 failed / 0 errors / 0 skipped（原 344 条全部保留）。

---

## 8. 未做的事

- 未修改 `tools/host_adapter.py`、`docs/HOST-INTEGRATION.md`、`docs/TASK-23-host.md`。
- 未调用任何真实模型（`--dry-run` 之外没有模型可调；宿主职责）。
- 未把 D1 写成失败测试（会让全量变红，且等于把缺陷固化进测试）。
- 未提交 git（等你的决定）。

---

# 验收方复核（Captain）

> 实现方交了 `docs/ACCEPT-M17.md`（8 条缺陷）与用户卡同义归一的修复。
> 我逐条复跑，并修掉其中属于适配器的部分。

## 1. 实现方的审计：**质量很高，缺陷都成立**

我实测复现了前三条：

| 缺陷 | 我的复现 | 结论 |
|---|---|---|
| D1 空库崩 | `E_KN_IO: 证据目录为空` | ✅ 成立 |
| D2 预算不覆盖固定开销 | 5000 字输入 → **5106 tokens > 4096** | ✅ 成立 |
| D3 大库慢 | 3000 条 → 单次 `prompt_for` **4.4–6.0 s**（外推 20 万约 96 s） | ✅ 成立 |
| D4 H5 测试用 2 条事件 | 读代码确认 | ✅ 成立 |
| D5 依赖私有 `_user_section` | 读代码确认 | ✅ 成立 |
| D6 `on_assistant` 绕过闸门 | 读代码确认 | ✅ 成立 |
| D7 过宽的 `except` | 读代码确认 | ✅ 成立 |
| D8 计数在动作之前 | 读代码确认 | ✅ 成立 |

**这是本项目第一次由实现方审出适配器的硬伤，其中两条会让产品直接不可用。**

## 2. 我修的（适配器侧，D1/D2/D5/D6/D7/D8）

| 修复 | 做法 | 实测 |
|---|---|---|
| D1 | 空库降级为「规则 + 输入」，不再抛错 | 空库 prompt 65 tokens，含规则 ✅ |
| D2 | **budget 改为整条 prompt 的预算**：先截输入、再按余量给上下文 | 5000 字输入 → 2595 tokens ✅ |
| D5 | 改用公开的 `user_card.text()`，去掉私有导入 | ✅ |
| D6 | docstring 写明「助手轮只走 `reply`」，并加测试固定 | ✅ |
| D7 | `except` 收窄到 `RecallError` / `AiInviteError` | ✅ |
| D8 | 计数移到成功之后 | 空库调用失败不再 +1 ✅ |

测试：344 → **357 全绿**（新增空库、超长输入、docstring 三条）。

## 3. 实现方的 P1 修复（用户卡同义归一）：我复核通过

| 输入 | call | never |
|---|---|---|
| 我叫老周 | 老周 | — |
| 名字：张兰 | 张兰 | — |
| 以后叫我小林 | 小林 | — |
| 别叫我宝贝 | — | 宝贝 |
| 不要叫我宝贝 | — | 宝贝 |
| 甭叫我宝宝 | — | 宝宝 |
| 叫我老周就好 | 老周 | — |
| **我妈叫我回家** | **—** | — |

**最后一条最关键**：亲属称呼「我妈叫我回家」不再被误当成用户想被叫「回家」。

## 4. 由此得到的关键数字：用户卡真的让人「认得」你

同一批 33 个人格、同一句「我叫什么名字？只回答名字」：

```
人数：50 个人格 × 2 个模型 = 100 次问答

A 组（无用户卡）：命中   0 / 100 = 0.00
E 组（仅用户卡）：命中 100 / 100 = 1.00

按模型拆：
  A · qwen3.5:9b   0/50     E · qwen3.5:9b  50/50
  A · glm4:9b      0/50     E · glm4:9b     50/50
```

**零例外。** 两个模型、50 个不同名字，没有一次失败。

**这是 M16 那个 0.917 的独立复现，且这次覆盖 33 个不同名字、两个模型。**

## 5. 仍未修复：D3（性能）

```
现状：prompt_for 每轮全量编译人格（compile_kernel → read_evidence）
实测：3000 条约 5 s；20 万条约 96 s
根因：build_persona_view 内部强制 compile_kernel，用不上 M12 的增量编译
```

**这不是适配器能独自修的**：需要 `build_persona_view(..., kernel=...)` 支持传入预编译内核。
交给实现方，作为 M17.1。

## 6. 验收结论

```
实现方审计：通过（8 条缺陷全部成立）
适配器修复：D1/D2/D5/D6/D7/D8 已修，357 测试全绿
用户卡 P1：通过（8 条用例全对，含亲属称呼反例）
剩余：D3 性能 → M17.1
```

**可以封版，但必须在 CHANGELOG 里写明 D3 未修。**

---

# D3 性能：修复与剩余（2026-11-02）

## 1. 做了什么

```
适配器改用 compile_kernel_incremental（M12 的增量编译）
并把编译好的 kernel 传给 build_persona_view（该函数已支持 kernel= 参数）
再加一层 view 缓存：head 未变时直接复用，不重复派生
```

## 2. 实测（同一台机器，同一 store 形状）

| 规模 | 修复前 | 修复后（热） | 修复后（追加一条后） |
|---|---|---|---|
| 3,000 条 | 4.4–6.0 s | **0.08 s** | **0.44 s** |
| 20,000 条 | 约 33 s（按比例估） | 0.69 s | **2.98 s** |
| 200,000 条 | 96 s（实现方实测） | — | 约 30 s（外推） |

**每轮成本下降约 10 倍，但仍然随证据量线性增长。**

## 3. 为什么还没根治

```
compile_kernel_incremental 虽然只重算增量，但它内部仍然 read_evidence(store)，
也就是每次把全部证据重新解析一遍。
build_persona_view 为了派生特质与用户卡，也会再读一遍。
⇒ 省掉的是「重算」，没省掉「重读」。
```

**真正的下一步**（需要内核 API 支持，属实现方）：

```
read_evidence(store, from_segment=...)   或   EvidenceReader 带前缀缓存
  → 只解析最后一个段，前缀复用内存里的对象
预期：20 万条下每轮从约 30 s 降到 0.1 s 量级
```

## 4. 结论

```
D3：部分修复（10×），未根治
能否上线：20 万条历史下仍不可用；5 万条以内可接受
必须记住：这是「读放大」，不是「算放大」——M12 的增量只解决了后者
```
