# ACCEPT-M16 · 特质、风格卡与用户卡（收尾验收）

> 规格：`docs/TASK-21-traits-style.md`
> 前置：`docs/ACCEPT-M16-P0.md`（P0 修复与人格事件跳过清单）
> **结论：十二项验收全部通过；全量 `Ran 339 tests` 全绿、0 failed、0 error、0 skipped。**
> 例外：Task 7 的四组对照**未测量**（本机 Ollama 无模型、端口拒绝），
> 真实报错与已测数字见 `docs/RESULTS-style.md`。

---

## 1. 十二项验收

| # | 测试 | 实测断言 | 结果 |
|---|---|---|---|
| S1 | `test_traits_schema` | 词表 6 条；4 个坏样本分别得到 `E_PERSONA_TRAIT_MODE` / `E_PERSONA_TRAIT_CONFLICT` / `E_PERSONA_TRAIT_SCHEMA`（缺 `guidance`、非法 `risk`） | ✅ |
| S2 | `test_trait_cap_and_conflict` | 第 6 条 → `E_PERSONA_TRAIT_CAP`；`可爱` 胜 `毒舌`，`conflicts_md()` 含 `### Conflicts` 与双方名字 | ✅ |
| S3 | `test_trait_requires_event` | 无事件 → 生效集为空；未批准 `proposal(self.trait)` → `E_PERSONA_UNAPPROVED`；批准后 `active=['毒舌']`、`origin='approved_proposal'`、`event_id=提案 id` | ✅ |
| S4 | `test_trait_mode_gate` | `consult` 下 `毒舌` 不生效且 `reasons` 有可读原因（不抛异常）；`banter` 下生效 | ✅ |
| S5 | `test_style_card_schema` | 801 字符 / 16 examples / 4 counter / 缺 `rhythm` 全部 `E_PERSONA_STYLE_CARD`；合法卡写入 v2 `proposal(self.style_card)` 并 `parse_event` + `event_full_text` 往返 | ✅ |
| S6 | `test_style_card_redaction` | `style_input` 剔除 `third_party`（`count=1`）；原文进 `examples` → `assert_redacted` 与 `load_style_card(exclude=…)` 都抛 `E_PERSONA_REDACTION`；未知 reason → `E_PERSONA_INPUT` | ✅ |
| S7 | `test_echo_guard` | LCS 13 → `ok=False`；LCS 12 → `ok=True`；无关句 LCS 0 | ✅ |
| U1 | `test_user_card_deterministic` | 进程内两次 `to_payload()` 相同；子进程（`PYTHONUTF8=1` + `encoding="utf-8"`）stdout 与本地 494 字节完全相同 | ✅ |
| U2 | `test_user_card_traceable` | 9 条非空条目全部指向 `core_events` 里的真实 id；删掉 `call` 证据 → `call=""`；删掉承诺证据 → `promises=()` | ✅ |
| U3 | `test_user_card_budget_and_pin` | `len(text)=382 ≤ 400`；`items[0]` 为 `event_id="user_card"` / `slot="pinned"`；`total=2883 ≤ 4096`；卡片单独超预算 → `E_PERSONA_BUDGET` | ✅ |
| U4 | `test_user_card_not_in_kid` | 两张不同用户卡：`view.kid == compile_kernel.kid == b0742668a742…`，`head` 相同，`to_prompt("D")` 不同 | ✅ |
| S8 | `test_all_regression` | 冻结基线 178 条全绿；包摘要与 `ALLOWED_ADDITIONS` / `ALLOWED_CHANGES` 双向一致 | ✅ |

## 2. 额外钉死的四项

| 测试 | 实测输出 |
|---|---|
| `test_refusal_compiles` | `M16 refusal kid=2c4954edd7c7 head=ev_000005 expected=2c4954edd7c7` |
| `test_persona_events_keep_kid` | `M16 persona events=600 kid=2c4954edd7c7 head=ev_000005 stable=True`；`self_md` / `canon_md` / `state` / `graph` 逐字节相同；增量 kid 相同；`reconcile.events=5` |
| `test_record_persona_only_keeps_version` | `M16 persona-only version=1 written=False kid_stable=True`；HISTORY 字节不变；`verify_kernel` 通过；证据链末事件仍是 `directive(kind=trait)` |
| `test_persona_not_in_pcs` | `M16 persona view groups=[0, 38, 139, 154] rules=6`；PCS 规则原文不含人格文本；`jian_persona/*.py` 源码不含 `jian_pcs` |

### 用户卡否定式回归（2026-11-02 补，4 条）

原规则 `叫我(X)` 无视否定前缀，导致 `别叫我宝贝` 派生出 `call=宝贝` +
`never=[宝贝]` 的自相矛盾卡。修复两层：规则层把否定前缀并进 call 正则，
派生层再断言 `call ∉ never`（同名即丢弃）。真实输出：

```
M16 address plain call=老周 never=[]
M16 address 别 call='' never=['宝贝']
M16 address 不要 call='' never=['宝贝']
M16 address 不许 call='' never=['小名']
```

其中 `别` 用例先写 `叫我宝贝` 再写 `别叫我宝贝`，所以它同时证明第二层兜底：
即使 call 已经建立，只要同名进入 never 也会被丢弃（`call_evidence` 一并移除）。

### P1/P2 修复（2026-11-02 第二批，5 条）

`甭` 不进 never 的根因不是词表缺失，而是「用前缀判断否定」这个结构：任何没被
正则列出的否定词都会退化成 call。因此改为**子句级否定判定**：

```
negations = 别 / 不要 / 不许 / 不准 / 勿 / 甭 / 别老 / 不用 / 没必要
按标点切子句 → 子句内出现任一否定词 ⇒ 该子句的「叫X」进 never
子句无否定词 ⇒ 只有「叫我X」能设 call；「妈妈叫桂花」仍不是称呼
suffixes  = 就好 / 就行 / 吧 / 啊 / 哦 / 了 / 啦    （反复从名字尾部剥离）
```

真实输出：

```
M16 address 甭 call='' never=['宝宝']
M16 address 勿 call='' never=['小名']
M16 address 别老 call='' never=['小名']
M16 address 不用 call='' never=['小名']
M16 address suffix call='老周' tails=7
```

`叫我老周就好吧` 这类叠加尾缀也会被剥到只剩 `老周`（测试里循环覆盖 7 个尾缀）。

## 3. 版本账本与宪章 A2（必须显式说明）

**特质增删只留痕在证据链，不进版本账本。**

```
第一次 record_kernel        → version=1，written=True
只追加 directive(kind=trait) → kid 不变（人格事件不参与 kid）
再次 record_kernel          → version 仍是 1，written=False，HISTORY 字节不变
```

由此产生一个必须承认的缺口：

- 宪章 A2 要求「性格改动可追溯」。**在版本账本（`HISTORY.jsonl`）这一层，这条是断的**：
  第 1 版与第 1 版之间加了什么特质，账本上看不出来。
- 本项目把这条可追溯性交给**证据链**承担：每次特质增删都是一条不可变的
  `directive(trait)` / `directive(trait_off)` 事件，带时间戳与事件 id。
  任何人只要重放证据，就能回答「什么时候加过哪个特质、谁写的」。
- 这个行为不是意外，是被 `test_record_persona_only_keeps_version` 钉死的设计决定：
  kid 就是人格，人格没变就不该产生新版本。

**代价**：只读 `HISTORY.jsonl` 的人会以为人格从未变过。
因此任何对外说明「人格版本」的材料，都必须同时指向证据链，而不是只指向版本号。

## 4. 红线复核

| 红线 | 复核方式 | 结果 |
|---|---|---|
| 三者都不进 kid | 六种人格事件各 100 条（600 条）后 kid / head / 四个产物逐字节相同 | ✅ |
| 三者都不进 PCS | `test_persona_not_in_pcs` 断言规则原文不含人格文本，且 `rule.text` 不出现在 D 组 prompt | ✅ |
| 特质只能由人写入 | 未批准 `proposal(self.trait)` → `E_PERSONA_UNAPPROVED`；批准必须是 `directive(target=提案 id)` 且文本一致 | ✅ |
| 用户卡不许模型自由发挥 | U2：9 条非空条目全部可追证据；无证据字段为空 | ✅ |
| 用户卡不自相矛盾 | 否定式回归 4 条：`call` 与 `never` 同名即丢弃（无论先后） | ✅ |
| 派生只向下 | `jian_persona` 内 grep 无 `jian_pcs` / `jian_kernel.history` / `jian_projection` | ✅ |
| 无第三方依赖 / 无 skip / 无占位 | 全量 unittest；`jian_persona` 内 grep 无 `TODO` / `pass` / `NotImplementedError` | ✅ |

## 5. 棘轮与拆分

- `ALLOWED_ADDITIONS`：`jian_persona` 的 7 个 `.py` 全部声明。
- `ALLOWED_CHANGES`：`jian_kernel/gate.py`、`jian_kernel/kernel.py`、`jian/event.py`、
  `jian_kernel/compiler.py` 等 M16 改动全部声明（`history.py` 未动）。
- `tests/test_env_v2.py`：`gate.py` / `kernel.py` 钉值更新，`len(changed) == 12`。
- 单文件 ≤700 行：`tests/test_persona.py` 曾到 740 行，已拆为
  `tests/test_persona.py`（351 行，跳过清单 + 特质）与
  `tests/test_persona_cards.py`（434 行，风格卡 + 用户卡 + 视图）；测试总数不变。

## 6. 全量测试（真实输出）

```
$ python -m unittest discover -s tests
...
S6 frozen tests=178 failures=0 errors=0 skipped=0
V5 probes=80 skipped=0 C(a)=0.8625 C(b)=0.8375 A=0.7750 PCS=0.6491
Ran 339 tests in 227.447s
OK
```

P1/P2 修复后又跑一次全量：`Ran 339 tests ... OK`，**0 failed / 0 error / 0 skipped**
（339 = 334 + 甭/勿/别老/不用 4 条 + 尾缀 1 条；kid 与 334 时相同，未动）。

## 7. 未测量项（Task 7）

```
模型目录 %USERPROFILE%\.ollama\models  不存在
127.0.0.1:11434                       连接被拒绝（WinError 10061）
```

`tools/style_experiment.py` 在第一次真实调用即失败并退出 2：

```
E_STYLE_EXPERIMENT: <urlopen error [WinError 10061] 由于目标计算机积极拒绝，无法连接。>
```

因此 B / C / D 三组的 `C` / `A` / `PCS` / 事实命中率 / 复读率**全部未测量**，
A 组只引用 V5 的既有基线（PCS=0.649，95% CI [0.522, 0.754]）。
已测到的只有四组 system prompt 的装配成本：
`A=124 / B=147 / C=213 / D=297` tokens（仅 system，不含探针与回复）。
细节：`docs/RESULTS-style.md`。

## 8. 结论

```
S1-S8, U1-U4   🟢 全部通过（真实断言，非「应该通过」）
额外四项       🟢 refusal 可编、600 条人格事件 kid 不变、人格事件不进版本账本、人格不进 PCS
全量            🟢 Ran 339 tests / OK / 0 skipped
Task 7 对照     ⚪ 未测量（无模型）；不宣称 B/C/D 的任何增益
M16 实现        🟢 可封版；唯一遗留是环境问题，不是代码问题
```

---

# 独立复核（验收方复跑）

> 330 测试全绿；但我在真实场景探针里发现一处**语义反转**，必须修。

## 1. 通过的部分（我亲自跑过）

| 检查 | 结果 |
|---|---|
| 全量测试 | **330 全绿** |
| `PersonaView.kid == compile_kernel.kid` | ✅ |
| 内核 `self.md` 未被污染（不含 `Traits`） | ✅ |
| 用户卡 `text()` 长度 ≤400 | ✅（实测 38） |
| `to_prompt` A/B/C/D 递增 | ✅ A=0 / B=16 / C=16 / D=63 |
| 特质模式门控 | ✅ `毒舌` 在 support 下不生效，并给出原因 |
| 高风险特质在 `banter` 生效 | ✅ |

**A 组 prompt 为空是对的**：`tools/style_experiment.py` 会先拼 `build_system(rules)` 再加 persona 体，
A 组等于「裸内核 + 无 persona 附加」。这一条我核对过实现，不是问题。

## 2. P0：用户卡把「禁忌称呼」当成了「想被称呼」

实测四种句式：

| 输入 | `call`（称呼） | `never`（忌称） | 判定 |
|---|---|---|---|
| 叫我老周 | 老周 | — | ✅ 正确 |
| 别叫我宝贝 | **宝贝** | 宝贝 | ❌ **完全反转** |
| 不要叫我宝贝 | **宝贝** | 宝贝 | ❌ |
| 不许叫我小名 | **小名** | 小名 | ❌ |

根因在数据文件：

```json
"call": "叫我([^，。！？,.!?]{1,10})"
```

**它只找子串「叫我」，无视前面的否定词。** `别叫我宝贝` 里含「叫我宝贝」，于是被当成正向。

### 后果是一条自相矛盾的链

```
① D 组 prompt 写「称呼：宝贝」
② 模型据此叫用户「宝贝」
③ M13 闸门的禁词规则命中「宝贝」→ 拒绝输出
⇒ 四组对照测到的不是风格提升，而是「被自己的提示词诱导违规再被拦」
```

**这是 A5「认得用户」最坏的一种失败**：不是不认识，而是**记反了**。

## 3. 修法（两处，缺一不可）

```
① 规则层：把否定式单独分流
   (别|不要|不许|不准|勿)?叫(?:我)?(X)
   有否定词 → 进 never；没有 → 进 call
② 不变量层：派生后断言 call ∉ never（同名即丢弃 call 并记 E_PERSONA_INPUT 或降级）
```

**只做 ① 不够**：将来加新的否定词（如「甭」）还会漏；② 是兜底的不变量。

并补一条测试：上面四种句式逐个断言。

## 4. 结论

```
管线：通过（kid 不受影响、可追溯、预算成立）
用户卡语义：不通过（P0，称呼与忌称反转）
验收：不签 —— 修完补测再验
```

## 5. 修复记录（实现方回应，2026-11-02）

```
① 规则层  user_card_rules.json
   "call": "(别|不要|不许|不准|勿)?叫(我)?([^，。！？,.!?]{1,10})"
   有否定前缀 → never；无前缀且含「我」→ call
   无前缀也无「我」（如「妈妈叫桂花」）→ 不当作称呼，保持亲属陈述

② 不变量层  derive_user_card
   call 若与 never 任一名字相同 → 丢弃 call 与 call_evidence（无论先后）

③ 回归测试  tests/test_persona_cards.py 新增 4 条：
   test_address_plain_call                 叫我老周        → call=老周 / never=[]
   test_address_negation_be_drops_earlier_call  叫我宝贝 + 别叫我宝贝 → call='' / never=[宝贝]
   test_address_negation_buyao_is_taboo     不要叫我宝贝    → call='' / never=[宝贝]
   test_address_negation_buxu_is_taboo      不许叫我小名    → call='' / never=[小名]
```

第二条用例故意把正向称呼写在前面，因此同时证明兜底不变量：只靠规则分流时
`call=宝贝` 仍会保留，必须由 `call ∉ never` 丢弃。

全量复跑：`Ran 334 tests in 251.521s` / `OK`（334 = 330 + 4），kid 未动。
P1/P2 修复后再跑：`Ran 339 tests in 227.447s` / `OK`（339 = 334 + 5），kid 未动。
修复提交：`13e067a`（P0：否定前缀 + `call ∉ never`）；P1/P2 提交见 `git log`。

---

# 复核后补充（2026-11-02）

## 1. 主问题已修——我复跑了原来失败的四种句式

| 输入 | 修复前 | 修复后 |
|---|---|---|
| 叫我老周 | call=老周 | call=老周 ✅ |
| 别叫我宝贝 | **call=宝贝** | call 为空，never=[宝贝] ✅ |
| 不要叫我宝贝 | **call=宝贝** | call 为空 ✅ |
| 不许叫我小名 | **call=小名** | call 为空 ✅ |

D 组 prompt 已不再包含「称呼：宝贝」。

**兜底不变量也生效了**：先写「叫我宝贝」再写「别叫我宝贝」→ call 为空（后禁覆盖前叫）。

| 项 | 结果 |
|---|---|
| 全量测试 | **334 全绿**（330 + 4 条新增地址测试） |

## 2. 两个残留（不阻塞，下一批修）

### P1：否定词表还不全，甭 仍会漏

```
甭叫我宝宝     -> call=宝宝     never 为空    仍漏
不准叫我亲爱的  -> call 为空     never=[亲爱的] 正确
```

**这正是上一轮预判的**：只做规则层不够，将来加新否定词还会漏。
兜底不变量只在 `never` 里已经有同名条目时才生效，
而「甭」根本不进 `never`，所以兜不住。

**修法（结构性，不是加词）**：

```
call 的匹配要求：整个子句不含任何否定词
（别 / 不要 / 不许 / 不准 / 勿 / 甭 / 别老 / 不用 / 没必要）
而不是要求否定词紧贴在「叫」前面
```

### P2：尾缀被吃进称呼

```
叫我老周就好  -> call=老周就好   （应为 老周）
```

加一组尾缀停用词：就好 / 就行 / 吧 / 啊 / 哦 / 了 / 啦。

## 3. 结论

```
主问题（P0）：已修复，我实测确认
兜底不变量：生效
测试：334 全绿
验收：通过，P1/P2 记入下一批（不得丢失）
```

## 4. P1/P2 已修（2026-11-02 第二批）

| 输入 | 修复前 | 修复后 |
|---|---|---|
| 甭叫我宝宝 | call=宝宝 | `call=''` / `never=['宝宝']` ✅ |
| 勿叫我小名 | （未测） | `call=''` / `never=['小名']` ✅ |
| 别老叫我小名 | （未测） | `call=''` / `never=['小名']` ✅ |
| 不用叫我小名 | （未测） | `call=''` / `never=['小名']` ✅ |
| 叫我老周就好 | call=老周就好 | `call='老周'` ✅ |
| 叫我老周就好吧 | call=老周就好吧 | `call='老周'`（叠加尾缀） ✅ |

结构改动：否定判定从「前缀」改为「子句」——按标点切子句，子句内出现任一否定词
即整条「叫X」进 `never`，不再依赖否定词紧贴 `叫`。尾缀在比较前反复剥离。

```
Ran 339 tests in 227.447s
OK
```

全量 339（334 + 5 条新增：甭/勿/别老/不用 + 尾缀），kid 未动。

---

# 残留修复复核（2026-11-02，第二轮）

## 1. 两个残留都修好了

| 输入 | 上一轮 | 现在 |
|---|---|---|
| 甭叫我宝宝 | call=宝宝 ❌ | **call 为空，never=[宝宝]** ✅ |
| 叫我老周就好 | call=老周就好 ❌ | **call=老周** ✅ |

## 2. 我另外加了 8 条对抗用例（不在实现方的测试里）

| 输入 | call | never | 判定 |
|---|---|---|---|
| 勿叫我老张 | 空 | [老张] | ✅ |
| 别老叫我宝贝 | 空 | [宝贝] | ✅ |
| 不用叫我小名 | 空 | [小名] | ✅ |
| 没必要叫我老师 | 空 | [老师] | ✅ |
| 叫我老王吧 | 老王 | — | ✅ 尾缀已剥 |
| 以后叫我阿杰 | 阿杰 | — | ✅ 前缀不影响 |
| 叫我一声哥 | 一声哥 | — | ⚠️ 数量词未剥 |
| 别叫我爸 | 空 | [爸] | ✅ 亲属称谓也不误判 |

**改法是对的**：从「否定词紧贴『叫』」改成「整个子句不含否定词」，
所以 勿/别老/不用/没必要 一次全中——这是结构性修复，不是打补丁。

## 3. 一处仍偏小（P3，不急）

```
叫我一声哥 → call=一声哥   （应为 哥）
```
数量词「一声/一句」未剥。罕见，记下即可。

## 4. 结果文件：值得表扬的诚实

`docs/RESULTS-style.md` 没有编数字：

```
ollama.exe   存在
模型目录      %USERPROFILE%\.ollama\models  不存在
服务端口      127.0.0.1:11434               连接被拒绝
→ 四组对照未测量，只有 dry-run 的装配成本
```

**这是正确的处理**：上一轮我要求「跑不了就如实写真实报错，不许编数字」，它照做了。
比我预期的更好——它还给出了三行环境证据，而不只是「跑不了」。

## 5. 结论

```
P1/P2 残留：已修复，我复跑 + 8 条对抗用例确认
测试：339 全绿
验收：通过
待办：P3 数量词（记录在案，不阻塞）；四组对照待 Ollama 可用后补测
```

---

# 封版结论（v0.19-m16）

> 339 测试全绿。宪章 A2 与 A5 首次有了落地物。

## 1. 这一版真正交付了什么

| 宪章条目 | 之前 | 现在 |
|---|---|---|
| A2 持续塑造与进化 | 只能靠用户显式指令 | ✅ 特质表（人写入、上限、冲突、门控）+ 风格卡 |
| A5 依然认得用户 | 有 state，无画像 | ✅ 用户卡（机械派生、可追溯、固定钉入） |
| A3 始终一致 | kid 不变 | ✅ 未退化；PCS 提升待测 |

**「它记得你，也能被你有意地调整」——这两句话第一次有了可测的载体。**

## 2. 一个必须记住的 P0

`refusal` 事件会让内核编不了，这个 bug 在 main 上活了 **6 个里程碑**，
315 个测试全绿也没抓到，因为**没有一处测试在“拒绝之后”再编译一次**。

```
教训：新机制上线时，必须回头跑一遍它下游的所有路径。
     「能写进去」与「写进去之后系统还能不能算」是两件事。
```

## 3. 未完成（不隐藏）

| 项 | 状态 |
|---|---|
| 四组对照（A/B/C/D） | **未测量**：本机 Ollama 无模型，三行环境证据见 `RESULTS-style.md` |
| P3 数量词（叫我一声哥） | 记录在案，罕见 |
| A3 的 PCS 提升 | 依赖四组对照，未测 |

## 4. 封版判断

```
代码契约完整：特质/风格/用户卡三件都有 schema、来源校验、预算与不变量
身份红线守住：600 条人格事件后 kid 与内核产物逐字节不变
未测的部分已如实记录，没有编造数字
⇒ 可封版；四组对照作为 v0.20 的数据任务补测
```