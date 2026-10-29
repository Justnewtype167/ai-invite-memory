# M4 验收报告（核心断言成立，一处门控语义要改）

> 对象：工作区 8 个改动文件（`jian_kernel/` + 测试）
> 结论：**「同一份证据 ⇒ 同一个人格，一个字节都不差」这条**跨进程**验证通过。
> 余一处：手改内核后 `record` 会静默覆盖，篡改痕迹消失。**

---

## 1. 我独立复现的结果

| 项 | 断言 | 实测 |
|---|---|---|
| 测试总数 | —— | **129 tests, OK, 0 skipped** |
| 三个已封版包 | 零 diff | `jian/`、`jian_cn/`、`jian_recall/` 均未改 |
| K1 同进程 100 次编译 | 字节一致 | kid 相同，`self_md/canon_md/state` 全同 |
| **K1 跨进程**（不同 PYTHONHASHSEED） | kid 相同 | **相同 `3a588adc…`** |
| K1 generation | 恒 0 | 0 |
| K1 state 全整数 | 无 float | `{intimacy:530, stability:500, trust:520}` |
| K1 全量溯源 | 每条带 evidence 且存在 | 0 条缺失 |
| K2 删 kernel 重建 | kid 不变 | 相同 |
| K2 restore(1) | kid == 历史值 | 相同 |
| K2 verify | 通过 | `VerifyReport(kid=…, version=1)` |
| K3 G2 变更率 | 超限报错 | 50 条新增 → `E_KN_GATE_DELTA` |
| K3 G4 状态跳变 | 超限报错 | 20 次 correction → `E_KN_GATE_STATE` |
| K3 手改 canon 后 verify | 必须发现 | `E_KN_STALE` |
| 正常增量 | 通过 | v2，delta=(0,0,0) |

## 2. 最有分量的一条：跨进程一致性

同一进程内编译 100 次一致，只能证明「没有随机」；
**跨进程**一致才能证明「没有依赖任何进程内状态」（字典哈希序、对象 id、缓存）。

```
PYTHONHASHSEED=0       kid=3a588adc64cc4ca3…
PYTHONHASHSEED=12345   kid=3a588adc64cc4ca3…
```

这条过了，`kid` 才真的能当身份用。

## 3. 要改的一处：`record` 对「盘上被手改」静默覆盖

实测：

```
手改 kernel/canon.md（追加 forged 行）
verify  → E_KN_STALE          ✅ 能发现
record  → 静默重建，v2，无任何提示  ❌ 篡改痕迹消失
```

规格 K3 原本写的是「手改 canon 后 record → E_KN_GATE_CANON」，实现没这么做。

**谁对？实现的行为更合理，但缺一步留痕。**

我的判断：内核是派生物，手改本来无意义，所以 `record` **不该**报 canon 门控错；
但它也不该静默覆盖——那样运维永远不知道有人在动内核。

### 建议改法

```
record 前先比对「盘上 kid」与「历史最后一版 kid」
  一致   → 正常记录
  不一致 → 拒绝，报 E_KN_STALE，提示「内核被手改过，确认请加 --force」
  --force → 覆盖，但 HISTORY 追加一行 {"event":"tamper_healed", ...} 留痕
```

这与本项目的主张一致：**不阻止人做事，但要让每件事留下证据。**

## 4. 待办

| 级别 | 项 |
|---|---|
| 必修 | 提交 8 个文件并打 tag `v0.4-m4` |
| 必修 | `record` 加「盘上/历史 kid 比对」：不一致 → `E_KN_STALE`，`--force` 才覆盖并留痕 |
| 顺带 | 规格 K3 的表述改成「verify 必须发现手改」，与实现对齐 |

