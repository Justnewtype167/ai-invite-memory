# TASK-24 · 用户卡增量折叠（M35）

> 目标：200k 事件的用户卡从 O(n) 降到 O(delta)，且与全量推导**逐字段等价**。
> 用户卡不进内核，所以这件事不改变 `kid`——速度优化不该动身份。

---

## 0. 一句话

```
卡片记住「折到哪」，而不是每轮重读全部证据；
校验不通过就老老实实重折。正确性优先于速度。
```

---

## 1. 问题（先量，再改）

参考实现 `derive_user_card` 对本机合成库的实测（单次冷推导）：

| 事件数 | 耗时 |
|---|---|
| 3k | 31.8 ms |
| 20k | 425.9 ms |
| 50k | 4171 ms |
| 200k | 30963 ms |

增长是**超线性**的，不是 O(n) 常数大：`_promise_done` 对每条承诺扫描它之后的全部事件，
承诺多时退化为 O(n²)。20k 时卡片已占单轮约四分之一；200k 时这条路根本走不通。

---

## 2. 状态：只记「折到哪」和「折出了什么」

`CardState`（frozen dataclass，`aiinvite/persona/card_fold.py`）：

```
digest        规则表摘要（json 规范化后的 sha256）
count         已折入的事件数（全事件列表位置，含 persona / assistant）
last_id       第 count 条的 event_id
tail          最后 TAIL 条事件的指纹
call / call_evidence / never / taboo_names / self_name / self_evidence
people / people_seen / taboos / promises / ongoing
likes / like_seen / dislikes / dislike_seen
```

`count` 与 `last_id` 用**原始事件列表**的位置，不预先过滤：过滤（人格事件、assistant 轮）在折叠循环里逐事件做，
这样「第 count 条」始终指得回 `events` 本身，校验逻辑不需要维护第二套索引。

---

## 3. 什么时候可以只折 delta

`_extension(events, state)` 必须同时满足：

1. `state.count <= len(events)`
2. `events[state.count - 1].event_id == state.last_id`
3. `_tail_fingerprint(events[state.count - TAIL : state.count]) == state.tail`
4. delta 段（`events[state.count:]`）的 event_id 严格递增

任一条不成立 → 丢弃状态，全量重折。规则表摘要（`_rules_digest`）变化同样触发全量重折。

第 3 条是被测试逼出来的，不是设计时想到的：
`tests/test_card_fold.py::test_rewritten_evidence_rebuilds` 构造了「事件数相同、末条 id 相同、但中间一条文本被改写」的库。
只校验 `count` 与 `last_id` 时，折叠结果（`call = 小张`）与参考实现（`call = ""`）不一致。
指纹只算 `TAIL = 8` 条，成本是 O(1)，但把「同长度改写」这一类漏判关掉了。

**为什么不做部分信任**（例如只重折被改的那一段）：折叠是有状态的——早期一条禁忌词会让后来的同名被跳过，
一条完成标记会关掉更早的承诺。任何局部重折都要先证明「后续状态不受影响」，而这个证明的复杂度远高于重折本身。
宁可慢一点重折，也不要一个说不清何时成立的缓存。

---

## 4. 折叠本身

`_fold` 单遍扫描 delta，事件级过滤：

```python
if is_persona_event(event) or event.role == "assistant":
    continue
```

AI 自己的话不塑造用户卡（M22 的教训：assistant 轮的「你宝贝」曾让卡学到 `忌称：你宝贝`）。

随后依次：称呼（复用 `_scan_address`）/ 自称 / 亲属称呼 / `directive(kind=lock)` 禁忌 / 承诺 / 里程碑 / 偏好。
逐字段语义与参考实现一致，包括几处容易漏的：

- 禁忌名一旦出现，之后同名的称呼不再被采纳；最终 `call` 若落在禁忌集合里则清空
- 承诺被**任意**更晚事件里的完成标记（`已完成 / 已办 / 做到了`）关闭，不看说话人
- 里程碑只保留最后 3 条
- 偏好按首次出现顺序追加，value 截断到 20 字符

---

## 5. 等价性怎么证明

`tests/test_card_fold.py` 的 `assertMatches(events, rules)`：对**每一个前缀**
比较 `fold_user_card(events[:stop], state)` 与 `derive_user_card(events[:stop])` 的 `to_payload()`。

不是只在末尾比一次：每一步都必须是同一个卡。这样任何「折着折着偏了」的实现都会在某一步暴露，
而不是靠一次幸运的终态相等蒙混过去。

14 条：空库 / 称呼边界（老周 + 忌称两枚）/ assistant 轮 / 人格事件 / 承诺关闭 / 承诺未关闭 /
亲属与里程碑 / 偏好顺序与 evidence / 规则表变更 / 证据缩短 / 证据改写 / 缓存不改变结果 /
`corpus/personas.jsonl` 40 个人格 / 随机流（seed 20261107，20 条）。

另在 `tests/test_host_adapter.py` 加两条端到端：

- `test_incremental_card_matches_full_derivation`：每轮之后卡块必须等于 `derive_user_card(read_evidence(store)).text()`
- `test_warm_session_matches_a_cold_one`：热会话的 prompt 与冷会话逐字节相同

---

## 6. 预算裁剪：从平方级改为二分

`UserCard.text()` 在超过 `CARD_BUDGET = 400` 时按 `DROP_ORDER` 从尾部丢条目。原实现对每个候选条目重新渲染一次，
条目多时是 O(条目² × 渲染)；名字多的卡可以到几百条。

现在：

- `_drop_count(data)` 算出可丢总数
- `_truncated(data, drops)` 在浅拷贝上应用前 `drops` 次删除，不改原数据
- 对 `drops` 二分，找最小的「渲染后 ≤ 400」的值；全部丢完仍超预算则抛 `E_PERSONA_BUDGET`

`_drop_one` 从包内删除，逻辑作为 oracle 移到 `tests/test_card_budget.py`：
逐步丢弃的参考结果必须与新实现的输出**精确相等**（5 组 sizes，含 dislikes=500 / likes=500 / people=100）。

---

## 7. 实测

| 事件数 | 旧路径 derive | 冷折叠 | 热折叠（+1 事件） |
|---|---|---|---|
| 3k | 31.8 ms | 32.6 ms | 0.34–1.2 ms |
| 20k | 425.9 ms | 267.6 ms | 0.3–1.2 ms |
| 50k | 4171 ms | 937.8 ms | 0.3–1.2 ms |
| 200k | 30963 ms | 1213 ms | 0.3–1.2 ms |

热折叠与 n 无关，是这一层的设计目标。冷折叠仍是 O(n)，无法避免——第一次总是要把证据读完。

---

## 8. 残余瓶颈（别把这一条读成「性能问题解决了」）

端到端 `HostSession.prompt_for`，20k 事件，**每次追加事件之后**（真实每轮形态）：

| 阶段 | 耗时 | 原因 |
|---|---|---|
| 索引 | 860–1180 ms | 追加后索引 stale，`build_index` 全量重建 |
| 内核 | 470–580 ms | 增量编译，但快照序列化整张 graph |
| 证据 | 180–245 ms | 段文件整体重解析（单段 100 条） |
| pins | 67–97 ms | 每轮全扫 |
| 卡片 | 3–21 ms | 本次优化对象 |
| **合计** | **约 1.7 s** | |

所以 P3 之后的真实结论是：**卡片不再是瓶颈，每轮仍有约 1.7 s 花在别处。**
此前文档里「20k 单轮 160–210 ms」是**不追加事件**时的缓存命中路径，不能当作每轮成本——已一并更正。

---

## 9. 未做

- 索引增量更新（追加事件只 patch 新增项，而不是重建）——下一个最大项
- 内核快照增量序列化（只写变化的子图）
- pins 增量（pin / unpin 是显式指令，本可以只更新列表）
- 证据段内增量解析（段文件是 append 的，理论上只需解析新增行）
