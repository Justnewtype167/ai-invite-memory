# M16 · P0 阶段验收（Task 1 + Task 2）

> 范围：`refusal` 编译崩溃（P0）+ 事件层扩展 + 人格事件跳过清单。
> **不含** `jian_persona`（Task 3–8 未开始）。
> 结论：**P0 修复成立，可继续。有两项未完成需在 M16 收尾前解决。**

---

## 1. 我独立复核的五项

| 检查 | 我的做法 | 结果 |
|---|---|---|
| **refusal 不再编不过** | 写一条 refusal 后编译 | ✅ 正常返回，`kid` 不变，`head` 停在 `ev_000002` |
| **人格事件不扰动 kid** | 六种形态各 100 条（200 条 trait/trait_off 实测） | ✅ `kid` 不变；`kernel.self_md` **逐字节相同** |
| **proposal 不改 origin/models** | 写一条 `proposal(self.trait)` | ✅ `origin` 仍 `rule_only`，`models` 仍空，`kid` 不变 |
| **增量与全量一致** | 追加人格事件后跑增量 + 对账 | ✅ `incremental.kid == full.kid`；`reconcile = ok` |
| **测试树** | 全量 | ✅ **317 全绿**（315 + 2） |

**第二项最关键**：`kernel.self_md` 逐字节相同，说明跳过清单真的把它们挡在了 kid 之外，
不是“看起来一样”。

## 2. 两项未完成

### ① `record_kernel` 遇到“只有人格事件变化”的行为未定

实测：

```
第一次 record   → version=1, kid=0fd78222…
只加一条 trait  → 内核 kid 不变
再 record       → **version 仍是 1，HISTORY 仍 1 条**（不产生新版本）
```

**这是一个决定，但没有被写进任何文档，也没有测试。**

我的判断：可以接受“不产生新版本”（kid 就是人格，人格没变就不该有新版本），
**但必须补两件事**：

```
① 一条测试把这个行为钉死（不然下次有人改了就没人知道）
② `ACCEPT-M16` 写明一句：特质的增删只留痕在证据链，不进版本账本
```

**否则宪章 A2「性格改动可追溯」在版本账本这一层是断的。**

### ② `jian_persona` 尚未创建

```
当前：jian_persona/ 不存在
已完成：Task 1（事件层）、Task 2（P0 + 跳过清单）
待做：Task 3–8（特质、风格卡、用户卡、四组对照、验收）
```

这是计划内的分批，不是缺陷。

## 3. 一处值得记下的实现选择

`PERSONA_TARGETS` / `PERSONA_DIRECTIVE_KINDS` 定义在 **`jian_kernel/kernel.py`**，
由 L2 的 `jian_persona` 引用——**依赖方向是向下**（L2 → L1），没有倒挂。

这个选择是对的：跳过清单属于「什么算内核事件」的定义，本来就该在 L1。

## 4. 结论

```
P0：已修复，我实测确认
Task 1/2：通过
继续 Task 3–8，但 ① 必须在 M16 收尾前补上
```
