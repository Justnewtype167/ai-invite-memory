# TASK-08 · PCS：换模型之后还像不像同一个人（M6）

> `kid` 量的是**内容身份**（是不是同一份字节）。
> PCS 量的是**行为身份**（表现得像不像同一个人）。
> 两者必须同时成立，「可迁移」才不是一句空话。

写前已过 `docs/SPEC-CHECKLIST.md` 十问。

---

## 0. 为什么必须另有一个指标

```
kid  ：同一份证据 → 同一个 kid          （M4 已证）
换模型：提案不同 → kid 必然不同          （M5 已证）
```

所以 `kid` **永远答不了**那个用户真正关心的问题：

> 我换了模型，它还是不是原来那个人？

PCS 就是为这个问题存在的。

---

## 1. 定义（三条，缺一不可）

```
探针集      P，|P| = 30，每条探针绑定一条自我规则 r_p
自我规则    R = self.md 中 Style / Conduct 的条目（模型提议、规则层接受）
模型回复    reply_m(p)

① 自洽率    C(m)  = 通过的探针数 / |P|
② 一致率    A(a,b) = 两个模型判定结果相同的探针数 / |P|
③ PCS(a,b) = A(a,b) × min(C(a), C(b))
```

### 1.1 为什么乘 `min(C)` 而不是只算一致率

```
情形：两个模型对全部探针都违反规则
只看 A   → A = 1.0，PCS = 1.0（看着「高度一致」）
但这是「一致的错」——两个都不像那个人
乘 min(C) → PCS = 1.0 × 0 = 0
```

**PCS 必须同时回答两件事：像不像，以及像不像「那个人」。**

### 1.2 三条硬约束

1. `PCS ∈ [0,1]`；当 `min(C) < 0.5` 时报告 `PCS = 0` 并标注 `insufficient_conformance`
2. 同一模型自比（a == b）必须得 `PCS = C(a)`，用于校准
3. 判定为 `unknown` 的探针**不计入分子分母**，且必须报告跳过数

---

## 2. 探针集

```
文件  jian_pcs/data/probes.jsonl
规模  30 条
字段  probe_id / rule / prompt / expect / violation
```

| 字段 | 说明 |
|---|---|
| `rule` | 该探针检查的自我规则原文（必须能在 self.md 里找到） |
| `prompt` | 给模型的用户输入 |
| `expect` | 结构化判定条件（见 §3），遵守时应通过 |
| `violation` | 一条**已知违反**的示例回复，判定器必须判它不通过 |

### 2.1 `violation` 是这份规格的核心防线

```
判定器先对 violation 跑一遍，必须 fail。
若判定器把已知违反判成 pass，该探针作废，且 T2 直接失败。
```

**理由**：一个永远返回 pass 的判定器会让 PCS 恒等于 1.0。
必须先证明它能判错，它判的「对」才有意义。

---

## 3. 判定器（确定性优先）

### 3.1 `expect` 的可用算子（全部可机器判定）

| 算子 | 含义 |
|---|---|
| `must_contain_any` | 回复必须含列表之一 |
| `must_not_contain_any` | 回复不得含列表之一（如形容词堆砌表） |
| `max_chars` | 回复长度上限 |
| `max_questions` | 问号数量上限 |
| `must_ask_before` | 出现 A 之前必须先出现 B |
| `max_sentences` | 句数上限 |

全部确定性、零模型。这是 PCS 可复现的基础。

### 3.2 模型判定（可选，不作为主口径）

```
若探针带 judge_prompt，可选用外部判定器，但：
  · 必须 2-of-3 采样一致才采纳
  · 必须分开报告「确定性判定」与「模型判定」两个数字，不许合并
```

---

## 4. 架构（核心零网络）

```
jian_pcs/                    纯计算：读探针、读回复、算分（零依赖零网络）
  probes.py  judge.py  score.py  report.py  cli.py

tools/responder_ollama.py    外部：把探针发给模型，落成 JSONL（网络只在这里）
```

回复文件格式（一行一条）：

```
{"probe_id":"p01","model":"qwen3.5:9b","text":"…","temp_milli":0,"seed":42}
```

---

## 5. 指标报告

```
python -m jian_pcs.cli pcs --a a.jsonl --b b.jsonl

探针        30   跳过 0
C(a)        0.87
C(b)        0.83
A(a,b)      0.90
PCS         0.75        ← 0.90 × min(0.87, 0.83)

并附按 rule 分组的明细：哪条规则最容易丢
```

**必须同时打印 `C(a)`、`C(b)`、`A`、`PCS` 四个数。** 只报 PCS 无法定位问题。

---

## 6. 验收（六个，全绿 0 skipped）

| # | 测试 | 断言 |
|---|---|---|
| T1 | `test_pcs_probes` | 30 条探针：每条 `rule` 能在示例 self.md 中找到；`expect` 算子合法；`violation` 非空 |
| T2 | `test_pcs_judge` | **每条探针的 `violation` 必须判 fail**；合法样例判 pass；空回复判 `unknown` |
| T3 | `test_pcs_score` | 三组脚本化回复：全遵守 → `PCS = C`；一方全违反 → `A = 1` 但 `PCS = 0`；一半遵守 → 数值等于手算值 |
| T4 | `test_pcs_edges` | `a == b` 时 `PCS == C(a)`；跳过计数正确；`min(C) < 0.5` 时 `PCS = 0` 且带标注 |
| T5 | `test_pcs_determinism` | 同一份回复文件跑两次，报告**逐字节一致** |
| T6 | `test_all_regression` | 现有 **180 个测试仍全绿**；四个已封版包零 diff |

---

## 7. 禁止

1. 不许让 `jian_pcs/` 导入 `urllib` / `socket` / `requests`
2. 不许测试里调真模型
3. 不许只报 PCS 不报 C 和 A
4. 不许改 `jian/`、`jian_cn/`、`jian_recall/`、`jian_kernel/`
5. 不许把 `unknown` 计入通过

---

## 8. 完成定义

```
python -m unittest discover -s tests -v      # 全绿、0 skipped
python -m jian_pcs.cli pcs --a a.jsonl --b b.jsonl
```

并附一段**真机记录**：

```
同一 store 的自我规则，同一批 30 条探针，两组回复：
  a 与 b 同参数         → PCS 应等于 C(a)（校准线）
  a 与 b 不同提示/参数   → 报出 C(a)、C(b)、A、PCS 四个数
```

**这一条用来证明：PCS 不是恒为 1 的装饰品。**

