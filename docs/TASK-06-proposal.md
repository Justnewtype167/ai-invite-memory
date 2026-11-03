# TASK-06 · 提案进链路，但不接模型（M5 第一步）

> 路线依据：`docs/M5-ROUTE.md`（A 提案即证据 + B 规则提交；C 只用于不进身份的层）。
> 这一步**不调用任何模型**：提案由 `ReplayProposer` 从证据里读，先证明链路对。
> 写规格前已过 `docs/SPEC-CHECKLIST.md` 十问。

## 0. 这一步只证明一件事

```
同一份证据（含提案） ⇒ 同一个 kid
换一份证据（少一条提案）⇒ kid 必须变，且 origin 必须标出来
```

**不许静默等价。** 这是整份规格最重要的一条。

---

## 1. 冻结例外

| 可改 | 不可改 |
|---|---|
| `aiinvite/event.py`（加第 6 种事件类型） | `aiinvite/capsule.py`、`aiinvite/cli.py` |
| `aiinvite.kernel/*`（新增 proposal 支持） | `aiinvite.cn/`、`aiinvite.recall/` 全部 |
| `tests/` 新增 | 事件哈希算法、canonical 规则 |

---

## 2. 第 6 种事件：`proposal`

```json
{"v":1,"id":"ev_000123","ep":"seg-0001","t":"2026-10-30T10:00:00Z",
 "type":"proposal","target":"self.style","model":"deepseek-v4",
 "prompt_sha":"ab12cd34","text":"说话时偶尔停顿，不急着给结论",
 "prev":"…","hash":"…"}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `target` | ✅ | **白名单**：M5 只允许 `self.style` |
| `model` | ✅ | 非空字符串，≤64 字符 |
| `prompt_sha` | ✅ | 非空十六进制，≤64 字符 |
| `text` | ✅ | 1–500 字符 |
| `role` / `kind` | ❌ | 出现即 `E_SCHEMA` |

**为什么提案要进证据层**：它也是「发生过的事」（模型在某时刻被要求提议）。
进了证据层，它才有哈希、才可审计、才能随胶囊搬到别的设备。

---

## 3. 提案如何影响内核（只影响一处）

```
self.md = 规则骨架（统计填空）
        + 「风格」小节（由被接受的 proposal 文本按 event_id 升序拼成）

canon / state / graph：完全不受提案影响
```

**canon 只能由 `directive` 事件改**——这条不许因为提案而松动。

### 3.1 三条约束

1. 每条提案文本截断到 **120 字符**
2. 「风格」小节总量上限 **800 字符**（超出按 event_id 顺序截断）
3. 同一 `target` 的提案最多接受 **8 条**，其余计入 `rejected`

---

## 4. `META.origin`：三态，且会改变 kid

| origin | 条件 |
|---|---|
| `rule_only` | 证据里没有任何 proposal 事件，且策略未要求提案 |
| `with_proposals` | 至少接受 1 条提案 |
| `rule_fallback` | 策略要求提案（`require_proposals=True`）但证据里没有，且显式 `--allow-fallback` |

```
三者 kid 互不相同 —— 因为 origin 写入 META，META 参与 kid。
```

> 这是「不许静默等价」的技术保证：**换了输入源，身份就一定变**，
> 谁都能看出来这份人格是「模型参与过」还是「规则兜底」。

### 4.1 缺口行为

```
policy.require_proposals = True 且证据无提案：
  默认   → E_KN_NO_PROPOSAL（硬失败）
  --allow-fallback → 规则兜底，origin=rule_fallback，kid 变化
```

---

## 5. 新门控 G5

| # | 条件 | 违反 |
|---|---|---|
| G5a | `target` 必须在白名单内 | `E_KN_BAD_TARGET`（硬失败，不是拒绝——说明写入方有 bug 或有人在试探） |
| G5b | `model` 与 `prompt_sha` 非空 | `E_KN_BAD_PROPOSAL` |
| G5c | 同 target 接受数 ≤ 8 | 超出部分记 `rejected`，不报错 |

G1–G4 保持不变。

---

## 6. 接口

```python
# 写入一条提案（供 ReplayProposer 使用；真模型在 M5 第二步接）
def record_proposal(store: Path, target: str, text: str, model: str,
                    prompt_sha: str, t: str | None = None) -> EvidenceEvent

# 编译：proposer 缺省为 ReplayProposer（读证据里的提案）
def compile_kernel(store, policy=None, proposer=None) -> Kernel

# 记录：新增 fallback 开关
def record_kernel(store, policy=None, force=False, allow_fallback=False) -> RecordResult
```

`ReplayProposer` 行为：按 `event_id` 升序返回所有 `target == "self.style"` 的提案。

CLI：

```
python -m aiinvite.kernel.cli propose <store> --text "…" --model m --prompt-sha abc123
python -m aiinvite.kernel.cli compile <store> --allow-fallback
```

---

## 7. 错误码（新增两个）

| 码 | 含义 |
|---|---|
| `E_KN_BAD_TARGET` | 提案 target 不在白名单 |
| `E_KN_BAD_PROPOSAL` | 提案缺 model / prompt_sha / text 非法 |
| `E_KN_NO_PROPOSAL` | 策略要求提案但证据里没有，且未开 fallback |

---

## 8. 验收（七个，全绿 0 skipped）

| # | 测试 | 断言 |
|---|---|---|
| P1 | `test_kn_proposal_event` | 写入/读回/校验一致；缺 `model`、缺 `prompt_sha`、带 `role` → 各报 `E_SCHEMA` |
| P2 | `test_kn_proposal_effect` | 有提案 vs 无提案 → **kid 不同**；`origin` 分别为 `with_proposals` / `rule_only` |
| P3 | `test_kn_proposal_required` | `require_proposals=True` 且无提案 → `E_KN_NO_PROPOSAL` |
| P4 | `test_kn_fallback` | 同上 + `allow_fallback` → 成功，`origin=rule_fallback`，**kid 与 P2 两种都不同** |
| P5 | `test_kn_gate5` | `target=canon` → `E_KN_BAD_TARGET`；12 条同 target → 接受 8 条、`rejected=4` |
| P6 | `test_kn_proposal_determinism` | 有提案时，跨进程（不同 PYTHONHASHSEED）kid 一致 |
| P7 | `test_all_regression` | 现有 **148 个测试仍全绿**；`aiinvite.cn/`、`aiinvite.recall/` 零 diff |

---

## 9. 禁止

1. 不许让提案影响 `canon` / `state` / `graph`（只能影响 `self.md` 的风格小节）
2. 不许在缺提案时静默用规则兜底（必须报错，或显式 fallback 且改 kid）
3. 不许把 `origin` 放在 kid 之外
4. 不许接真模型（本步只用 `ReplayProposer`）
5. 不许改 `aiinvite.cn/`、`aiinvite.recall/`

---

## 10. 完成定义

```
python -m unittest discover -s tests -v      # 全绿、0 skipped
```

并附一段手工验证记录：

```
同一 store：
  无提案  → kid=A  origin=rule_only
  加 1 条  → kid=B  origin=with_proposals
  删掉证据里那条提案 → kid 必须回到 A
```

第三行是这条链路真正的证明：**提案在，人格变；提案走，人格回来。**

