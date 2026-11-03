# TASK-16 · 增量编译与对账（M12）

> 目标：**连续流下不再每次全量重算，但结果必须与全量逐字节相同。**
> 对账（reconcile）不是优化，是「增量没有破坏确定性」的证明。

写前已过 `docs/SPEC-CHECKLIST.md` 十问；约束 C14 适用（绝对时延不进单测门禁）。

---

## 0. 一句话与边界

```
做    用上一次的派生快照 + 新增事件，得到与全量编译相同的 kid
不做  不做流式写入、不做并发、不改 evidence 层任何格式
```

**对账是本轮的一等公民**：没有对账的增量编译，只是「相信它算对了」。

---

## 1. 三条必须同时成立的性质

```
A1  等价性   增量结果 == 全量结果（kid、canon_md、self_md、state、graph 全部逐字节相同）
A2  可丢弃   删掉快照 → 退化为全量 → 结果不变（说明快照不是真相）
A3  可检测   快照被篡改或过期 → 报错，绝不静默使用
```

**A2 是 C6c「索引可丢弃」在内核层的重述**：快照只能加速，不能成为事实来源。

---

## 2. 快照（snapshot）

```
store/kernel/snapshot.json   派生物，可随时删除
```

```json
{
  "format": 1,
  "head": "ev_000123",            ← 已消化的最后一条事件 id
  "kid": "...",                   ← 该前缀的 kid
  "policy_digest": "sha256:...",  ← 编译策略的摘要（含 now）
  "state": {...}, "graph": {...}, "self_md": "...", "canon_md": "..."
  "digest": "sha256:..."           ← 快照自身内容的摘要（防篡改）
}
```

| 规则 | 说明 |
|---|---|
| 快照必须自证 | `digest` 覆盖除自身外的全部字段；不符 → `E_KN_SNAPSHOT` |
| `policy_digest` 必须匹配 | `now` 或任何策略项不同 → 快照作废，回全量 |
| `head` 必须在证据中存在 | 不在（证据被截断）→ 快照作废 |
| 快照不含时间戳以外的环境信息 | 否则跨机器不可复现 |

---

## 3. 两个入口

```python
compile_kernel(store, policy)                    # 全量，行为不变
compile_kernel_incremental(store, policy)        # 有快照则续算，无则全量
reconcile(store, policy)                         # 全量重算并与快照比对
```

| 函数 | 语义 |
|---|---|
| `compile_kernel` | 一行不改，作为「真相」的唯一定义 |
| `compile_kernel_incremental` | 读快照 → 应用 `id > head` 的事件 → 新 kid → 写回快照 |
| `reconcile` | 强制全量编译，与快照的 kid / 四个产物逐字节比对，不一致报 `E_KN_DRIFT` |

**CLI**：

```
aiinvite kernel compile --incremental       # 增量（无快照自动全量）
aiinvite kernel reconcile                   # 对账，不一致退出码非零
```

---

## 4. 错误码（新增两个）

| 码 | 含义 |
|---|---|
| `E_KN_SNAPSHOT` | 快照结构非法、`digest` 不符、字段缺失 |
| `E_KN_DRIFT` | 增量结果与全量不一致（对账失败） |

`E_KN_STALE` 复用：快照 head 与证据不匹配（证据被截断/回滚）。

---

## 5. 验收（七个）

| # | 测试 | 断言 |
|---|---|---|
| R1 | `test_incremental_equals_full` | **随机 20 组事件序列**（含 turn / directive / feedback / milestone / proposal），每加一条增量一次；每次 `kid` 与四个产物都与全量逐字节相同 |
| R2 | `test_policy_change_forces_full` | 改变 `policy.now` → 快照作废 → 结果等于全量；不报错、不静默沿用 |
| R3 | `test_snapshot_discardable` | 删除 `store/kernel/` 后增量退化为全量 → kid 不变 |
| R4 | `test_snapshot_tamper` | 改快照任一字段 / 改 `digest` → `E_KN_SNAPSHOT`；`head` 指向不存在事件 → `E_KN_STALE` |
| R5 | `test_work_is_delta_sized` | **工作量按事件条数计，不按秒计**：增量处理的事件数 == 新增事件数（用计数器断言，不用墙钟） |
| R6 | `test_reconcile_detects_drift` | 人为写入错误 kid 的快照 → `reconcile` 报 `E_KN_DRIFT`，退出码非零 |
| R7 | `test_all_regression` | 现有 **264 个测试全绿**；`aiinvite/`、`aiinvite.cn/`、`aiinvite.recall/`、`aiinvite.pcs/`、`aiinvite.projection/` 零 diff；`aiinvite.kernel/` 改动必须在 `ALLOWED_CHANGES` 声明 |

**R5 是这一轮的方法论要求**：不要用「快了 N 倍」证明增量，用「处理了 N 条」证明。
墙钟受机器负载影响（C14 的教训），事件计数是确定的。

---

## 6. 禁止

1. 不许改 `compile_kernel` 的语义与签名（它是真相）
2. 不许让增量路径产生与全量不同的产物（哪怕只差一个空格）
3. 不许跳过快照的 `digest` 与 `policy_digest` 校验
4. 不许让快照进入胶囊导出（胶囊只装证据）
5. 不许在测试里用墙钟断言性能

---

## 7. 完成定义

```
python -m unittest discover -s tests -v      # 全绿、0 skipped
```

并提交一段手工记录（写进 `docs/ACCEPT-M12.md`）：

```
同一段证据（例如 200 条）：
  全量      kid = ?   处理事件数 = ?
  增量      kid = ?   处理事件数 = ?
  对账      pass / fail
  删快照后  kid = ?（必须与全量相同）
```

**增量处理的事件数必须是 200 而不是 0**——否则说明它在用缓存糊弄，而对账会立刻暴露。

