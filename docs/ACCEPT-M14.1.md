# ACCEPT-M14.1 · 增量装配的口径修正

> 规格：`docs/TASK-19-incremental-scope.md`
> 前置：`docs/ACCEPT-M14.md`（M14 的 S1/S2 互斥与独立复核 §2–§4）
> 结论：**签收**。检索不增量，只把时间触发布成增量；S1 的字节等价没有被放弃。

---

## 0. 这一轮改了什么

M14 的 S2 说「`scored` 增量 == 受影响条目数」，S1 又说「与全量逐字节相同」。
bm25 的分数依赖全库 `N` / `avgdl` / `idf`，追加一条事件会改变所有分数，
两者互斥。M14.1 的处理是：

```
retrieve   明确不可增量，retrieve_scored 恒等于候选池条目数，本轮不减少（写进报告）
trigger    按查询谓词分桶缓存，可独立失效，真省工
```

| 文件 | 改动 |
|---|---|
| `aiinvite.recall/trigger.py` | 拆出 `trigger_parts`，两个子查询可独立取数 |
| `aiinvite.recall/assemble.py` | 拆出 `_assemble_pools`，与流式会话共享 pool → context |
| `aiinvite.recall/stream.py` | 四计数 + `(key, generation)` 谓词缓存 + 索引重建检测 |
| `tests/test_stream.py` | X1–X5、X3b 与 W3–W6 |
| `tests/test_all_regression.py` | `ALLOWED_CHANGES` 增 `trigger.py`、`assemble.py` |
| `tests/test_env_v2.py` | `stream.py` 新钉值；`M12_EDITS` 增两个 recall 文件；`len(changed)` 8 → 10 |

`assemble()` 的签名与语义不变，`assemble(store, query, budget, now)` 仍是等价性参照。

---

## 1. 四个计数

```python
StreamStats(
    trigger_scanned:int,   # 失效判定时查看的新事件条数（冷启动 = 0）
    trigger_loaded:int,    # 触发查询实际取回的行数（冷启动 <= 5，全命中 = 0）
    trigger_reused:int,    # 从缓存直接返回的子查询数（0..2，不是天数）
    retrieve_scored:int,   # 恒等于 Context.candidates，本轮不减少
)
```

`scanned` 与 `loaded` 分开记，是因为它们度量两件事：冷启动没有新事件
（`scanned == 0`）但缓存为空必须真取（`loaded <= 5`）。把冷启动的代价藏进
`scanned` 或干脆记 0，都会让报告失真。

---

## 2. 缓存键与失效

缓存按查询谓词分桶，条目是 `(key, generation, hits)`：

```
same_day   key = (now 的 MM-DD, now 的 year)   generation = same_day 代
promises   key = 全局                           generation = promises 代
```

| 触发条件 | 失效哪个子查询 |
|---|---|
| 追加事件的 `md == target_md` 且 `year < target_year` | `same_day` |
| 追加事件是承诺（`is_promise`） | `promises` |
| 追加事件与两者都无关 | **一个都不失效** |
| `now` 改变（`md` 或 `year`） | 键变，`same_day` 失效；`promises` 不受影响 |
| 证据 head 回退（`lsn` 回退） | 全部 |
| 索引重建（索引 inode 变化） | 全部 |

索引身份取 `(st_ino, st_ctime_ns)`，以 inode 变化判重建；只有 inode 为 0 的
文件系统才退回 ctime。否则 `update_index` 的普通写回会被误判成重建，
每次追加都全失效。

---

## 3. 手工记录（真实输出）

命令：一次性探针脚本（`%TEMP%` 下运行后删除）。同一个 store 逐步追加。
库：60 条命中 + 3 条同日纪念 + 8 条最近日常 + 2 条承诺 = 73 条；
`QUERY=项目进度`，`BUDGET=512`，`NOW=2026-10-29T10:00:00+08:00`。

```
store events=73 budget=512 query='项目进度'
cold_start=61 candidates
cold stats={'trigger_scanned': 0, 'trigger_loaded': 5, 'trigger_reused': 0, 'retrieve_scored': 61}
append 10: identical=10/10
scanned  = [1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
loaded   = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
reused   = [2, 2, 2, 2, 2, 2, 2, 2, 2, 2]
retrieve = [61, 61, 61, 61, 61, 61, 62, 63, 63, 63]
next_day identical=True stats={'trigger_scanned': 0, 'trigger_loaded': 0, 'trigger_reused': 1, 'retrieve_scored': 60}
rebuild  identical=True stats={'trigger_scanned': 0, 'trigger_loaded': 2, 'trigger_reused': 0, 'retrieve_scored': 60}
md_hit   identical=True stats={'trigger_scanned': 1, 'trigger_loaded': 3, 'trigger_reused': 1, 'retrieve_scored': 63}
promise  identical=True stats={'trigger_scanned': 1, 'trigger_loaded': 2, 'trigger_reused': 1, 'retrieve_scored': 62}
```

读法：

- 追加 10 条，`scanned` 恒为 1（每次只追加 1 条），`loaded` 恒为 0，
  `reused` 恒为 2 —— 普通对话不失效任何子查询，这是本轮真正省工的地方。
- `retrieve_scored` 从 61 缓增到 63，恒等于 `Context.candidates`；
  **它没有下降，也没有被宣称减少**。
- 跨天（`now = 2026-10-30`）：`same_day` 键变而失效，`promises` 仍命中，
  `reused == 1`，结果仍与 `assemble` 字节相同。
- 索引重建：`reused == 0`，`loaded == 2`，结果仍相同。
- 同日命中：`same_day` 失效、`promises` 命中，`reused == 1`、`loaded == 3`。
- 新承诺：`promises` 失效、`same_day` 命中，`reused == 1`、`loaded == 2`。
- 所有分支（包括跨天与重建）的 `context.to_json()` 与 `assemble.to_json()` 相同。

---

## 4. 验收对照

| # | 测试 | 真实输出 |
|---|---|---|
| X1 | `test_still_equivalent` | `steps=30 identical=30 last=(1, 0, 2, 63)` |
| X2 | `test_trigger_is_delta_sized` | `store_size/one/ten=[(60, 1, 10), (400, 1, 10)]` |
| X3 | `test_trigger_reused_per_subquery` | 冷启动 `(0, 5, 0)` → 全命中 `(0, 0, 2)` → 无关 `(1, 0, 2)` → 同日 `(1, 3, 1)` → 承诺 `(1, 2, 1)` |
| X3b | `test_reused_is_not_days` | `days=30 reused_set=[2]` |
| X4 | `test_cache_invalidation` | `now_day/reused=1 now_year/reused=1 rollback/reused=0 rebuild/reused=0` |
| X5 | `test_retrieve_not_claimed_incremental` | `retrieve_scored/candidates=[61, 61, 61, 61]` |
| W3 | `test_determinism` | `bytes=2404 seeds=0,12345 identical=True` |
| W4 | `test_chunks_concatenate` | `chunks=4 slots=['recent','recall','longterm','history'] items=27` |
| W5 | `test_unsealed_stream` | `events=48 state=unsealed` |
| W6 | `test_budget_never_exceeded` | `budgets=256,512,1024,4096 scarce_items=1` |
| X6 | `test_all_regression` | `S6 frozen tests=178 failures=0 errors=0 skipped=0` |

---

## 5. 诚实说明

```
做到：trigger 的两条子查询按谓词缓存，普通追加不失效，等价性保住
没做：retrieve 的减少 —— bm25 全库统计下不可能，本轮明确不宣称
```

对外只能说「**时间触发增量 + 会话级等价**」，不能说「检索增量」。
`retrieve_scored` 与 `Context.candidates` 同时出现，才是这一轮的完整口径。

---

## 6. 测试（真实输出）

```
python -m unittest discover -s tests
Ran 298 tests in 238.176s
OK
S6 frozen tests=178 failures=0 errors=0 skipped=0
N4 m1 tests=31 failures=0 errors=0 skipped=0
```

- M14 基线 294 → M14.1 因测试重写净增 4 个，共 **298**，0 skipped、0 failures、0 errors。
- 两处棘轮：`test_all_regression.py` 声明 `trigger.py`、`assemble.py`；
  `test_env_v2.py` 更新 `stream.py` 钉值并把两个 recall 文件加入 `M12_EDITS`，
  `len(changed)` 8 → 10。改了没声明失败，声明了没改也失败。
