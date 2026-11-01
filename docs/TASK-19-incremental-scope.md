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
trigger  同日 ≤3 / 未完成承诺 ≤2
         按「天」分桶      追加只影响当天桶      可缓存，真省工
retrieve bm25 top-K      全局统计，**不可增量**   明确不碰
```

**本轮只把 trigger 做成增量，并把 retrieve 的不可增量写进报告。**

---

## 3. 新增的两个计数

```python
StreamStats(
    trigger_scanned:int,   # 本轮实际扫描的事件条数（按天桶）
    trigger_reused:int,    # 直接命中的缓存天数
    retrieve_scored:int,   # bm25 条目数（保持不变，**不宣称减少**）
)
```

| 计数 | 断言 |
|---|---|
| `trigger_scanned` | 追加一条后 == 1（只扫新增），与历史总量无关 |
| `trigger_reused` | 未跨天时 == 已缓存天数 |
| `retrieve_scored` | **恒等于候选池条目数**，本轮不做减少 |

---

## 4. 缓存失效（最容易出错的地方）

| 触发条件 | 动作 |
|---|---|
| 追加事件且落在**同一天** | 只失效当天桶 |
| 追加事件落在**新的一天** | 新增一个桶，旧桶不动 |
| 证据 head 回退（截断/回滚） | **全部失效** |
| 索引重建 | 全部失效 |
| 会话 `now` 改变 | 全部失效（同日判定依赖它） |

**任何一条漏掉，都会产出一个「与全量不同」的上下文——而这正是 S1 要防的。**

---

## 5. 验收（六个）

| # | 测试 | 断言 |
|---|---|---|
| X1 | `test_still_equivalent` | 30 次随机追加，每次 `session.context == assemble`（字节级，保住 S1） |
| X2 | `test_trigger_is_delta_sized` | 追加 1 条后 `trigger_scanned == 1`；追加 10 条后 `== 10`；与库大小无关 |
| X3 | `test_trigger_reused_within_day` | 同一天内多轮查询，`trigger_reused == 已缓存天数` |
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

