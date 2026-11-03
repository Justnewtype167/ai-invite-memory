# TASK-05 · 补最后三公里（M4.1）

> 端到端演示暴露的三件事，搁着不管，接模型之后会被放大成「人格漂移」的假象。
> 所以插一个短里程碑，只做三件，**不改架构**。

## 0. 三件事

| # | 问题 | 影响 |
|---|---|---|
| 1 | `directive / milestone / feedback` 写不进证据层（seal 报 `E_SCHEMA`） | 内核缺 directive 与反馈，canon 只剩承诺 |
| 2 | 装配只按 `event_id` 去重，同一句话出现 3 次 | 白吃预算，上下文变噪 |
| 3 | 单字命中即入选（问天气也回一堆「今天」） | 检索噪声，挤掉金句 |

---

## 1. 冻结例外（范围写死，不得扩大）

`jian/`、`aiinvite.cn/`、`aiinvite.recall/` 都已封版。M4.1 **只允许**改这些：

| 文件 | 允许改什么 |
|---|---|
| `jian/event.py` | 事件类型与字段校验、`new_event` 增加 type/kind |
| `jian/capsule.py` | `append_event` 增加 type/kind 参数（旧签名必须仍可用） |
| `jian/cli.py` | `append` 增加 `--type` / `--kind` |
| `aiinvite.recall/retrieve.py` | 打分加查询覆盖度 |
| `aiinvite.recall/assemble.py` | 文本级去重 |

**其它任何文件不许动。** `aiinvite.cn/` 与 `aiinvite.kernel/` 一行都不许改。

---

## 2. 事件模型扩展

### 2.1 五种类型与字段

| type | 必填 | 可选 | 禁止 |
|---|---|---|---|
| `turn` | `role`(user/assistant), `text` | —— | `kind` |
| `feedback` | `kind`(praise/correction), `text` | `target`(event_id) | `role` |
| `directive` | `kind`(lock/unlock/rule), `text` | —— | `role` |
| `milestone` | `text` | —— | `role`, `kind` |
| `checkpoint` | `text`(kid) | —— | `role` |

所有类型共有：`v=1, id, ep, t, type, prev, hash`。

**校验是严格的**：出现上表「禁止」的字段，或缺少「必填」字段 ⇒ `E_SCHEMA`。
这条比宽容更重要——M1 的严格校验是篡改检测的一部分。

### 2.2 链与哈希不变

`hash_i = sha256(prev + \n + canonical(event 去掉 hash))`，**与 M1 完全一致**。
新增字段参与 canonical，因此旧事件不受影响。

### 2.3 向后兼容（硬要求）

```
旧胶囊（只有 turn）必须仍能 verify / import / export
M1 的 31 个测试必须仍全绿
新写的胶囊给旧版本读：应报 E_SCHEMA，不许崩
```

---

## 3. 公开写入 API

```python
# 旧签名，保持不变
append_event(store, role: str, text: str, t: str | None = None) -> Event

# 新签名（关键字调用），与旧签名并存
append_event(store, *, type: str, text: str, kind: str | None = None,
             role: str | None = None, target: str | None = None,
             t: str | None = None) -> Event
```

CLI：

```
python -m aiinvite.cli append <dir> --type directive --kind lock --text "称呼：叫我小满"
python -m aiinvite.cli append <dir> --type feedback --kind correction --text "不对"
```

---

## 4. 去重语义（此前规格里「去重」二字没有定义）

```
去重键   = sha256(canonical({"t": normalize(text)}))
优先级   = trigger > retrieved > recent
保留     = 优先级最高、分数最高的那一条
合并信息 = item.merged = 被合并掉的 event_id 列表（升序）
预算     = 只计一次
```

`normalize` 用 `aiinvite.cn.normalize`（繁简/全半角/空白一致），这样「臺灣」与「台湾」算同一句。

**边界**：

1. 同一 event 出现在两个槽位 → 按优先级保留一次
2. 文本相同但 event 不同 → 合并为一条，`merged` 记录其余 id
3. 去重后仍须满足槽位上限与总预算
4. 去重不得改变输出顺序（trigger → retrieved 分数降序 → recent 时间降序）

---

## 5. 检索：不是缺 IDF，是缺覆盖度

复盘：FTS5 的 bm25 **本身含 IDF**。演示里「今天天气怎么样」回一堆「今天…」，
不是 IDF 没起作用，而是**只要命中一个二元组就够进候选**。

所以加的是**查询覆盖度**，不是 IDF：

```
q_bigrams = 查询的二元组集合（去重）
hit_terms = 该事件文本中出现的 q_bigrams
coverage  = |hit_terms| / |q_bigrams|

final = bm25_normalized * (0.4 + 0.6 * coverage) * time_decay
```

- `bm25_normalized`：把本轮候选的 bm25 分数线性归一到 0–1（全相同则取 1）
- `coverage` 用整数运算：`(400 + 600 * hit * 1000 // total) // 1000`，避免 float
- 单一高频词命中 → coverage 低 → 排序自然下沉

---

## 6. 验收（六个，全绿 0 skipped）

| # | 测试 | 断言 |
|---|---|---|
| S1 | `test_ev_types` | 五种类型各写一条 → seal → verify → export/import 后**逐字节一致**；非法字段组合 → `E_SCHEMA`（每个类型至少 2 个反例） |
| S2 | `test_ev_compat` | M1 的 31 个测试全绿；`docs/demo/memory.aiem` 仍能 verify；只有 turn 的旧目录仍能 seal |
| S3 | `test_rc_dedupe` | 5 条同文本不同事件 → 装配后**只出现 1 条**，`merged` 含另 4 个 id；跨槽同文本只保留优先级高的；去重后仍满足槽位上限 |
| S4 | `test_rc_coverage` | 1100 条语料（复用 M3 质量集），20 个问题各自金句必须进 **top-5**，命中率 **≥ 0.90**；且「今天天气怎么样」这类单字命中不得挤掉金句 |
| S5 | `test_rc_determinism` | 同查询装配两次**字节一致**（去重+覆盖度引入后仍确定） |
| S6 | `test_all_regression` | M1–M4 的 **131 个测试仍全绿** |

---

## 7. 禁止

1. 不许改 `aiinvite.cn/`、`aiinvite.kernel/` 任何一行
2. 不许改事件哈希算法或 canonical 规则
3. 不许为了 S4 去改 `qa_labels.json` 或扩充干扰池
4. 不许把去重做成「删掉后出现的重复」而不记录 `merged`
5. 不许引入停用词表（那会把「今天」这种有意义的词也删掉）

---

## 8. 完成定义

```
python -m unittest discover -s tests -v      # 全绿、0 skipped
python tools/demo_e2e.py                     # 第 9 段不再报 E_SCHEMA
```

演示脚本第 9 段应变成：

```
directive / milestone / feedback 均写入成功，seal → OK
```

