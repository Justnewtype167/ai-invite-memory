# TASK-19 · 增量装配的口径修正（M14.1）

> 修 M14 的矛盾：S1 要「与全量逐字节相同」，S2 要「跳过重算」——
> 在 bm25 全库统计下这两件事互斥。本轮把口径**收窄到能成立的那部分**。

---

## 1. 先把事实摆清楚

```
bm25 的分数依赖全库统计（N、avgdl、idf）
追加一条事件 → 统计变化 → 所有条目的分数变化
⇒ 只要坚持「与全量逐字节相同」，检索就**不可能**跳过重算
```

**任何声称「检索也增量」的实现，必然偷偷改了口径。**

---

## 2. 能真正增量的部分：时间触发与最近窗口

```
recent   尾部 N 条        追加只影响尾部        O(1) 读取，已是增量
trigger  同日 ≤3 / 未完成承诺 ≤2                 可缓存，真省工
retrieve bm25 top-K      全局统计，**不可增量**   明确不碰
```

**本轮只把 trigger 做成增量，并把 retrieve 的不可增量写进报告。**

### 2.1 trigger 的真实查询键（先读代码，再谈缓存）

`jian_recall/trigger.py` 的两个查询**不是按天分桶**的：

```
same_day   WHERE t.md = ? AND t.year < ?   ORDER BY t.ts DESC LIMIT 3
           ⇒ 依赖「now 的 MM-DD」与「now 的 year」，不是事件自己的日期
promises   WHERE d.is_promise = 1          ORDER BY t.ts DESC LIMIT 2
           ⇒ 依赖「全库最新的两条承诺」，与日期无关
```

**所以缓存不能按「天」分桶，只能按查询谓词分桶 + 定向失效。**


---

## 3. 新增的两个计数

```python
StreamStats(
    trigger_scanned:int,   # 失效判定时查看的新事件条数（冷启动=0）
    trigger_loaded:int,    # 触发查询实际取回的行数（冷启动<=5，命中缓存=0）
    trigger_reused:int,    # 从缓存直接返回的子查询数（0..2）
    retrieve_scored:int,   # bm25 条目数（保持不变，**不宣称减少**）
)
```

**为什么拆成 scanned 和 loaded**：它们度量的是两件事，混在一个数字里，
冷启动的代价就被藏起来了。

```
scanned  失效判定：只有「新事件」才会走这条路 ⇒ 冷启动没有新事件 ⇒ 0
loaded   查询取数：冷启动缓存为空，必须真的取 ⇒ <=5 行（同日至多 3 + 承诺至多 2）
```

**冷启动的代价必须可见**，所以用 `loaded` 记，而不是把它算进 `scanned` 或干脆记 0。

| 计数 | 断言 |
|---|---|
| `trigger_scanned` | 冷启动 == 0；追加一条后 == 1；与历史总量无关 |
| `trigger_loaded` | 冷启动 <= 5；缓存全部命中 == 0；**只在失效后**才再次取数 |
| `trigger_reused` | **不是天数**：本轮有几个子查询命中缓存（`same_day` / `promises` 各算一个，取值 0..2） |
| `retrieve_scored` | **恒等于候选池条目数**，本轮不做减少 |

> `trigger_reused` 早期写成「已缓存天数」，那是错的——
> 触发查询没有「天」这个维度，硬套一个天数口径只会得到无法解释的数字。

---

## 4. 缓存失效（最容易出错的地方）

| 触发条件 | 失效哪个子查询 | 理由 |
|---|---|---|
| 追加事件的 `md == target_md` 且 `year < target_year` | `same_day` | 它进入了周年候选集 |
| 追加事件是承诺（`is_promise`） | `promises` | 它可能挤掉 top-2 |
| 追加事件与上述都无关 | **一个都不失效** | 两条查询结果都不变 |
| `now` 改变（`md` 或 `year` 变化） | 全部 | 查询键变了 |
| 证据 head 回退（截断/回滚） | 全部 | 结果集可能变小 |
| 索引重建 | 全部 | 派生数据重置 |

**「追加事件与查询无关时一个都不失效」是本轮真正省工的地方**——
普通对话轮次不会碰 triggers 的任何一个子查询。

**任何一条漏掉，都会产出一个「与全量不同」的上下文——而这正是 S1 要防的。**

---

## 5. 验收（六个）

| # | 测试 | 断言 |
|---|---|---|
| X1 | `test_still_equivalent` | 30 次随机追加，每次 `session.context == assemble`（字节级，保住 S1） |
| X2 | `test_trigger_is_delta_sized` | 追加 1 条后 `trigger_scanned == 1`；追加 10 条后 `== 10`；与库大小无关 |
| X3 | `test_trigger_reused_per_subquery` | 两轮无关键追加后 `trigger_reused == 2`；追加一条与 `md` 无关的普通对话后仍 `== 2`；追加一条匹配 `md` 的事件后 `== 1`（`promises` 仍命中）；追加一条承诺后 `== 1` |
| X3b | `test_reused_is_not_days` | 断言 `trigger_reused ∈ {0,1,2}`；跨 30 天、全程没有 `md` 命中时它依然是 2 —— 证明它**不是**天数口径 |
| X4 | `test_cache_invalidation` | 跨天 / head 回退 / 索引重建 / `now` 改变 → 缓存全失效，结果仍与全量相同 |
| X5 | `test_retrieve_not_claimed_incremental` | `retrieve_scored == candidates`（明写：本轮不减少） |
| X6 | `test_all_regression` | 现有 **294 个测试全绿**；`jian/`、`jian_cn/`、`jian_kernel/`、`jian_pcs/`、`jian_projection/` 零 diff；`jian_recall/` 改动在 `ALLOWED_CHANGES` 声明 |

---

## 6. 禁止

1. 不许为了让 `trigger_scanned` 变小而改变触发语义（首要是与全量等价）
2. 不许宣称检索增量
3. 不许用墙钟断言（C14）
4. 不许在失效条件上「差不多就行」——漏一条就等于 S1 失效

---

## 7. 完成定义

```
python -m unittest discover -s tests -v      # 全绿、0 skipped
```

并提交手工记录：

```
同一 store，追加 10 条：
  每次 context == assemble ?
  trigger_scanned 序列 ?   retrieve_scored 序列 ?
  跨天一次后 缓存是否重建、结果是否仍相同 ?
```

**trigger_scanned 必须是小常数，retrieve_scored 必须保持原值。**
两个数字一起出现，才是这一轮的诚实。

