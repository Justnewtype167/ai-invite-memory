# TASK-12 · 探针扩到 60 条与 R3 精确语义（M8.3）

> 两个目的：**收窄 CI**（30 → 60 条探针），**落实 R3 修订**（恰好一问）。

---

## 1. 新增数据（已由规格方写好，实现方不要改内容）

```
jian_pcs/data/probes_more.jsonl    30 条（R1–R6 各 5 条），已自检 120/120 断言通过
jian_pcs/data/probes.jsonl         保持 30 条不动
合计                               60 条
```

## 2. 代码改动

### 2.1 规则文件新增参数

```
rules_v2.json 的 R3 已改为：
  args: {sentences: 2, questions: 1, questions_exact: true}
  human: 按 。！？ 切分后不超过 2 句，且「？」恰好 1 个

判分器要求：
  questions_exact=true  → 「？」数必须恰好等于 questions
  questions_exact 缺省   → 沿用「不超过」语义（向后兼容，M6/M7 的旧探针不受影响）
```

### 2.2 探针加载

```
load_probes()   仍只读 probes.jsonl（保持既有测试不变）
load_more_probes()  新增，读 probes_more.jsonl
load_all_probes()   改为 30 + 30 = 60
PROBE_COUNT         改为从文件推导（不再硬编码 30）
```

**注意**：M6/M7 的测试断言 `len(load_probes()) == 30`，这个必须保持；
扩量只影响 `load_all_probes()`。

---

## 3. 验收（五个）

| # | 测试 | 断言 |
|---|---|---|
| X1 | `test_probes_more_schema` | 30 条新探针字段齐、id 不与旧集重复、rule ∈ R1–R6、每条 5 个 |
| X2 | `test_probes_more_judge` | 120 条断言全部正确（accept 全过、violation 全拒） |
| X3 | `test_r3_exact` | `questions_exact=true` 时：0 问 fail、1 问 pass、2 问 fail；缺省参数时 0 问 pass（向后兼容） |
| X4 | `test_all_probes_60` | `load_all_probes()` 返回 60 条，无重复 id |
| X5 | `test_all_regression` | 现有 **235 个测试仍全绿**；四个已封版包零 diff |

---

## 4. 完成定义

```
python -m unittest discover -s tests -v      # 全绿
python -m jian_pcs.cli pcs --a … --b …       # 用 60 条重算
```

并回填到 `docs/RESULTS-cross-model-v2.md`：

```
60 条探针下的 C(qwen) / C(glm) / A / PCS 与 95% CI
```

**CI 应当明显收窄**；若没有收窄，说明新探针与旧探针难度分布雷同，需要检查。

