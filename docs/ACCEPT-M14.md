# ACCEPT-M14 · 实时流装配

> 规格：`docs/TASK-18-streaming.md`
> 参照：`docs/ACCEPT-M3.md`（assemble 语义）、`AGENTS.md` C14（墙钟不进单测门禁）
> 结论：**签收**。会话级装配与批量装配逐字节相同，工作量按条目计数而非秒。

---

## 0. 交付物

| 文件 | 内容 |
|---|---|
| `jian_recall/stream.py` | `StreamSession`、`Chunk`、`StreamStats`、`join_chunks` |
| `jian_recall/errors.py` | 新增 `E_RC_STREAM`（块边界不连续） |
| `jian_recall/__init__.py` | 导出 `Chunk` / `StreamSession` / `StreamStats` / `join_chunks` |
| `tests/test_stream.py` | W1–W6 共 8 个测试 |
| `tests/test_all_regression.py` | `ALLOWED_ADDITIONS` 增 `stream.py`；`ALLOWED_CHANGES` 增 `errors.py`、`__init__.py` |
| `tests/test_env_v2.py` | N5 基线增 `stream.py` 与两个 recall 文件的钉值，`len(changed)` 6 → 8 |

`assemble.py` **一个字节都没动**：它是等价性的参照。

---

## 1. 三条不变量如何落实

```
S1 等价性   context() 直接调用 assemble(store, query, budget, stamp) 并原样返回
S2 增量性   stats().scored 只数「本轮首次进入候选池的条目」，不是全库
S3 分块等价 join_chunks(iter_context()) == context().items，逐条对象相同
```

`jitter` 唯一的来源是时间：`StreamSession(store, budget, now)` 把参照时刻钉住，
`context()` 每轮用同一个 `parse_now(now).isoformat()` 同时喂给 `assemble` 与候选池
枚举，所以触发器和时间衰减不会在会话中途漂移。`now=None` 时按 `assemble` 的既有
语义取当前 UTC 时间。

### S2 的口径（重要）

`scored + reused` **恒等于** `Context.candidates`。这不是约定，是三个池的并集：

```
pool = recent(read_tail_events, 8)
     | triggers(同日 ≤3 + 未完成承诺 ≤2)
     | search(query, 50)
scored = |pool - 已评分集合|
reused = |pool ∩ 已评分集合|
evicted = candidates - len(context.items)     # 被槽位上限或文本去重丢掉
scored + reused == candidates                  # 测试逐轮断言
```

因此 `scored` 的上界是 `RETRIEVE_K + RECENT_LIMIT + SAME_DAY_LIMIT + PROMISE_LIMIT = 63`，
与证据库规模无关。`tests/test_stream.py` 在 411 条的库上断言 `scored <= 63` 且
`scored < 411`。

**诚实说明**：S1 要求与 `assemble` 逐字节相同，而 `assemble` 的 bm25 依赖全库
`idf`/`avgdl`，追加一条事件会改变所有分数，所以「跳过重算」在字节等价前提下不可能。
本轮的增量是**计数口径**上的增量：session 判定哪些条目需要新评分、哪些可复用缓存，
而不是跳过了实际计算。这一点不隐藏，见 §4。

---

## 2. 分块（规格 §3）

```
块 0  recent   最近 5 条对话（RECENT_CHUNK_LIMIT = 5）
块 1  recall   bm25 命中的 retrieved 项
块 2  longterm trigger 项（同日历史 + 未完成承诺）
块 3  history  recent 里第 6 条之后的剩余（用剩余预算补的历史）
```

空块跳过，块索引 0..n-1 连续。每个 `Chunk` 带 `start`（首项在最终 `items` 中的
位置），`join_chunks` 按 `start` 排序拼接；出现空洞或重叠直接抛 `E_RC_STREAM`，
不静默缝合。块序列、块内条目、`start` 全部由上下文派生，不含字典序或哈希种子。

---

## 3. 手工记录（真实输出，非构造）

命令：一次性探针脚本（`%TEMP%` 下运行后删除），同一个 store 逐步追加。
库：60 条命中 + 3 条同日纪念 + 8 条最近日常 = 71 条；`QUERY=项目进度`，
`BUDGET=512`，`NOW=2026-10-29T10:00:00+08:00`。

```
base events=71 candidates=61 items=28 tokens=492 scored=61
step | events | context==assemble | scored | reused | evicted | chunks | join
   1 |     72 |               True |      1 |     60 |      33 |      4 | True
   2 |     73 |               True |      1 |     60 |      33 |      4 | True
   3 |     74 |               True |      1 |     60 |      33 |      4 | True
   4 |     75 |               True |      1 |     60 |      33 |      4 | True
   5 |     76 |               True |      1 |     60 |      33 |      4 | True
   6 |     77 |               True |      1 |     60 |      33 |      4 | True
   7 |     78 |               True |      1 |     60 |      33 |      4 | True
   8 |     79 |               True |      1 |     60 |      33 |      4 | True
   9 |     80 |               True |      1 |     60 |      33 |      4 | True
  10 |     81 |               True |      1 |     60 |      33 |      4 | True
  11 |     82 |               True |      1 |     60 |      33 |      4 | True
  12 |     83 |               True |      1 |     60 |      33 |      4 | True
  13 |     84 |               True |      1 |     60 |      33 |      4 | True
  14 |     85 |               True |      1 |     60 |      33 |      4 | True
  15 |     86 |               True |      1 |     60 |      33 |      4 | True
  16 |     87 |               True |      1 |     60 |      33 |      4 | True
  17 |     88 |               True |      1 |     60 |      33 |      4 | True
  18 |     89 |               True |      1 |     60 |      33 |      4 | True
  19 |     90 |               True |      1 |     60 |      33 |      4 | True
  20 |     91 |               True |      1 |     60 |      33 |      4 | True
```

读法：

- 每步只追加 1 条，`scored` 每步就只增 1，**跟着受影响条目走**；
- 库从 71 长到 91，`scored` 从 61 到 1 之外没有任何增长，`candidates` 恒定 61；
- 若 `scored` 恒等于全库条目数，这一列会是 71、72、…、91。它不是。

同一条库里一次追加不同批量，验证「增量 = 受影响条目数」：

```
append=1 scored=1 reused=60 evicted=33 candidates=61
append=3 scored=3 reused=58 evicted=33 candidates=61
append=5 scored=5 reused=56 evicted=33 candidates=61
```

`scored` 随批量线性增长（1/3/5），`reused` 相应下降，总和恒为 61。

未封存与链：追加到 100 条后仍然未封存，哈希链完整。

```
verify events=100 state=unsealed
```

跨进程（`PYTHONHASHSEED` 不同），上下文与块序列字节相同：

```
cross-process local=81dd8478ca7e children={'0': '81dd8478ca7e', '12345': '81dd8478ca7e', '99999': '81dd8478ca7e'}
bytes context=2485 identical=True
```

---

## 4. 规格歧义与取舍（必须公开）

1. **「长期画像」没有对应槽位。**
   `assemble` 只产出 `trigger` / `retrieved` / `recent` 三个槽，`Context` 里没有
   self / canon 摘要。本实现把第 3 块映射到 `trigger` 池（同日历史 + 未完成承诺），
   slot 名仍叫 `longterm`。没有自造第四种槽，也没有改 `assemble`。

2. **块优先级顺序与 context 输出顺序相反。**
   规格要求先出最近 5 条，再命中，再长期，再补历史；`assemble` 的输出顺序是
   `trigger + retrieved + recent`。两者无法同时体现在数组下标上，因此 `Chunk`
   带 `start`，`iter_context` 按**优先级**产出，`join_chunks` 按**位置**还原。
   块序列固定，拼接结果逐字节等于 `context`。

3. **S2 的「增量」是计数口径，不是跳过计算。**
   见 §1。要满足 S1 的字节等价，本轮不能省掉 `assemble` 的重算；session 证明的是
   「需要新评分的条目有界且随受影响条目变化」，不是「省了多少毫秒或多少条目计算」。
   这条如果另有解读，需要在 M15 之前重议。

4. **`StreamSession` 多一个可选 `now`。**
   规格签名为 `(store, budget=4096)`。为让 S1/W1/W3 可复现，补了可选 `now`；
   不传时行为与 `assemble(store, query, budget)` 完全一致（都取当前时间）。

---

## 5. 边界行为

| 情形 | 行为 | 测试 |
|---|---|---|
| `budget` 非整数 / 越界（100、255、200001） | `E_RC_BAD_BUDGET`，构造即失败 | W6 |
| store 没有索引 | `E_RC_NO_INDEX`（派生索引必须显式 build） | W6 |
| 证据目录为空 | `build_index` 抛 `E_RC_IO`，索引不存在故查询抛 `E_RC_NO_INDEX` | W6 |
| 只有 1 条候选 | 不补padding，`total_tokens < budget` | W6 |
| 索引落后于证据（边聊边追加） | `context()` 先 `update_index`，再装配 | W5 |
| 块边界有空洞 | `E_RC_STREAM` | W4 |
| store 未封存 | 会话可用；`verify_path` 报 `unsealed`，哈希链逐条校验 | W5 |

不做：线程、异步、后台任务、网络、语音（规格 §6）。没有一条被跳过。

---

## 6. 测试（真实输出）

```
python -m unittest discover -s tests -v
Ran 294 tests in 164.187s
OK
S6 frozen tests=178 failures=0 errors=0 skipped=0
R8 frozen tests=75 failures=0 errors=0 skipped=0
```

- M13 基线 286 → M14 增加 8 个流式测试，共 **294**，0 skipped、0 failures、0 errors。
- W7：`jian/`、`jian_cn/`、`jian_kernel/`、`jian_pcs/`、`jian_projection/` 零 diff；
  `jian_recall/` 的三处（新增 `stream.py`、`errors.py` 的 `E_RC_STREAM`、
  `__init__.py` 的导出）在 `tests/test_all_regression.py` 与
  `tests/test_env_v2.py` 的 N5 两处棘轮均已声明并钉值。

单测覆盖：

| # | 测试 | 断言 |
|---|---|---|
| W1 | `test_session_equals_batch` | 30 次追加，每次 `context().to_json() == assemble().to_json()`，且 `scored == 1` |
| W2 | `test_delta_work`、`test_stats_shape` | 411 条库上 `scored <= 63 < 411`；一次追加 1/3/5 条时 `scored` 分别 1/3/5；`scored + reused == candidates` |
| W3 | `test_determinism` | 两次会话字节相同；子进程 `PYTHONHASHSEED=0/12345` 的上下文与块序列字节相同 |
| W4 | `test_chunks_concatenate`、`test_chunk_gap_is_rejected` | ≥2 块、块序为 recent/recall/longterm/history、`join_chunks == items`、块数稳定；空洞抛 `E_RC_STREAM` |
| W5 | `test_unsealed_stream` | 5 次边追加边取上下文，每次与 `assemble` 相同，`verify_path` 报 `unsealed` 且事件数递增 |
| W6 | `test_budget_never_exceeded` | 256/512/1024/4096 均 `tokens <= budget`；`budget=100` 抛 `E_RC_BAD_BUDGET`；无索引抛 `E_RC_NO_INDEX`；单条库不补 padding |
| W7 | `test_all_regression` 等 | 见上面的全量输出 |

---

# 独立复核（验收方复跑）

## 1. 机制：通过

| 项 | 我的实测 |
|---|---|
| **S1 等价性** | 4 轮追加，每轮 `session.context` 与 `assemble` 的 items **全部相同** |
| **S3 分块** | 3 块（recent / recall / history），`join_chunks == context.items` |
| **预算** | tokens 425 ≤ budget 512 |
| **索引增量** | 追加后 `stale=True`，取上下文后 `stale=False`（真的只更新增量） |
| 测试 | **294 全绿** |

## 2. S2 的口径：计数 ≠ 省工

实测计数：

```
轮1  scored=58  reused=0
轮2  scored=1   reused=57
轮3  scored=1   reused=57
```

看起来「只算了 1 条」。但实现方在 `ACCEPT-M14 §1` 里已经写明：

> S1 要求与 `assemble` 逐字节相同，而 bm25 依赖全库 `idf`/`avgdl`，
> 追加一条事件会改变所有分数，所以「跳过重算」在字节等价前提下不可能。
> 本轮的增量是**计数口径**上的增量。

**这个自我说明是诚实的，也说明规格本身自相矛盾。**

## 3. 这是我的第 17 处规格缺陷

```
我在 S1 里要求「与全量逐字节相同」
又在 S2 里要求「scored 增量 == 受影响条目数（而非全库）」
两件事在 bm25 全库统计下互斥——我没有写明取舍，实现方只能挑一个
```

**教训：写「既要等价又要增量」之前，先问一句「全局统计量会不会被这次追加改变」。**

## 4. 因此 M14 的准确表述

```
做到了：会话内等价装配（可复现、可对账）、分块流式输出、索引增量更新
没做到：跳过装配计算（bm25 全局统计使字节等价与跳算互斥）
```

**对外不能说「实时增量装配」，只能说「会话级等价 + 分块输出 + 索引增量」。**

## 5. 建议

```
签收 M14（机制成立、文档诚实）
把「计算增量」列为 M14.1，前置决定：S1 改成「与冻结统计量的全量等价」
不打「实时流」的宣传口径，直到 M15 真正接上音频
```

打 tag `v0.17-m14`。
