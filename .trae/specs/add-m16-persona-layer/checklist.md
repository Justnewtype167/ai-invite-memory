# Checklist

## P0 与红线

- [ ] `refusal` 事件不再导致 `E_KN_IO: 未知事件类型 refusal`，`compile_kernel` 正常返回
- [ ] 跳过清单恰好六种形态：`refusal` / `directive(trait)` / `directive(trait_off)` / `proposal(self.trait)` / `proposal(self.style_card)` / `proposal(self.user_card)`，既不多也不漏
- [ ] 六种各 100 条写入后，`kid` 与写入前逐字节相同；`head` 停在最后一条内核事件
- [ ] 六种各 100 条写入后，`kernel.self_md` / `canon_md` / `state` / `graph` 与写入前逐字节相同
- [ ] 只追加人格事件后 `record_kernel` 产生同 kid 的新版本，HISTORY 该行含 `"note": "persona_only"`；无新证据时 `written=False` 且 HISTORY 字节不变
- [ ] 追加人格事件后 `compile_kernel_incremental` 与 `compile_kernel` 的 kid 相同，`reconcile` 返回 `ok`
- [ ] `moment` / `models` / `style` / `state` / `graph` / `self.md` 全部只由内核事件计算，人格事件不参与

## 特质

- [ ] `jian_kernel/data/traits.json` 六条、冲突引用闭合，内核代码不读它
- [ ] S1 `test_traits_schema`：未知 mode → `E_PERSONA_TRAIT_MODE`；未知冲突名 → `E_PERSONA_TRAIT_CONFLICT`；缺 `guidance` / 非法 `risk` → `E_PERSONA_TRAIT_SCHEMA`
- [ ] S2 `test_trait_cap_and_conflict`：第 6 条 → `E_PERSONA_TRAIT_CAP`；`可爱` 胜 `毒舌`，胜负写进 `PersonaView.self_md` 的 `### Conflicts`
- [ ] S3 `test_trait_requires_event`：无事件时生效集为空；只有未批准 `proposal(self.trait)` → `E_PERSONA_UNAPPROVED`
- [ ] S4 `test_trait_mode_gate`：`毒舌` 在 `consult` 下不生效且 `reasons` 有可读原因（不抛异常）
- [ ] 特质来源不混：`directive(kind=trait)` = 用户亲口，`proposal(self.trait)` 必须有批准 `directive`（`target` = 提案 id 且文本一致）

## 风格卡

- [ ] S5 `test_style_card_schema`：>800 字符 / examples 16 / counter 4 / 缺字段 → `E_PERSONA_STYLE_CARD`；合法卡片写入 v2 `proposal(self.style_card)` 并能 `parse_event` 读回
- [ ] S6 `test_style_card_redaction`：被排除（`third_party`）的原文出现在任何字段 → `E_PERSONA_REDACTION`；`style_input` 不包含该原文
- [ ] S7 `test_echo_guard`：LCS 13 字 → `ok=False`；12 字 → `ok=True`

## 用户卡

- [ ] U1 `test_user_card_deterministic`：同证据两次派生字节相同；子进程派生字节相同（`PYTHONUTF8=1` + `encoding="utf-8"`）
- [ ] U2 `test_user_card_traceable`：每个非空条目都带存在的内核事件 id；删掉证据后该字段消失；无证据字段为空
- [ ] U3 `test_user_card_budget_and_pin`：`text()` ≤400；`pin_user_card` 后 `items[0]` 是 `event_id="user_card"` / `slot="pinned"`；检索挤压不丢卡
- [ ] U4 `test_user_card_not_in_kid`：两张不同用户卡的 `PersonaView.kid` 与 `compile_kernel` 的 kid 相同

## 共用管线

- [ ] `PersonaView.to_prompt` 的 A/B/C/D 严格对应空 / 特质 / +风格卡 / +用户卡；未知组 → `E_PERSONA_INPUT`
- [ ] `test_persona_not_in_pcs`：PCS 规则原文不含人格文本；`jian_persona` 不 import `jian_pcs`
- [ ] 派生只读证据层：`jian_persona` 不 import `jian_kernel.history` / `jian_projection`，无上层 → 上层依赖

## 棘轮与全量

- [ ] `tests/test_all_regression.py`：包元组含 `jian_persona`；7 个新文件在 `ALLOWED_ADDITIONS`；`jian_kernel/gate.py`、`jian_kernel/kernel.py`、`jian_kernel/history.py` 在 `ALLOWED_CHANGES`
- [ ] `tests/test_env_v2.py`：`incremental.py`/`compiler.py` 摘要更新，`gate.py`/`kernel.py`/`history.py` 新钉值，`len(changed) == 13`
- [ ] `python -m unittest discover -s tests -v` 全绿、0 skipped、0 errors，总数 ≥ 330
- [ ] 无 `TODO` / `pass` / `NotImplementedError`；无 skip；无第三方依赖；单文件 ≤700 行

## 工具与文档

- [ ] `tools/style_experiment.py` 支持 `--group A B C D --models qwen3.5:9b glm4:9b`，`--dry-run` 不联网
- [ ] `jian_persona/data/facts.jsonl` 恰好 30 条事实探针
- [ ] `docs/RESULTS-style.md` 是真实结果或真实「未测量」原因（含 Ollama 不可用的真实报错），不编造数字
- [ ] `docs/ACCEPT-M16.md` 记录真实测试输出摘要
- [ ] 最终汇报按 RUN / CHANGED / TEST / OPEN 格式，TEST 贴真实输出
