# 特质、风格卡与用户卡（M16）Spec

## Why

宪章 A5「依然认得用户」是当前唯一没有落地的承诺：内核有 `state`（认识多少天、几条事件、top_kinship），
但装配上下文时没有「用户是谁」的显式条目。同时 TASK-21 要把「像他 / 认得他 / 还是他」
做成三个**可写入、可审阅、可测量**的派生品，并守住一条红线：三者都不进 `kid`。

本轮同时修掉一个 P0：`refusal` 事件一入链，内核就编不了
（`jian_kernel/compiler.py` 的 `EVENT_TYPES` 里没有 `refusal`）。

## What Changes

- **P0**：编译器认得 `refusal` 与人格事件，解析后**直接跳过**，不进 `canon` / `self.md` / `state` / `graph`。
- 新增 L2 包 `jian_persona/`：特质、风格卡、用户卡三条派生都放这里，不塞进 `jian_kernel/`。
- 新增事件写法：`directive(kind=trait|trait_off)`、`proposal(target=self.trait|self.style_card|self.user_card)`。
- `jian/capsule.py` 的 `append_event` / `append_payload_event` 增加可选溯源字段（`model` / `prompt_sha` /
  `quant` / `weights_sha` / `temp_milli` / `seed`），否则写不出 `proposal`（含 800 字的 v2 风格卡）。
- 用户卡：从证据机械派生、每字段可追证据、≤400 字符、装配时 pinned。
- 新增 `tools/style_experiment.py` 与 `docs/RESULTS-style.md`；四组对照能跑就跑，跑不了如实写。
- 两处棘轮（`tests/test_all_regression.py`、`tests/test_env_v2.py`）同步声明。
- **非 BREAKING**：既有证据的 `kid` 逐字节不变，有专门的 600 事件测试守着。

## Impact

- Affected specs: `docs/TASK-21-traits-style.md`（唯一权威规格）。
- Affected code:
  - `jian/event.py`、`jian/capsule.py`
  - `jian_kernel/compiler.py`、`jian_kernel/incremental.py`、`jian_kernel/kernel.py`、`jian_kernel/gate.py`
  - 新建 `jian_persona/`（8 个 `.py` + 2 个数据文件）
  - 新建 `jian_kernel/data/traits.json`
  - `tests/test_persona.py`、`tests/test_all_regression.py`、`tests/test_env_v2.py`
  - `tools/style_experiment.py`、`docs/RESULTS-style.md`、`docs/ACCEPT-M16.md`

## 关键裁决（已由用户确认，不得再自行发明）

1. 先修 P0：编译器认得新类型 → 解析后直接跳过，不进入 `canon` / `self` / `state` / `graph`。
2. 派生逻辑放新包 `jian_persona`（L2），不塞进 `jian_kernel`。
3. 特质授权分两种来源，不许混：
   - `directive(kind=trait)` → 用户亲口，`origin=user`
   - `proposal(target=self.trait)` → 模型提议 + 人工批准，`origin=approved_proposal`
   - `proposal` 没有批准记录 → `E_PERSONA_UNAPPROVED`
   - 不许把用户的话包装成 `proposal`，也不许把模型提议写成 `directive`
4. `kind` 只用 `trait` / `trait_off`，不复用 `lock` / `unlock`。
5. 编译器跳过清单**显式列全**（漏一个要么改 kid，要么编不过）：
   `refusal` / `directive(trait)` / `directive(trait_off)` /
   `proposal(self.trait)` / `proposal(self.style_card)` / `proposal(self.user_card)`。
6. 验收：上述每种各写 100 条（共 600 条），`kid` 逐字节不变。

## ADDED Requirements

### Requirement: 人格事件跳过清单（core_events）

系统 SHALL 在 `jian_kernel/compiler.py` 提供：

```python
PERSONA_TARGETS = ("self.trait", "self.style_card", "self.user_card")
PERSONA_DIRECTIVE_KINDS = ("trait", "trait_off")

def is_persona_event(event: EvidenceEvent) -> bool
def core_events(events: list[EvidenceEvent]) -> list[EvidenceEvent]
```

`is_persona_event` SHALL 恰好命中六种形态（不许多、不许少）：

| # | 形态 |
|---|---|
| 1 | `type == "refusal"` |
| 2 | `type == "directive"` 且 `kind == "trait"` |
| 3 | `type == "directive"` 且 `kind == "trait_off"` |
| 4 | `type == "proposal"` 且 `target == "self.trait"` |
| 5 | `type == "proposal"` 且 `target == "self.style_card"` |
| 6 | `type == "proposal"` 且 `target == "self.user_card"` |

`_compile` SHALL 只用 `core = core_events(events)` 计算：
`moment`（`core[-1].stamp`）、`check_proposals`、`_select_style`、`_model_ids`、`content`、
`self_md`、`state`、`graph`、`head = core[-1].event_id`。
`core` 为空时抛 `E_KN_IO`（没有可编译的内核证据）。

#### Scenario: 六种各 100 条，kid 不变
- **WHEN** 先编译一个只有内核事件的 store，得到 `kid_1`；再各写 100 条上述六种事件，重新编译
- **THEN** `kid_2 == kid_1`（逐字节），`head` 仍停在最后一条内核事件，`compile_kernel_incremental` 的 kid 与全量相同，`reconcile` 为 `ok`

#### Scenario: refusal 不再编不过
- **WHEN** 证据里有一条 `refusal`（M13 的 `append_refusal`）
- **THEN** `compile_kernel` 正常返回，不抛 `E_KN_IO: 未知事件类型 refusal`

### Requirement: 事件层支持特质写法

`jian/event.py` SHALL 把 `KIND_VALUES["directive"]` 扩为
`("lock", "unlock", "rule", "trait", "trait_off")`，其余校验不变
（`directive` 的 `target` 仍必须是事件 id）。

`jian/capsule.py` SHALL 让 `append_event` 与 `append_payload_event` 接受可选关键字
`model` / `prompt_sha` / `quant` / `weights_sha` / `temp_milli` / `seed` 并原样交给 `new_event`；
这些字段是否合法仍由 `jian/event.py` 的类型校验决定（`proposal` 才允许）。

### Requirement: 特质表（人写入，≤5，冲突显式解决，高危按模式门控）

词表文件 `jian_kernel/data/traits.json`（只有数据，内核不读它）：

```json
{
  "可爱": {"guidance": "多用短句与语气词，允许叠词；不卖萌到影响语义",
           "conflicts": ["毒舌", "高冷"], "modes": ["support", "banter"], "risk": "low"},
  "毒舌": {"guidance": "可以调侃与反讽，但不针对外貌、家人、收入",
           "conflicts": ["可爱", "温柔"], "modes": ["banter"], "risk": "high"},
  "闷骚": {"guidance": "嘴上克制，偶尔露一两句真心话；不解释自己",
           "conflicts": [], "modes": ["support"], "risk": "medium"},
  "温柔": {"guidance": "先接住情绪再给建议；不用命令句",
           "conflicts": ["毒舌"], "modes": ["support", "consult"], "risk": "low"},
  "高冷": {"guidance": "少用语气词；回复短，不主动追问",
           "conflicts": ["可爱"], "modes": ["support", "banter"], "risk": "medium"},
  "话痨": {"guidance": "一次给两三个相关细节；不重复同一个点",
           "conflicts": [], "modes": ["support", "banter"], "risk": "low"}
}
```

`jian_persona/errors.py` SHALL 固定这些错误码（`PersonaError(code, message)`，未知码即 `ValueError`）：

| 码 | 触发 |
|---|---|
| `E_PERSONA_TRAIT_SCHEMA` | 缺 `guidance`、字段多余、类型错、`risk` 非法 |
| `E_PERSONA_TRAIT_MODE` | `modes` 里有未知模式（合法：`support` / `banter` / `consult` / `complaint`） |
| `E_PERSONA_TRAIT_CONFLICT` | `conflicts` 里引用了词表里不存在的名字 |
| `E_PERSONA_TRAIT_CAP` | 同时生效超过 5 条 |
| `E_PERSONA_UNAPPROVED` | `proposal(self.trait)` 没有批准记录，或批准 `target` 指向不存在的提案，或批准文本与提案文本不一致 |
| `E_PERSONA_STYLE_CARD` | 风格卡超 800 字符 / examples >15 / counter >3 / 字段缺失 |
| `E_PERSONA_REDACTION` | 风格卡任何字段出现被排除的第三方原文 |
| `E_PERSONA_BUDGET` | 用户卡超 400 字符，或卡片 token 超过装配预算 |
| `E_PERSONA_IO` | 词表/规则/证据读不出来 |
| `E_PERSONA_INPUT` | 参数或事件载荷非法 |

#### Scenario: 词表校验
- **WHEN** 加载含未知 mode、未知冲突名、缺 `guidance`、未知 risk 的词表
- **THEN** 分别抛 `E_PERSONA_TRAIT_MODE`、`E_PERSONA_TRAIT_CONFLICT`、`E_PERSONA_TRAIT_SCHEMA`、`E_PERSONA_TRAIT_SCHEMA`

#### Scenario: 上限与冲突
- **WHEN** 依次启用 6 个特质；或同时启用 `可爱` 与 `毒舌`
- **THEN** 6 条时抛 `E_PERSONA_TRAIT_CAP`；`可爱`（risk=low）胜 `毒舌`（risk=high），
  胜负写进 `PersonaView.self_md` 的 `### Conflicts` 段（含双方事件 id 与理由）

冲突规则（写死）：`risk` 低者胜；同 `risk` 时**后启用者胜**；输者不进入生效集。

#### Scenario: 特质必须有事件（防自动晋升）
- **WHEN** 证据里没有任何特质事件；或只有一条没有批准记录的 `proposal(self.trait)`
- **THEN** 前者生效集为空；后者抛 `E_PERSONA_UNAPPROVED`。
  内核与 `PersonaView.self_md` 里的特质**只能**来自上面两种授权事件。

#### Scenario: 高危模式门控
- **WHEN** `毒舌`（risk=high，modes 只有 `banter`）在 `consult` 模式下派生
- **THEN** 生效集不含 `毒舌`，且 `reasons` 里有一条可读原因（含特质名与模式名），不抛异常

### Requirement: 风格卡（一次性蒸馏，≤800 字符，写入即 proposal）

`jian_persona/style_card.py` SHALL 校验并读写：

```json
{"source": {"from_event": "ev_000001", "to_event": "ev_000500", "count": 500},
 "distilled_at": "...", "model": "...", "prompt_sha": "...",
 "rhythm": "...", "address": "...", "tics": ["..."],
 "examples": ["..."], "counter_examples": ["..."], "forbidden": ["..."]}
```

| 规则 | 值 |
|---|---|
| 上限 | canonical JSON 字节解码后的字符串长度 ≤ **800**（超即 `E_PERSONA_STYLE_CARD`） |
| examples / counter_examples | ≤15 / ≤3 |
| 写入 | `proposal` 事件，`target="self.style_card"`，v2 信封（`payload` = 卡片的 canonical JSON 字节，`summary` ≤200），溯源字段齐全 |
| 读取 | 取最后一条 `proposal(self.style_card)`，解 `event.text`（v2 即载荷原文）并校验 |
| 脱敏 | 复用 M15 原因表 `jian_succession.model.REASONS`；被排除事件的原文不得出现在任何字段 |

复读守卫（可判定）：`echo_guard(reply, examples, limit=12) -> EchoResult(lcs, ok)`，
最长公共子串 >12 字判为复读（`ok=False`），≤12 不误报。

#### Scenario: 风格卡 schema
- **WHEN** 卡片 801 字符 / examples 16 条 / counter 4 条 / 缺 `rhythm`
- **THEN** 一律 `E_PERSONA_STYLE_CARD`；合法卡片写入后可用 `parse_event` 原样读回

#### Scenario: 脱敏
- **WHEN** 输入里有一条被标为 `third_party` 的事件，其原文被塞进 `examples`
- **THEN** 校验抛 `E_PERSONA_REDACTION`；由 `style_input(...)` 生成的输入里不含该事件原文

#### Scenario: 复读守卫
- **WHEN** 回复与 `examples` 任一句的最长公共子串为 13 字；或为 12 字
- **THEN** 前者 `ok=False`，后者 `ok=True`

### Requirement: 用户卡（机械派生，≤400 字符，每字段可追证据，pinned）

`jian_persona/user_card.py` SHALL 只从内核证据（`core_events`）派生，规则表放在
`jian_persona/data/user_card_rules.json`（代码保持 ASCII）：

| 字段 | 机械规则 | 证据 |
|---|---|---|
| `address.call` | 正则 `叫我(X)`，取最后一条 | 事件 id |
| `address.self` | 正则 `自称(X)`，取最后一条 | 事件 id |
| `address.never` | 正则 `(?:别|不要|不许|不准)叫(?:我)?(X)`，全部去重 | 事件 id |
| `people` | `jian_cn.kinship` 词表命中的关系词，后接 `叫(X)` 才有名字，否则名字为空 | 事件 id |
| `taboos` | 所有内核 `directive(kind="lock")` 的原文 | 事件 id |
| `promises` | `jian_recall.index.is_promise` 且未被完成标记取消 | 事件 id + `since`(日期) |
| `ongoing` | 最近 ≤3 条 `milestone` 原文 | 事件 id |
| `prefs.like` / `prefs.dislike` | 规则表里的 `我喜欢X` / `我不喜欢|不爱|讨厌|不吃|不看|不听 (X)` | 事件 id |

字段条目统一形如 `{"text": ..., "evidence": "ev_..."}`（`address.call`/`self` 用 `..._evidence`）。
无证据 SHALL 留空，不许猜、不许补默认值（例如 `address.self` 不一定等于「我」）。

预算：`UserCard.text()` 渲染后的长度 ≤400；超出时按固定优先级
`address > taboos > people > promises > ongoing > prefs`，从最低优先级尾部逐条丢弃，
同一输入必然得到同一结果（不许按时间、不许随机）。仍超 400 抛 `E_PERSONA_BUDGET`。

装配：`pin_user_card(context, card, budget=4096) -> Context` 把卡片作为
`ContextItem(event_id="user_card", slot="pinned")` 放在**首位**；超预算时从尾部丢条目
（recent 先走），卡片本身永不被挤掉；卡片单独就超预算时抛 `E_PERSONA_BUDGET`。

#### Scenario: 可重算
- **WHEN** 同一份证据派生两次；以及另起一个进程派生
- **THEN** `dumps(card.to_payload())` 字节相同（子进程用 `PYTHONUTF8=1` + `encoding="utf-8"`，C13）

#### Scenario: 可追溯
- **WHEN** 卡片任一非空字段
- **THEN** 都能追到一条存在的内核事件 id；删掉对应证据后该字段消失（不许留残值）

#### Scenario: 预算与钉住
- **WHEN** 卡片 ≥400 字符上限附近，装进 `assemble(...)` 的结果
- **THEN** 卡片在 `items[0]`，`slot == "pinned"`，且不因检索挤压而消失

#### Scenario: 不进 kid
- **WHEN** 用两张不同的用户卡构造 `PersonaView`
- **THEN** 两者的 `kid` 与直接 `compile_kernel` 的 `kid` 完全相同

### Requirement: 一条共用派生管线

`jian_persona/view.py` SHALL 提供：

```python
def build_persona_view(store, *, mode="support", exclude=None,
                       style_card=None, user_card=None) -> PersonaView
```

`PersonaView` 字段：`kid`、`head`、`traits`（生效集，按启用事件 id 升序）、
`conflicts`、`reasons`、`style_card`、`user_card`、`self_md`（人格文档，含 `## Traits` 与 `### Conflicts`）。

`PersonaView.to_prompt(group) -> str`，`group ∈ {"A","B","C","D"}`（其它值 `E_PERSONA_INPUT`）：

```
A  ""                       （裸内核）
B  特质段
C  特质段 + 风格卡段
D  特质段 + 风格卡段 + 用户卡段
```

#### Scenario: 三者都不进 PCS
- **WHEN** 取 `jian_pcs.probes.load_rules_v2()` 的规则原文与 `PersonaView.to_prompt("D")`
- **THEN** 人格文本不进入规则集；`jian_persona` 的模块不 import `jian_pcs`

### Requirement: 四组对照工具与报告

`tools/style_experiment.py` SHALL 接受
`--group A B C D --models qwen3.5:9b glm4:9b`，沿用 80 条 PCS 探针 + 新增 30 条用户事实探针
（`jian_persona/data/facts.jsonl`，每条 `{"id","question","answer"}`），指标为
`PCS / C(qwen) / C(glm) / A / 事实命中率 / tokens/轮 / 复读率`。
网络/模型不可用时 MUST 以非零退出码失败并给出可读原因，不许输出编造数字。
`--dry-run` 不联网，只组装四组 prompt 并打印长度与 token 数。

`docs/RESULTS-style.md` MUST 记录真实结果或真实的「未测量」原因（当前本机 Ollama 未就绪）。

## MODIFIED Requirements

### Requirement: 增量编译与对账

`jian_kernel/incremental.py` SHALL 与全量编译共用同一份跳过语义：
`events = read_evidence(store)` → `core = core_events(events)`；
快照 `head` 校验、`delta`（只取 `core` 中 `seq > head` 的）、`_apply_delta` 的
`moment` / `head` / `_model_ids`、`_build_context(core)`、`_kernel_from_snapshot` 的 `moment`
全部改用 `core`。追加人格事件后 `compile_kernel_incremental` 的 kid 与
`compile_kernel` 逐字节相同，`reconcile` 返回 `ok`。

### Requirement: 提案白名单

`jian_kernel/gate.py` 的 `check_proposals` SHALL 允许
`STYLE_TARGETS + PERSONA_TARGETS`（供直接调用者），但编译器只把 `core` 交给它，
所以人格提案不参与 G5 校验、也不影响 `origin` / `models` / kid。

## REMOVED Requirements

无。

## 验收测试（名称必须一致，写进 `tests/test_persona.py`）

| # | 测试名 |
|---|---|
| S1 | `test_traits_schema` |
| S2 | `test_trait_cap_and_conflict` |
| S3 | `test_trait_requires_event` |
| S4 | `test_trait_mode_gate` |
| S5 | `test_style_card_schema` |
| S6 | `test_style_card_redaction` |
| S7 | `test_echo_guard` |
| U1 | `test_user_card_deterministic` |
| U2 | `test_user_card_traceable` |
| U3 | `test_user_card_budget_and_pin` |
| U4 | `test_user_card_not_in_kid` |
| S8 | `test_all_regression`（既有文件，保持全绿） |

额外必加（用户裁决）：

- `test_persona_events_keep_kid`：六种各 100 条，kid 逐字节不变 + 增量/对账同样不变
- `test_persona_not_in_pcs`：人格文本不进 PCS 规则集，`jian_persona` 不 import `jian_pcs`

## 棘轮（必须同时改）

- `tests/test_all_regression.py`：包元组加 `jian_persona`；`ALLOWED_ADDITIONS` 加 8 个
  `jian_persona/*.py`；`ALLOWED_CHANGES` 新增 `jian_kernel/gate.py`、`jian_kernel/kernel.py`
  （`jian/event.py`、`jian/capsule.py`、`jian_kernel/compiler.py` 已有声明，需更新理由文字）。
- `tests/test_env_v2.py`：`M12_ADDITIONS` 更新 `incremental.py` 摘要；`M12_EDITS` 更新
  `compiler.py` 摘要并新增 `gate.py`、`kernel.py` 两条；`len(changed)` 由 10 改为 12。

## DoD

```
python -m unittest discover -s tests -v        # 全绿，0 skipped
python tools/style_experiment.py --group A B C D --models qwen3.5:9b glm4:9b   # 记录真实结果或真实失败原因
```

单文件 ≤700 行；一次提交 ≤800 行（P0 与人格层拆两次提交）；无 `TODO` / `pass` / `NotImplementedError`。
