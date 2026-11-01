# TASK-18 · 实时流装配（M14）

> 目标：把「每次查询都全量装配」改成**边聊边装**，且结果与全量逐字节相同。
> 实时形态下没有「等一下再装」的余地。

写前已过 `docs/SPEC-CHECKLIST.md` 十问；**C14 强制**：一切性能断言按工作量计，不按墙钟。

---

## 0. 一句话与边界

```
做    会话级增量装配：追加一条事件后，下一次上下文只重算受影响的部分分段产出：先给高优先级片段，再补齐
不做  不做线程、不做异步、不做网络、不接语音（那是 M14 之后的事）
```

**为什么不做并发**：并发会把「同输入同输出」变成需要证明的性质，本轮要先证明确定性。

---

## 1. 一个新东西：`StreamSession`

```python
class StreamSession:
    def __init__(self, store: Path, budget: int = 4096) -> None: ...
    def context(self, query: str) -> Assembly: ...      # 与全量等价
    def iter_context(self, query: str) -> Iterator[Chunk]: ...  # 分块产出
    def stats(self) -> StreamStats: ...                 # 工作量计数（不是秒）
```

| 方法 | 语义 |
|---|---|
| `context` | 必须与 `assemble(store, query, budget)` **逐字节相同** |
| `iter_context` | 分块产出；所有块拼接后与 `context` 相同 |
| `stats` | `scored` / `reused` / `evicted` 三个计数，用于断言工作量 |

---

## 2. 三条不变量

```
S1  等价性    session.context(q) == assemble(store, q, budget)（字节级）
S2  增量性    追加一条事件后，scored 的增量 == 受影响的条目数，而不是全库条目数
S3  分块等价  iter_context 的块串接结果 == context 的结果
```

**S2 是本轮的方法论核心**：用 `stats().scored` 证明增量，不用秒表（C14）。

---

## 3. 分块策略（优先级）

```
第 1 块  最近 5 条对话（对应「刚才说的」）
第 2 块  命中查询的记忆（bm25 排序前 N）
第 3 块  长期画像（self / canon 摘要）
第 4 块  用剩余预算补历史
```

**块边界必须确定**：同输入 → 同块序列，不许受字典序或哈希种子影响（跨进程测试覆盖）。

---

## 4. 未封存与封存的边界

```
会话进行中：store 未封存，追加事件后不重新封存（M12 已证明未封存可 verify）
超出段容量：新段自动开启（既有行为，不许改）
```

**本轮不允许因为「实时」而跳过哈希链**：每条追加仍然写 hash 与 prev。

---

## 5. 验收（七个）

| # | 测试 | 断言 |
|---|---|---|
| W1 | `test_session_equals_batch` | 随机 30 次追加，每次 `context(q)` 与 `assemble` **逐字节相同** |
| W2 | `test_delta_work` | `scored` 增量 ≤ 受影响的条目数 + 常数；断言的是**计数**，不是时间 |
| W3 | `test_determinism` | 同一 store 两次 `context` 相同；**跨进程（不同 PYTHONHASHSEED）字节相同** |
| W4 | `test_chunks_concatenate` | `iter_context` 至少 2 块；拼接结果 == `context`；块数稳定 |
| W5 | `test_unsealed_stream` | 未封存 store 上边追加边取上下文，全程可用 |
| W6 | `test_budget_never_exceeded` | 任意时刻 `tokens <= budget`；空库/小预算的边界行为明确 |
| W7 | `test_all_regression` | 现有 **286 个测试全绿**；`jian/`、`jian_cn/`、`jian_kernel/`、`jian_pcs/`、`jian_projection/` 零 diff；`jian_recall/` 改动必须在 `ALLOWED_CHANGES` 声明 |

---

## 6. 禁止

1. 不许引入线程 / 异步 / 后台任务
2. 不许用墙钟断言性能（C14）
3. 不许改 `assemble` 的既有语义（它是等价性的参照）
4. 不许跳过哈希链（实时不等于不可验证）
5. 不许让块序列依赖哈希种子或字典顺序

---

## 7. 完成定义

```
python -m unittest discover -s tests -v      # 全绿、0 skipped
```

并提交手工记录（写进 `docs/ACCEPT-M14.md`）：

```
同一 store，逐步追加 20 条：
  每一步  context == assemble ?   scored 增量 ?
  分块    块数 ?  拼接 == context ?
  跨进程  kid/上下文 是否字节相同 ?
```

**`scored` 增量必须随受影响条目变化，而不是恒等于全库条目数**——否则「增量」只是换了个名字。

