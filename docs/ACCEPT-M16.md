# ACCEPT-M16 · 特质、风格卡与用户卡（收尾验收）

> 规格：`docs/TASK-21-traits-style.md`
> 前置：`docs/ACCEPT-M16-P0.md`（P0 修复与人格事件跳过清单）
> **结论：十二项验收全部通过；全量 `Ran 330 tests` 全绿、0 failed、0 error、0 skipped。**
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
Ran 330 tests in 330.106s
OK
```

拆分后同一命令共跑三次（`266.071s` / `277.104s` / `330.106s`，最后一次即提交前状态），
每次都是 `OK`：**0 failed / 0 error / 0 skipped**（330 = 329 + Task 6 的 1 条）。

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
全量            🟢 Ran 330 tests / OK / 0 skipped
Task 7 对照     ⚪ 未测量（无模型）；不宣称 B/C/D 的任何增益
M16 实现        🟢 可封版；唯一遗留是环境问题，不是代码问题
```
