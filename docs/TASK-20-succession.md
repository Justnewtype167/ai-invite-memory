# TASK-20 · 哀悼与继承（M15，MVP）

> 目标：**用户不在了以后，有人能验证「它还是它」，并且能把它带走。**
> 本轮只做**继承**，不做「继续运行」——后者是治理决定，不是工程决定。

---

## 0. 边界（先说不做什么）

```
做    遗赠胶囊：证据 + 策略 + 明文说明 + 脱敏清单；接手方重算 kid 验明身份
不做  不做「AI 是否应继续运行」、不做「它知不知道用户已故」、不做自动运行
```

**这两件事必须分开：协议可以写死，伦理不能由工程师单方面决定。**

---

## 1. 遗赠胶囊（legacy capsule）

```
legacy.aiem.zip
  manifest.json      format / created / kid / policy_digest / format_version
  evidence/          证据段（与普通胶囊相同）
  blobs/             载荷（v2 才有）
  letters/           明文说明（谁、何时、给谁），可选一条
  redaction.json     脱敏清单：被排除的条目 id 与原因
  succession.json    继承声明：successor_kid / 派生自哪个 kid / 时刻
```

| 规则 | 说明 |
|---|---|
| **自包含** | 不含任何外部引用；接手方离线可验 |
| **可验身份** | 重算 kid 必须等于 `manifest.kid`，否则 `E_SUCC_DRIFT` |
| **脱敏留痕** | 被排除的条目写进 `redaction.json`，并与证据层 hash 绑定 |
| **新身份** | 继承后生成 `successor_kid`，**不冒用原 kid** |

---

## 2. 脱敏（这是最容易做错的部分）

```
问题：证据里有对方的发言，对方没同意被继承
做法：按事件粒度排除，并把排除清单写进 redaction.json
要求：排除后**重算 kid 必然变化**——必须显式记录「这是脱敏后的派生身份」
```

| 字段 | 含义 |
|---|---|
| `excluded` | 被排除的事件 id 列表 |
| `reason` | 每条的原因（`third_party` / `private` / `requested`） |
| `redacted_kid` | 脱敏后重算的 kid |
| `origin_kid` | 脱敏前的 kid |

**不许悄悄删除**：删了不记录，接手方无法判断「这是原本的样子吗」。

---

## 3. 继承声明

```json
{
  "successor_kid": "sha256:...",   // 用脱敏后的证据 + 随包策略重算出来的 kid
  "derived_from": "sha256:...",    // 继承前的 origin_kid，只作血缘记录
  "redacted": true,                // 是否发生过脱敏
  "created": "2026-11-01T00:00:00Z",
  "mode": "inherit"                // 只有 inherit，没有 continue
}
```

`mode` 只有 `inherit` 一个值，是刻意的：**协议层面不提供「继续运行」这个选项**。
将来要加，必须走规格变更，而不是加个枚举值。

### 3.1 `successor_kid` 的定义（这决定协议是否可验证）

```
successor_kid = 用继承后的证据 + 随包策略重算出来的 kid
                （与普通 kid 同一个函数，同一套规则）
```

| 情形 | 结果 |
|---|---|
| 没有脱敏、策略未变 | `successor_kid == origin_kid` —— **这是正确的，不是 bug** |
| 发生过脱敏 | 证据变了 ⇒ `successor_kid != origin_kid`，且 `redacted=true` |

**不用「再哈希一次」来制造不等。** 那样会让身份依赖 `created` 这类元数据，
破坏「同内容 ⇒ 同身份」这条最基本的性质。

**不等必须由证据变化引起，不能由包装引起。**

---

## 4. 与既有机制的关系

| 已有 | 本轮如何用 |
|---|---|
| 胶囊（M1/M10） | 复用导出/导入；legacy 是它的超集 |
| kid（M4） | 身份验证的核心；脱敏后重算 |
| 策略（M4） | 必须随包携带，否则重算出来是另一个人 |
| 增量（M12） | 不需要：继承是一次性的全量 |

---

## 5. 验收（六个）

| # | 测试 | 断言 |
|---|---|---|
| Y1 | `test_legacy_roundtrip` | 导出 → 导入 → 重算 kid == `manifest.kid`；证据条数一致 |
| Y2 | `test_redaction_is_recorded` | 排除 3 条 → `redaction.json` 有 3 条原因；`redacted_kid != origin_kid`；重算等于 `redacted_kid` |
| Y3 | `test_redaction_is_verifiable` | 有人偷改 `redaction.json` → `verify` 失败（清单与证据哈希绑定） |
| Y4 | `test_successor_identity` | `successor_kid == 重算 kid`；未脱敏时 `== origin_kid` 且 `redacted=false`；脱敏后 `!= origin_kid` 且 `redacted=true` |
| Y4b | `test_successor_kid_is_recomputable` | 第三方拿到胶囊：重算 → 等于 `successor_kid`；改一个字节 → 不等且 `verify` 失败 |
| Y5 | `test_mode_is_inherit_only` | `mode` 非法值（如 `continue`）→ `E_SUCC_MODE` |
| Y6 | `test_all_regression` | 现有 **294 个测试全绿**；改动只在白名单内声明 |

---

## 6. 禁止

1. 不许实现「继续运行」或任何形式的自动接续
2. 不许在无记录的情况下删除证据条目
3. 不许用「再哈希 metadata」的方式制造 `successor_kid != origin_kid`
4. 不许把策略从胶囊里省掉（省了就无法复算）
5. 不许在本轮引入「它知道用户已故」这类语义

---

## 7. 完成定义

```
python -m unittest discover -s tests -v      # 全绿、0 skipped
```

并提交手工记录：

```
原 store：kid=?, events=?
导出 legacy 胶囊 → 大小 ?, 文件数 ?
去掉 3 条第三方发言 → origin_kid=?, redacted_kid=?
接手方重算 → 与 redacted_kid 相同？
successor_kid=?, derived_from=?
```

**「有人能带着它走」这句话，只有这份记录落下来，才不是修辞。**

