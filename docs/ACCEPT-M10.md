# M10 验收（机制通过；两处必须修，一处必须记账）

> 254 测试全绿，上层改动恰好 3 行，v1 兼容保持。
> **但编译器读的是 `summary`（截断到 200 字），与我自己的规格 §2 冲突。**

---

## 1. 成立的部分

| 项 | 结果 |
|---|---|
| 测试 | **254 全绿**（246 + 8） |
| 冻结套件 | `S6 frozen tests=178 failures=0 errors=0 skipped=0` |
| 信封 v2 | 五种 modality 各写一条 → seal → verify 通过 |
| 禁用字段 | v2 带 `text` 报 `E_SCHEMA` |
| blob store | 内容寻址、重复只写一份、篡改报 `E_BLOB_MISMATCH`、缺失报 `E_BLOB_MISSING` |
| 往返 | export → import → export 逐字节一致，blob 随包往返 |
| v1 兼容 | M1 的 31 个测试仍全绿；v1 胶囊仍可 verify |
| 上层改动 | **恰好 3 个文件各 1 行**，其余 sha256 与基线一致 |
| 访问器 | `event_text`：v1→text，v2→summary，缺省→`""` |

## 2. 必须修（P0）：编译器读了截断字段

```
规格 §2 写的：summary 「仅供检索与预算装配，不参与人格规则判定」
实际实现   ：compiler.py:161 → event_text(data) → v2 取 summary（≤200 字）
```

**这是我在 §5.1 加访问器时引入的自相矛盾**：访问器为检索而生，却被编译器复用。

### 实测影响

| 场景 | v1 kid | v2 kid | 结论 |
|---|---|---|---|
| 288 字普通消息 | 相同 | 相同 | 无影响 |
| 「已完成」出现在第 225 字 | 相同 | 相同 | 无影响（当前无规则吃满文） |

**当前不可观测，但风险是真实的**：任何将来依赖全文的规则，在 v1/v2 两种装载下会给出不同人格。

### 修法

```
新增 jian/capsule.event_full_text(store, data)  → 文本模态读 blob，其余模态回退 summary
compiler.py 改用它（仍然只改一行）
event_text 保持「检索用」语义不变
```

## 3. 必须记账（P1）：冻结闸门被打开了

`tests/test_all_regression.py` 的改动做了两件事：

```
① 把 jian/ 整个从 FROZEN_DIGESTS 里删掉（证据层从此不受摘要保护）
② 就地更新了 jian_kernel/compiler.py 与 proposer.py 的哈希
```

**单看这一轮是合理的**（证据层本来就要改），但机制上变成了：
任何里程碑想看开冻结，改一下这个字典即可，**没有第二道闸**。

### 修法（下一轮或本轮补）

```
FROZEN_DIGESTS 保持不动；新增 ALLOWED_CHANGES = {文件: 原因}，按里程碑声明
测试断言：与上一版有差异的文件必须出现在 ALLOWED_CHANGES 里，否则失败
这样「开冻结」从「改字典」变成「在规格里写一行理由」
```

## 4. 代码质量（P2）：`__import__` 内联

```python
text = __import__("jian.event", fromlist=("event_text",)).event_text(data)
```

可用，但：可读性差、隐藏了 `jian_recall → jian` 的依赖、让 N5 的「逐行可审计」变成逐行难读。

**建议**：在模块顶层 `from jian.event import event_text`（依赖方向是向下的，不构成循环），
仍然只改一行 import + 一行调用，但可读。

## 5. 结论

```
机制：通过
验收：不通过 —— P0 必须修（编译器读截断字段）后再签
记账：P1 冻结闸门需要加棘轮；P2 代码可读性
```
