# M12 终验：增量编译与对账

> 结论：**增量与全量逐字节相同；快照删掉后退化为全量、kid 不变；篡改与漂移都会被拒。**
> 全量 `270` 个测试全绿、`0 skipped`；`compile_kernel` 一行未改。

本轮新增 `jian_kernel/snapshot.py`（快照结构与自证摘要）与
`jian_kernel/incremental.py`（续算与对账）。`jian_kernel/` 的三处既有改动
（`errors.py`、`__init__.py`、`cli.py`）已在
`tests/test_all_regression.py` 的 `ALLOWED_CHANGES` 与
`tests/test_env_v2.py` 的 `M12_EDITS` 中声明。

## 1. 验收结果

| # | 测试 | 结果 |
|---|---|---|
| R1 | `test_incremental_equals_full` | 20 组随机序列、共 `223` 次增量调用，每次 `kid` 与四个产物都与全量逐字节相同 |
| R2 | `test_policy_change_forces_full` | 改 `policy.now` → 快照作废、回全量：`early=f8ac3c448888` `late=f2a3bc29d696`，不报错、不静默沿用 |
| R3 | `test_snapshot_discardable` | 删除 `store/kernel/` 后再增量：退化为全量，`kid=0d3cdd4f6cb3` 不变 |
| R4 | `test_snapshot_tamper` | 改 `kid` / 改 `digest` / 删字段 → `E_KN_SNAPSHOT`；`head` 指向不存在事件 → `E_KN_STALE` |
| R5 | `test_work_is_delta_sized` | 事件计数而非墙钟：`full=20`，之后每次增量 `delta=1,1,1,1`，无新增时 `idle=0` |
| R6 | `test_reconcile_detects_drift` | 人为写入全零 `kid`：`reconcile` 与 CLI 均报 `E_KN_DRIFT`，退出码非零 |
| R7 | `test_all_regression` | `178` 个冻结测试全绿；`jian/`、`jian_cn/`、`jian_recall/`、`jian_pcs/`、`jian_projection/` 零 diff；`jian_kernel/` 改动已声明 |

R5 的关键断言是「处理了几条」，不是「快了多少」：增量路径的计数器等于
`id > head` 的事件条数，与机器负载无关（C14）。

## 2. 手工记录（同一段 200 条证据）

事件 200 条（turn / directive / feedback / milestone 混合，跨 5 段 30 天以上的空档，
用来触发衰减分支），`Policy(now=2026-10-29T10:00:00+08:00)`。

```
full      kid=e21dff239df8c1ab7868b6acb5480d9bea45d3de0aefc9b6fb0f50f8d0959a31 events=200 head=ev_000200
incremental(first, no snapshot) kid=e21dff239df8c1ab7868b6acb5480d9bea45d3de0aefc9b6fb0f50f8d0959a31 events=[200] same=True bytes=True
reconcile status=ok kid=e21dff239df8c1ab7868b6acb5480d9bea45d3de0aefc9b6fb0f50f8d0959a31 events=200 head=ev_000200
after snapshot delete kid=e21dff239df8c1ab7868b6acb5480d9bea45d3de0aefc9b6fb0f50f8d0959a31 events=[200] same=True
after +5  incremental kid=dfab0f5b6d51cc8a0867a07790c42f9fe6b7e8eee9ca2b25c29a1d620c5823f9 events=[5] full kid=dfab0f5b6d51cc8a0867a07790c42f9fe6b7e8eee9ca2b25c29a1d620c5823f9 same=True bytes=True
reconcile(after +5) status=ok kid=dfab0f5b6d51cc8a0867a07790c42f9fe6b7e8eee9ca2b25c29a1d620c5823f9 head=ev_000205 events=205
```

| 场景 | kid | 处理事件数 |
|---|---|---|
| 全量 | `e21dff239df8…` | 200 |
| 增量（首次，无快照） | `e21dff239df8…` | **200** |
| 增量（追加 5 条后，有快照） | `dfab0f5b6d51…` | **5** |
| 删快照后再增量 | `e21dff239df8…` | **200** |
| 对账 | `status=ok`（两次） | 200 / 205 |

首次增量的处理事件数是 **200 而不是 0**：没有快照时它必须老老实实全量重算，
不是拿缓存糊弄。删掉快照后再次回到 200，也证明快照只是加速器，不是真相。
追加 5 条后它只处理 5 条，且与全量逐字节相同（`bytes=True`
比较的是 `META.json`、`canon.md`、`self.md`、`state.json`、`graph.json`）。

## 3. 为什么能等价

| 机制 | 做法 |
|---|---|
| 续算上下文 | 快照除规格要求的八个字段外，另存一个派生 `context` 块（已接受风格、配额、已见日期、月数、模型、拒绝数），`digest` 覆盖全部字段 |
| 时钟 | `policy_digest` 按**声明值**摘要，`now=None` 不随证据增长失效；有效时钟每次由证据尾部重算 |
| promise 取消 | delta 内任一「已完成 / 已办 / 做到了」会取消快照里的全部 promise，delta 内新 promise 只被更后事件取消，完全镜像全量 |
| state | 从快照已 clamp 的 state + 最后一条内容的 stamp 续算 gap / 新日期 / feedback / clamp |
| graph | 快照边锚 + delta 边锚，按 `(event_id, term)` 去重排序 |
| 对账 | 全量重算，依次比 `kid`、`canon.md`、`self.md`、`state.json`、`graph.json`，首个不一致即 `E_KN_DRIFT` |

## 4. 一句话

快照落盘 `store/kernel/snapshot.json`，删它无事发生；
`reconcile` 是这一轮的一等公民——它证明增量没有破坏确定性，而不是假设它没有。

---

# 独立复核（由验收方复跑，不使用实现的测试）

| 性质 | 我的验证 | 结果 |
|---|---|---|
| **A1 等价性** | 同一 store 逐条追加 6 种事件（turn/directive/feedback/milestone），每追加一条就增量一次，与全量比对 `kid` + `canon_md` + `self_md` + `state` | **6/6 全部一致** |
| **R5 工作量** | 计数器序列 | `[1,1,1,1,1,1]` —— 每次只处理 1 条，与历史长度无关 |
| **A2 可丢弃** | 删除 `store/kernel/` 后再增量 | 退化为全量（处理 6 条），**kid 不变** |
| **A3 可检测** | 手改快照 `kid` | `E_KN_SNAPSHOT: 快照 digest 不符，已被手改` |
| **对账** | `reconcile()` | `pass` |

快照实际字段：

```
canon_md / context / digest / format / graph / head / kid / policy_digest / self_md / state
```

## 一处我自己测错了，记录在案

我第一次把 `head` 改成 `ev_999999` 时，期望 `E_KN_STALE`，实际得到 `E_KN_SNAPSHOT`——
因为我改了字段却没重算 `digest`，**摘要校验先于语义校验触发**。

这不是缺陷，是防护顺序正确：**先验完整性，再验语义**。
实现方的 `test_snapshot_tamper` 用四种注入方式覆盖了这两种错误码（含重算 digest 的过期 head）。

## 结论

```
R1-R7：通过
独立复核：通过（A1 / A2 / A3 / R5 / 对账）
测试：270 全绿，冻结套件 178/0/0/0
compile_kernel：一行未改
```

打 tag `v0.15-m12`。

## 下一步

M13 动作闸门：把「不可腐蚀」从「拒绝改自己」扩展到「拒绝做违反自己的事」。
