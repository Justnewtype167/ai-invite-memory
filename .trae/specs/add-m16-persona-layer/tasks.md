# Tasks

> 执行约束：只用 Python 3.11+ 标准库（unittest，零第三方依赖）；源码 ASCII；单文件 ≤700 行；
> 不许 `TODO` / `pass` / `NotImplementedError`；不许 skip 测试；不许降低验收标准。
> 提交边界（用户指令）：Task 3 / Task 4+5 / Task 6+7 各一次提交，每次提交前跑全量。
> `record_kernel` 的人格事件留痕测试随 Task 3 批次提交。

- [ ] Task 1: 事件层与胶囊写入扩展
  - [ ] SubTask 1.1: `jian/event.py` 的 `KIND_VALUES["directive"]` 增加 `"trait"` / `"trait_off"`（不动其它校验）
  - [ ] SubTask 1.2: `jian/capsule.py` 的 `append_event` 与 `append_payload_event` 增加可选 `model/prompt_sha/quant/weights_sha/temp_milli/seed` 并透传给 `new_event`
  - [ ] SubTask 1.3: 验证：`python -m unittest tests.test_ev_types tests.test_ev_compat tests.test_capsule -v` 全绿；手写一段临时脚本确认 `directive(kind="trait")` 与 v2 `proposal(self.style_card)` 可写入并 `parse_event` 读回

- [ ] Task 2: P0 —— 内核跳过人格事件（依赖 Task 1）
  - [ ] SubTask 2.1: `jian_kernel/compiler.py`：`EVENT_TYPES` 加 `"refusal"`；新增 `PERSONA_TARGETS`、`PERSONA_DIRECTIVE_KINDS`、`is_persona_event`、`core_events`；`_compile` 全程改用 `core`（`moment`/`check_proposals`/`_select_style`/`_model_ids`/`content`/`head`），`core` 为空抛 `E_KN_IO`
  - [ ] SubTask 2.2: `jian_kernel/incremental.py`：`core_events` 过滤、`delta` 只取 core、`_apply_delta`/`_kernel_from_snapshot`/`_compile_full` 的 `moment`、`head`、`_build_context(core)` 全部改用 core
  - [ ] SubTask 2.3: `jian_kernel/kernel.py`：新增 `PERSONA_TARGETS` / `PERSONA_DIRECTIVE_KINDS` 常量（L1 定义，L2 引用，避免上层反向依赖）；`jian_kernel/gate.py` 白名单改为 `STYLE_TARGETS + PERSONA_TARGETS`
  - [ ] SubTask 2.4: 新建 `tests/test_persona.py`，先写 `test_refusal_compiles` 与 `test_persona_events_keep_kid`（六种各 100 条：kid 逐字节不变 + `self_md`/`canon_md`/`state`/`graph` 逐字节不变 + 增量 kid 相同 + `reconcile` ok）
  - [ ] SubTask 2.5: 棘轮（此步只声明 `gate.py` + `kernel.py`）：`tests/test_all_regression.py` 包元组加 `jian_persona` 与 7 个 `ALLOWED_ADDITIONS`、`ALLOWED_CHANGES` 新增两条；`tests/test_env_v2.py` 更新 `incremental.py`/`compiler.py` 摘要，新增 `gate.py`/`kernel.py` 钉值，`len(changed)` 10 → 12
  - [ ] SubTask 2.6: 验证：`python -m unittest discover -s tests` 全绿且总数 = 315 + 2 = 317
  - [ ] SubTask 2.7: **单独一次提交**（P0 提交），提交后立即向用户报告 317 全绿，等确认再往下

- [ ] Task 2C: 只被人格事件推进时的记录行为（依赖 Task 2；随 Task 3 批次提交）
  - [ ] SubTask 2C.1: 不改 `jian_kernel/history.py`；按实测钉死行为：`record_kernel` 不产生新版本（`written=False`、版本号与 HISTORY 字节不变）
  - [ ] SubTask 2C.2: 新增 `test_record_persona_only_keeps_version`（版本号不变 + HISTORY 字节不变 + `verify_kernel` 通过 + 人格事件仍在证据链里）
  - [ ] SubTask 2C.3: `docs/ACCEPT-M16.md` 写明：特质增删只留痕在证据链，不进版本账本（宪章 A2 的可追溯性由证据链承担）


- [ ] Task 3: 特质表（依赖 Task 2）
  - [ ] SubTask 3.1: 新建 `jian_persona/{__init__.py,errors.py,model.py,traits.py}`，错误码按 spec 固定
  - [ ] SubTask 3.2: 新建 `jian_kernel/data/traits.json`（6 条，冲突引用闭合，含 `话痨` 用于测上限）
  - [ ] SubTask 3.3: `traits.py`：`load_vocabulary`、`resolve_traits(events, vocabulary, mode)`、`trait_activations`；上限 5、冲突（risk 低者胜/同 risk 后启用胜）、高危按模式门控并写 `reasons`、未批准提案抛 `E_PERSONA_UNAPPROVED`
  - [ ] SubTask 3.4: 写 S1–S4 四个测试并跑绿

- [ ] Task 4: 风格卡与复读守卫（依赖 Task 1、2）
  - [ ] SubTask 4.1: `jian_persona/style_card.py`：`StyleCard` 解析/校验（800 字符、examples ≤15、counter ≤3）、`record_style_card`（v2 proposal）、`load_style_card`、`style_input(events, exclude)`、`assert_redacted`、`echo_guard`
  - [ ] SubTask 4.2: 写 S5–S7 三个测试并跑绿（含 `parse_event` 往返）

- [ ] Task 5: 用户卡（依赖 Task 2）
  - [ ] SubTask 5.1: 新建 `jian_persona/data/user_card_rules.json`（中文正则放数据里，代码保持 ASCII）
  - [ ] SubTask 5.2: `jian_persona/user_card.py`：`derive_user_card(events, rules)`、`UserCard.to_payload()`、`UserCard.text()`（≤400 的固定优先级裁剪）、每字段带 evidence
  - [ ] SubTask 5.3: `pin_user_card(context, card, budget)`（首位 pinned，超预算从尾部丢，卡片单独超预算抛 `E_PERSONA_BUDGET`）
  - [ ] SubTask 5.4: 写 U1–U4 四个测试并跑绿（U1 含子进程：`PYTHONUTF8=1` + `encoding="utf-8"`）

- [ ] Task 6: 共用管线与四组 prompt（依赖 Task 3、4、5）
  - [ ] SubTask 6.1: `jian_persona/view.py`：`build_persona_view`、`PersonaView`（`kid`/`head`/`traits`/`conflicts`/`reasons`/`style_card`/`user_card`/`self_md`）、`to_prompt(group)`
  - [ ] SubTask 6.2: `self_md` 含 `## Traits` 与 `### Conflicts`（写明哪条胜出、双方事件 id、理由）
  - [ ] SubTask 6.3: 写 `test_persona_not_in_pcs` 并跑绿

- [ ] Task 7: 对照工具与结果（依赖 Task 6）
  - [ ] SubTask 7.1: 新建 `jian_persona/data/facts.jsonl`（30 条事实探针）
  - [ ] SubTask 7.2: 新建 `tools/style_experiment.py`：`--group A B C D`、`--models`、`--dry-run`、`--limit`、`--store`；复用 `tools/responder_ollama.call_ollama` 与 `jian_pcs` 打分；模型不可用 → 非零退出 + 可读原因
  - [ ] SubTask 7.3: 跑 `--dry-run` 记录四组 prompt 长度/token；再真跑一次 `--group A B C D --models qwen3.5:9b glm4:9b`
  - [ ] SubTask 7.4: 写 `docs/RESULTS-style.md`：真实数字，或真实「未测量」原因 + 既有 V5 基线 PCS=0.6491，不许编造

- [ ] Task 8: 收尾验收（依赖 Task 1–7）
  - [ ] SubTask 8.1: 写 `docs/ACCEPT-M16.md`（十二验收 + 两项额外测试的真实输出摘要）
  - [ ] SubTask 8.2: 全量 `python -m unittest discover -s tests -v`，全绿 0 skipped，记录真实 `Ran N tests`
  - [ ] SubTask 8.3: 按 RUN / CHANGED / TEST / OPEN 汇报（TEST 贴真实输出）

# Task Dependencies

- Task 2 依赖 Task 1（没有 `trait` kind 与 proposal 溯源字段，写不出被测事件）
- Task 2C 依赖 Task 2（人格事件留痕建立在实测行为之上，不改 history.py）
- Task 3 / 4 / 5 依赖 Task 2（所有派生都建立在 `core_events` 之上）；Task 3、4、5 之间互不依赖，可并行
- Task 6 依赖 Task 3、4、5
- Task 7 依赖 Task 6
- Task 8 依赖全部
- 用户要求：P0 已单独提交并验收通过 317 全绿；之后按 Task 3 / Task 4+5 / Task 6+7 三批提交
- 若单次改动超过 800 行，按上述三批边界继续拆分落地
