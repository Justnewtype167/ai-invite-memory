# TASK-04 · 人格内核与漂移门控（M4）

> 唯一权威规格。**写之前先过一遍 `docs/SPEC-CHECKLIST.md` 的十问。**

## 0. 范围与一个决定性取舍

原设计里内核编译是「LLM 提案、规则提交」。M4 **不接模型**，只做规则部分：

```
Proposer 协议          ← 接口留好，M5 填
NullProposer          ← M4 只用它：不产生任何提案
ReplayProposer        ← 读录制好的提案重放（M5 用，M4 先留桩）
```

**为什么这样切**：M4 要证明的第一件事是「**同证据 + 同策略 + 同编译器版本 ⇒ 字节一致**」。
只要有一个 LLM 在链路里，这句话就永远证不了。所以 M4 先把确定性做实，M5 再证明「LLM 参与下仍可重算」。

| 许做 | 不许做 |
|---|---|
| 新增 `aiinvite.kernel/` | 改 `jian/`、`aiinvite.cn/`、`aiinvite.recall/`（三者已封版） |
| 读 M1 证据、调用 M2 的称谓/时间 | 调用任何模型、网络、三方库 |
| 写 `store/kernel/`（派生物，可删可重建） | 写 `store/evidence/`（证据层只读） |

---

## 1. 目录

```
aiinvite.kernel/
  __init__.py  errors.py  compiler.py  kernel.py  gate.py
  proposer.py  history.py  cli.py
tests/test_kn_compile.py · test_kn_determinism.py · test_kn_gate.py
      test_kn_history.py · test_kn_sources.py · test_kn_regression.py
```

产出物（运行期，落在 store 下）：

```
store/kernel/
  self.md          ← 模板 + 统计填空（不是自由生成）
  canon.md         ← 每条带 evidence id
  state.json       ← 三个 0–1000 整数
  graph.json       ← 称谓边 + 时间锚点，每条带 evidence id
  META.json        ← kid / version / head / policy_hash / compiler_version
  HISTORY.jsonl    ← 每次 record 追加一行
```

---

## 2. 编译（纯函数）

```python
def compile_kernel(store: Path, policy: Policy | None = None, proposer=None) -> Kernel
```

四条硬性：

1. **只读证据**，绝不读 `kernel/` 自身（单向派生）
2. 不取当前时间；需要时间一律用 `policy.now` 或证据里的时间戳
3. 不使用随机数、不使用 float
4. 同一 `(evidence, policy, compiler_version)` ⇒ **输出字节一致**

### 2.1 各条目生成规则（全部可机器判定）

| 文件 | 来源规则 |
|---|---|
| `canon.md` | ①每个 `type=directive, kind=lock` 事件 → 一条；②`is_promise(text)` 命中且此后无「已完成/已办/做到了」抵消 → 一条承诺 |
| `self.md` | 固定模板 + 统计填空：相识天数、事件总数、活跃月份数、最高频称谓、最近 1 条 milestone |
| `state.json` | `trust / intimacy / stability` 三个整数：`feedback(correction)` −50 trust；`feedback(praise)` +20 trust；每自然日首次对话 +5 intimacy；每连续 30 天无事件 ×0.9；全部截断到 0–1000，按事件序累加 |
| `graph.json` | 用 `aiinvite.cn.kinship` 匹配文本中的称谓词建边；用 `aiinvite.cn.timex` 把相对时间落成绝对日期（锚点取该事件时间） |

**每一条**都必须带 `evidence: [event_id, ...]`，且 id 必须在证据中存在。

### 2.2 身份与版本

```
kid      = sha256(canonical(self, canon, state, graph))     ← 内容身份
version  = 该 kid 在 HISTORY.jsonl 中的序号（1 起）；compile 不算 version
META.generation = 0 恒成立
```

> `kid` 是身份，`version` 是账本序号。**不要把两者混用**——这是 M1 里 `created` 那个坑的同类问题。

---

## 3. 记录与门控（唯一允许改内核的入口）

```python
def record_kernel(
    store: Path, policy: Policy | None = None, force: bool = False
) -> RecordResult
```

流程：**盘上篡改检测** → 编译 → 与 `HISTORY` 中最近一版比对 → **四条门控** → 通过则追加历史，不通过则抛错且**不写任何文件**。

### 3.0 盘上篡改检测（与 G1 是两件事）

`record` 之前先把 `kernel/` 里的 `self.md`、`canon.md`、`state.json`、`graph.json`
重新哈希成 kid，与 `HISTORY` 最后一版的 kid 比对：

| 情况 | 行为 |
|---|---|
| 一致 | 正常记录 |
| 不一致（含文件缺失/不可解析） | 拒绝，`E_KN_STALE`，提示「内核被手改过，确认请加 --force」 |
| 不一致 + `--force` | 按证据重写内核，并在 `HISTORY.jsonl` 追加一行 `{"event":"tamper_healed", ...}` |

G1 管的是**证据驱动的变更**；3.0 管的是**盘上被外力改动**。两者不得合并：篡改检测失败时
G1 根本不会执行，`--force` 只覆盖盘上字节，不改变任何门控阈值。

### 3.1 四条门控

| # | 条件 | 不满足 |
|---|---|---|
| G1 | **canon 不可变**：条目集合与上版完全相同（除非本次证据里新增了 directive 事件） | `E_KN_GATE_CANON` |
| G2 | **变更率有界**：改动条目数 / max(1, 上版条目数) ≤ `policy.delta_limit`（默认 200/1000） | `E_KN_GATE_DELTA` |
| G3 | **全量溯源**：每条新增/修改条目 `evidence` 非空且事件存在 | `E_KN_UNSOURCED` |
| G4 | **状态不跳变**：任一 state 维度单次变化 ≤ 200 | `E_KN_GATE_STATE` |

### 3.2 三条行为约束

1. 门控失败时**目录必须保持原样**（先写临时目录，校验通过再原子替换）
2. `record` 是唯一写 `kernel/` 的函数；`compile` 只返回对象不落盘
3. `HISTORY.jsonl` 只追加，不修改、不删除

---

## 4. 历史与回滚

版本行：

```json
{"version":3,"kid":"ab12...","head":"ev_000412","at":"2026-10-29T08:00:00Z","delta":{"added":2,"changed":1,"removed":0}}
```

审计行（只在 `--force` 修复篡改时追加，不是版本，不参与 `history()`）：

```json
{"at":"...","event":"tamper_healed","found":"<盘上 kid>","head":"ev_000412","kid":"<修复后 kid>","version":3}
```

```python
def history(store) -> list[HistoryEntry]
def diff_versions(store, a: int, b: int) -> Diff      # 逐条 added/changed/removed
def restore(store, version: int) -> Kernel            # 只重建对象，不写盘
```

`restore` 不能靠历史快照——必须**重新编译**并断言 kid 等于历史里记录的 kid。
这正好是「可重算」的运行时证明。

---

## 5. 错误码

| 码 | 含义 |
|---|---|
| `E_KN_UNSOURCED` | 有条目无法溯源到证据 |
| `E_KN_GATE_CANON` | canon 被非法改动 |
| `E_KN_GATE_DELTA` | 变更率超限 |
| `E_KN_GATE_STATE` | 状态单次跳变超限 |
| `E_KN_NO_HISTORY` | 尚无历史版本 |
| `E_KN_STALE` | 内核落后于证据 head |
| `E_KN_IO` | 读写失败 |

---

## 6. CLI

```
python -m aiinvite.kernel.cli compile <store> --now ISO8601
python -m aiinvite.kernel.cli record  <store> --now ISO8601 [--force]
python -m aiinvite.kernel.cli history <store>
python -m aiinvite.kernel.cli diff    <store> --a 1 --b 2
python -m aiinvite.kernel.cli verify  <store>
```

`verify`：重新编译并与当前 `kernel/` 比对，输出 `OK kid=... version=... head=...`；不一致 `E_KN_STALE`。

---

## 7. 验收测试（六个，全绿 0 skipped）

| # | 测试 | 断言 |
|---|---|---|
| K1 | `test_kn_compile` | 同一 store 编译 **100 次，字节一致率 100%**；各条目含 evidence 且 id 存在 |
| K2 | `test_kn_determinism` | 删掉 `kernel/` 后重新 record，**kid 与 version 不变**；`restore(1)` 的 kid 等于历史记录 |
| K3 | `test_kn_gate` | ①手改 canon 后 record → `E_KN_STALE`（篡改检测），证据新增承诺但无新指令 → `E_KN_GATE_CANON`（canon 门控），`--force` 重写并追加 `tamper_healed`；②注入一次大变更 → `E_KN_GATE_DELTA`；③state 跳变 500 → `E_KN_GATE_STATE`；④各失败后 `kernel/` 目录**字节未变** |
| K4 | `test_kn_history` | HISTORY 只追加；`diff` 逐条正确；`restore` 不写盘 |
| K5 | `test_kn_sources` | 构造一条无 evidence 的条目 → `E_KN_UNSOURCED`；evidence 指向不存在事件 → 同样报错 |
| K6 | `test_kn_regression` | M1+M2+M3 的 **104 个测试仍全绿**；`jian/`、`aiinvite.cn/`、`aiinvite.recall/` 零 diff |

---

## 8. 禁止事项

1. 不许在 `compile_kernel` 里读 `kernel/`（单向派生）
2. 不许用 float（`state.json` 全整数）
3. 不许在门控失败后留下任何半成品文件
4. 不许让 `version` 参与 `kid` 计算
5. 不许为了让 K3 通过而把门控阈值调宽
6. 不许改已封版的两个包（`jian/`、`aiinvite.cn/`、`aiinvite.recall/`）

---

## 9. 这一轮真正要证明的一句话

> **同一份证据，无论今天编译、明天编译、删掉重编译，得到的是同一个人格，一个字节都不差。**

这句话比「人格更聪明」重要得多——它是后面所有承诺（可迁移、可继承、可审计）的地基。

