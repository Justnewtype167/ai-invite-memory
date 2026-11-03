# M4 验收报告（核心断言成立，一处门控语义要改）

> 对象：工作区 8 个改动文件（`aiinvite.kernel/` + 测试）
> 结论：**「同一份证据 ⇒ 同一个人格，一个字节都不差」这条**跨进程**验证通过。
> 余一处：手改内核后 `record` 会静默覆盖，篡改痕迹消失。**

---

## 1. 我独立复现的结果

| 项 | 断言 | 实测 |
|---|---|---|
| 测试总数 | —— | **129 tests, OK, 0 skipped** |
| 三个已封版包 | 零 diff | `jian/`、`aiinvite.cn/`、`aiinvite.recall/` 均未改 |
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


---

# M4 终验（通过，已封版 v0.4-m4）

> tag `v0.4-m4`，工作区干净，**131 测试全绿**，干净克隆复验通过。

## 1. 篡改留痕：9 项全部符合预期

| # | 场景 | 实测 |
|---|---|---|
| T1 | 手改 canon 后 record（无 force） | **拒绝**，`E_KN_STALE` |
| T2 | 拒绝后 kernel 目录 | **字节未变** |
| T3 | 拒绝后 HISTORY 长度 | 仍是 1（没写脏数据） |
| T4 | `force=True` | 成功，v2 |
| T5 | HISTORY 追加审计行 | `{"at":…,"event":"tamper_healed","found":<被改后的kid>,"kid":<治愈后>,"version":2,"head":…}` |
| T6 | 治愈后 canon | forged 行已消失 |
| T7 | 治愈后正常 record | 通过（同 kid 不重复追加版本） |
| T8 | 跨进程 determinism | 仍一致 |

审计行里带了 `found`（盘上被改成的 kid）与 `kid`（治愈后），
**能回答「什么时候、被改成什么、被谁覆盖回什么」**——这才是审计，不是日志。

## 2. 干净克隆复验

```
tag         v0.4-m4
M1 verify   OK head=61a5d726 state=sealed
M2 timex    两年前 → 2024-10-29
M4 CLI      compile / record / history / verify / diff
tests       Ran 131 tests, OK
```

## 3. 四个里程碑盘点

| 版本 | 模块 | 测试 | 关键断言 |
|---|---|---|---|
| v0.1-m1 | `jian/` | 31 | 改 1 字节必被发现 |
| v0.2-m2 | `aiinvite.cn/` | 44 | 组合优于清单（留出集 14/14） |
| v0.3-m3 | `aiinvite.recall/` | 27 | 4k 预算不损保真（20/20） |
| v0.4-m4 | `aiinvite.kernel/` | 29 | **跨进程 kid 一致** |
| 合计 | 4 包 | **131** | 零依赖、零模型 |

## 4. M4 真正证明了什么

```
同一份证据 + 同一策略 + 同一编译器版本
  → 同进程 100 次：kid 一致
  → 跨进程（不同 PYTHONHASHSEED）：kid 一致
  → 删掉 kernel/ 重建：kid 一致
  → restore(历史版本) 重算：kid 等于历史值
```

**人格第一次成为一个可以从证据验算出来的函数输出，而不是一份谁也不知道改没改过的状态。**

这是 P2 论文的核心实验，也是后面「换模型 / 换设备 / 继承」三件事的共同地基。

