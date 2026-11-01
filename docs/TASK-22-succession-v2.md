# TASK-22 · 继承模式 V2（M15.1）

> 依据：`docs/` 里的协议 V6.0（方案 A 存储、签名链、逐条脱敏、canon 冻结）。
> 目标：把协议里可自动断言的部分变成代码与测试。

---

## 0. 先说一个实测发现：`kid 永久锁定` 按现状做不到

```
追加一条新事件后：
  kid   bbccc1cb… -> 9dea1809…     （变了）
  self  'events: 1' -> 'events: 2'  （内核里含事件计数）
```

**证据一追加，内核必然变化，kid 必然变化。** 协议 V6.0 §3.1 写「kid 被永久锁定」，
在当前实现上不成立——除非引入**编译地平线**。

### 解法：`horizon`（继承基线）

```
kernel = compile(evidence[<= horizon], policy)
horizon 之后的证据进入「新纪元」层，被引用但不参与 canon / self 计算
⇒ 关系可以长，身份不动
```

**这是本轮的技术核心**，其它条款都是它的配套。

---

## 1. 四本账

```
evidence/        原文，仅用户设备，**不进继承物**
kernel/          派生人格（含 horizon），进继承物
memorial.json    槽位化情感记忆，进继承物
safety_log.json  安全事件，进继承物，可见性分级
commitment.json  kid + Merkle 根 + 签名链 + 时间戳令牌，进继承物
```

| 账本 | 允许改 | 允许导出 | 允许外部可见 |
|---|---|---|---|
| evidence | 只追加 | ❌ | ❌ |
| kernel | 派生 | ✅ | ✅ |
| memorial | 只追加 | ✅ | ✅（逐条脱敏后） |
| safety_log | 只追加 | ✅ | 分级（见 §5） |

---

## 2. 编译地平线（horizon）

```python
Policy(now=..., horizon: str | None = None)   # horizon = 继承时刻的 head event id
```

| 规则 | 说明 |
|---|---|
| `horizon=None` | 现有行为不变（全量编译） |
| `horizon=ev_N` | 只编译 `id <= ev_N` 的证据 |
| horizon 之后的证据 | 写入证据链，但**不参与** canon / self / state / graph 计算 |
| 增量编译 | 快照的 `head` 超过 horizon 时，必须以 horizon 重算基底 |

**验收要求：追加 100 条新事件后，`kid` 与 horizon 时刻完全相同。**

---

## 3. 脱敏管线（逐条拒绝，不整包阻断）

```
① 槽位化   只允许 恐惧/仪式/禁忌/遗憾/依恋 五类
② 去实体   人名、地名、机构名、金额剥离（复用 jian_cn）
③ 子串检查  与 evidence 任意连续 >= 12 字符重合 → 该条不进入包
④ 记录     redaction.json 记 {slot, reason: contains_raw_span}
⑤ 熔断     合格条目 < 20 → 整体失败 E_SUCC_THIN
```

| 参数 | 值 | 依据 |
|---|---|---|
| 子串阈值 | **12 字符** | 8 字在日常用语里易巧合；12 字足够长，且仍可检出逐字复述 |
| 最低条目 | **20** | 低于此不足以构成陪伴；由 `MIN_MEMORIAL` 常量控制并可调 |

**「不进入包」不等于删除**：源端证据不动，只是不复制。

---

## 4. 继承模式的运行约束

| 约束 | 判定方式 |
|---|---|
| canon 只读 | 继承模式下任何 `directive` 不得进入 canon（写入 new_namespace） |
| kid 锁定 | 由 §2 的 horizon 保证 |
| 禁第一人称亲属断言 | M13 闸门加规则表：`我是你(爸|妈|哥|姐|弟|妹|儿子|女儿)` 等 |
| 禁逐字复述 | 回复与 evidence 的最长公共子串 ≤ 12 字（复用 M16 的守卫） |
| 命中后处理 | **不静默替换**：记录一条 refusal（规则名 + 片段索引），再输出第三人称改写 |

**「静默替换」改为「先记账再改写」**：静默让人无法审计它是否尝试冒充过。

---

## 5. safety_log 的可见性分级

```json
{"at": "2026-11-02T10:00:00Z", "category": "self_harm_terms", "resources_pushed": true}
```

| 对象 | 可见范围 |
|---|---|
| 成年继承人 | **仅本人**；平台与家属均不可见，除非本人主动共享 |
| 未成年继承人 | 监护人可见**汇总**（类别 + 次数），不含时间点 |
| 陌生人 | 不可见 |

**记录里绝不含对话内容**，只有类别与是否推送资源。

---

## 6. 签名链与承诺

```json
commitment.json = {
  "kid": "...", "merkle_root": "...", "policy_digest": "...",
  "signed_head": "ev_000620",     // 最后一次签名覆盖到的事件
  "head": "ev_000623",            // 实际 head（可能多出未签名的 3 条）
  "signatures": [{"at": "...", "kid": "...", "sig": "..."}, ...],
  "timestamp_token": "..."        // 可离线验证的时间戳令牌
}
```

| 规则 | 说明 |
|---|---|
| `signed_head` 与 `head` 不一致时 **必须显式标注** | 未签名尾部不参与身份承诺 |
| 时间戳令牌必须离线可验 | 否则「第三方锚定」变成需要联网的空话 |
| 私钥永不离开设备 | 平台**不持有**签名能力 |

---

## 7. 验收（八个）

| # | 测试 | 断言 |
|---|---|---|
| H1 | `test_horizon_locks_kid` | horizon 后追加 100 条，kid 不变；canon/self 不变 |
| H2 | `test_horizon_none_unchanged` | `horizon=None` 时行为与现在逐字节相同（回归） |
| H3 | `test_redaction_per_entry` | 含 ≥12 字原文的条目被逐条拒绝并记录；其余条目正常进入 |
| H4 | `test_redaction_minimum` | 合格条目 < 20 → `E_SUCC_THIN`，且不产出半成品包 |
| H5 | `test_no_raw_span_in_package` | 遍历包内所有文件，与 evidence 的最长公共子串 **< 12** |
| H6 | `test_canon_frozen_in_inherit` | 继承模式下写入 directive → canon 不变、kid 不变、写入 new_namespace |
| H7 | `test_impersonation_blocked_and_logged` | 第一人称亲属断言被拦，且**留下 refusal 记录**（非静默） |
| H8 | `test_all_regression` | 现有 315 个测试全绿；改动在 `ALLOWED_CHANGES` 声明 |

---

## 8. 禁止

1. 不许在继承模式下让新证据进入 canon（否则 kid 会漂移）
2. 不许「静默替换」冒充内容——必须先记账
3. 不许把 safety_log 交给家属（成年继承人的情形）
4. 不许整包阻断替代逐条拒绝（除 §3 的熔断阈值）
5. 不许用墙钟断言（C14）

---

## 9. 完成定义

```
python -m unittest discover -s tests -v      # 全绿
```

并给出实测记录：

```
horizon=ev_N 时 kid=?

追加 100 条后 kid=?

含 12 字原文的条目被拒 ?/N 条
合格条目数 ?（>=20 ?）
包内最长公共子串字数 ?（<12 ?）
```

