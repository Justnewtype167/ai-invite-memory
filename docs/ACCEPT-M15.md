# ACCEPT-M15 · 哀悼与继承（遗赠胶囊）

> 规格：`docs/TASK-20-succession.md`
> 参照：`docs/ACCEPT-M14.md`（胶囊与流）、`docs/ACCEPT-M1.md`（哈希链）
> 结论：**签收**。胶囊自包含、离线可验、脱敏必留痕、身份必可重算。

---

## 0. 交付物

| 文件 | 内容 |
|---|---|
| `aiinvite.succession/errors.py` | `E_SUCC_MODE / DRIFT / REDACTION / HEADER / SCHEMA / IO` |
| `aiinvite.succession/model.py` | 常量、`Letter`、`LegacyInfo`、策略编解码、`recompute_kid` |
| `aiinvite.succession/archive.py` | zip / JSON / 证据 / 载荷 / 编译原语 |
| `aiinvite.succession/legacy.py` | `export_legacy` / `verify_legacy` / `import_legacy` |
| `aiinvite.succession/__init__.py` | 公开 API |
| `tests/test_succession.py` | Y1–Y6 共 17 个测试 |
| `tests/test_all_regression.py` | 扫描包加 `aiinvite.succession`；`ALLOWED_ADDITIONS` 声明 5 个新文件 |

`aiinvite/`、`aiinvite.kernel/`、`aiinvite.recall/` **一个字节都没动**：遗赠层只调用它们的公开 API。

---

## 1. 胶囊里有什么

```
legacy.aiem.zip                     （STORE 不压缩、时间戳归零、条目按名排序）
  manifest.json     format / format_version / created / kid / policy_digest / head
                    / files[path, sha256, bytes] / signature=null
  chain.json        v / sealed_at / segments（与普通胶囊同一套 chain_document）
  evidence/seg-NNNN.jsonl
  blobs/<sha256>    v2 载荷（v1 没有这一层）
  letters/letter-1.txt   who / when / to / 空行 / 正文
  policy.json       编译策略（缺了就无法复算 kid）
  redaction.json    excluded / reason / redacted_kid / origin_kid / evidence_sha256
  succession.json   successor_kid / derived_from / redacted / created / mode
```

`manifest.files` 覆盖除 `manifest.json` 外的每一条目，因此**任何字节改动都会露馅**：
改 `redaction.json` → `E_SUCC_REDACTION`；改 `succession.json` → `E_SUCC_SCHEMA`；
改证据或载荷 → `E_SUCC_HEADER`；改 `policy.json` → `E_SUCC_HEADER`（`policy_digest` 对不上）。

---

## 2. 脱敏怎么实现（不是「删掉就行」）

删一条事件会让后面所有序号、段名、`prev` 全部失效。所以脱敏是**重建证据链**：

```
1. 过滤被排除的事件
2. 重编号 ev_000001..ev_NNNNNN（format_id）
3. 每 100 条重分段 seg-0001..（SEGMENT_MAX_EVENTS）
4. 逐条重算 prev / hash（GENESIS_PREV 起）
5. feedback 的 target 按旧→新映射；target 也被排除则整次导出失败（E_SUCC_REDACTION）
6. 用新证据 + 随包策略重算 kid → redacted_kid
```

`redaction.json.evidence_sha256` 是「证据段路径 + 段 sha256」的规范化摘要，
`verify_legacy` 会重算并比对——清单和证据因此是**互相绑定**的，不能各自被改。

脱敏清单还要求：`excluded` 严格升序无重复、`reason` 恰好覆盖 `excluded`、
原因只能是 `third_party / private / requested`、不能把全部证据排除。

---

## 3. `mode` 与身份

- `mode` 只接受 `inherit`。`copy` / `continue` / `successor` / 空串一律 `E_SUCC_MODE`。
- `successor_kid` = 用**随包证据 + 随包策略**重算出来的 kid（与普通 kid 同一函数）。
- `derived_from` = 脱敏前的 `origin_kid`，只作血缘记录，**不参与身份判定**。

按 TASK-20 §3.1：**未脱敏时 `successor_kid == origin_kid` 是正确的**。
删掉的字节让证据变了，身份才会变；本项目**没有**用「再哈希 metadata」制造不等。
`_check_redaction_values` 把这条写成硬约束：

```
发生过脱敏  → origin_kid != manifest.kid   （不等必须来自证据变化）
未脱敏      → origin_kid == manifest.kid   （身份必须与来源一致）
```

---

## 4. 手工记录（真实输出）

夹具：14 条事件（含 2 条第三方发言、1 条私事、1 条 feedback），策略 `now=2026-11-01T00:00:00Z`。

```
原 store：kid=28de15e8dbf817852e8bab0cdee9c6dfd7a9aec45729a0ecbba04395d9c9889e
          events=14 segments=1

导出 legacy 胶囊 → 大小 7771 字节，文件数 8
                     ['REVIVAL.md', 'chain.json', 'evidence/seg-0001.jsonl',
                      'letters/letter-1.txt', 'manifest.json', 'policy.json',
                      'redaction.json', 'succession.json']

去掉 3 条（ev_000005/000006 third_party，ev_000007 private）
          origin_kid  = 28de15e8dbf817852e8bab0cdee9c6dfd7a9aec45729a0ecbba04395d9c9889e
          redacted_kid= ca65e9028edff463ddced116d322dbc113e7e10b2cd3de69dd7fdbcb8dfdb40d
          events 14 → 11，segments 1 → 1

接手方重算 → ca65e9028edff463ddced116d322dbc113e7e10b2cd3de69dd7fdbcb8dfdb40d
          与 redacted_kid 相同？

successor_kid = ca65e9028edff463ddced116d322dbc113e7e10b2cd3de69dd7fdbcb8dfdb40d
derived_from  = 28de15e8dbf817852e8bab0cdee9c6dfd7a9aec45729a0ecbba04395d9c9889e

偷改 succession.json 的 mode → E_SUCC_MODE
偷改 redaction.json 的 excluded → E_SUCC_REDACTION
```

未脱敏路径（同一 store）：`kid = origin_kid = successor_kid = 28de15e8...`，`redacted=false`。

---

## 5. 验收对照

| # | 测试 | 断言 | 结果 |
|---|---|---|---|
| Y1 | `test_legacy_roundtrip` | 导出→导入→重算 == `manifest.kid`；14 条一致 | 通过 |
| Y2 | `test_redaction_is_recorded` | 3 条原因；`redacted_kid != origin_kid`；重算等于 `redacted_kid` | 通过 |
| Y3 | `test_redaction_is_verifiable` | 改 `redaction.json`（清单 / 原因）→ `E_SUCC_REDACTION` | 通过 |
| Y3b | `test_deleted_evidence_without_record_is_caught` | 偷偷删一行证据 → `E_SUCC_HEADER` | 通过 |
| Y4 | `test_successor_identity` | 脱敏后 `!= origin_kid` 且 `redacted=true`；未脱敏 `==` 且 `redacted=false` | 通过 |
| Y4b | `test_successor_kid_is_recomputable` | 第三方重算 == `successor_kid`；改策略一字节 → 不等且 `verify` 失败 | 通过 |
| Y5 | `test_mode_is_inherit_only` | 4 个非法值全 `E_SUCC_MODE` | 通过 |
| Y5b | `test_capsule_contains_no_runnable_payload` | 胶囊只有 `.json/.jsonl/.md/.txt` | 通过 |
| Y6 | `test_all_regression` | 全量测试全绿、改动在白名单 | 通过 |

其余：未封存拒绝导出、非法排除 id/原因/全排除、字节可复现、导入不覆盖非空目录、
`Letter`/`policy` 往返、zip 与证据原语。

---

## 6. 诚实说明

1. **`kid` 不依赖 `delta_limit`**，依赖 `known_days`（即策略 `now`）、事件条数、
   canon、图与来源。因此「改一字节 → 身份变」的演示用 `policy.now`，不用 `delta_limit`。
   这不是缺陷，是 M4 的身份定义：身份跟踪的是渲染出的内容，不是编译参数。
2. **脱敏后段数不变**在这个夹具里是 11 条 < 100；超过 100 条时会按 100 重分段，
   段名与 `chain.json` 一起重建。
3. **不做「继续运行」**：胶囊里没有任何可执行入口，Y5b 用后缀白名单把这条钉住。
4. 本轮不做「它知道用户已故」这类语义，`letters/` 只是原样搬运的明文。

---

## 7. 测试输出

```
Ran 315 tests in 170.762s
OK
```

（M14.1 的 298 + 本轮新增 17 = 315，0 skipped，0 failures，0 errors。）

---

# 独立复核（验收方以「接手方」身份复跑）

## 1. M15：以第三方视角验证「能不能带走」

| 检查 | 结果 |
|---|---|
| 原样导出（无脱敏） | `successor_kid == origin_kid`，`redacted=False` —— **相同是正确的** |
| 第三方接手：全新目录导入后重算 kid | 与原 kid **一致** |
| 脱敏 2 条第三方发言 | `redacted=True`，`successor_kid != origin_kid`，`excluded=[ev_000002, ev_000004]`，原因 `third_party` |
| 篡改 `redaction.json` | `E_SUCC_REDACTION: 文件大小与 manifest 不符` |
| 伪造 `mode=continue` | `E_SUCC_MODE: mode 只能是 inherit，收到：continue` |
| 未封存仓库导出 | `E_SUCC_SCHEMA: 目录未封存，不能导出遗赠胶囊` |

**六项全过。** 尤其是第一、二行合起来说明：

> **拿走一个胶囊的人，能在自己的机器上重算出同一个身份。**
> 这句话过去只是设计承诺，现在是可复现的行为。

## 2. 顺带复核 M14.1 的计数口径

| 场景 | scanned | loaded | reused | 判定 |
|---|---|---|---|---|
| 冷启动（首轮） | 0 | 4 | 0 | ✅ 没有新事件走失效；代价由 `loaded` 可见 |
| 第二轮（无追加） | 0 | 0 | 2 | ✅ 两个子查询全命中 |
| 追加一条**无关**普通对话 | 1 | 0 | **2** | ✅ **真正省工**：一个都没失效 |
| 追加一条**匹配 md 的旧年**事件 | 1 | 3 | 1 | ✅ 只失效 `same_day`，`promises` 仍命中 |
| 等价性（换 now 后新会话） | — | — | — | ✅ items 与全量逐字节相同 |

### 一个由此简化掉的场景

`StreamSession.now` 是**构造时固定的**，所以「同一会话里 now 漂移」根本不存在——
上一轮讨论的「改 now 如何与新增桶区分」在实现层面自动消失了。

**这是好设计：把不确定性挡在构造函数之外，比在运行时处理它更省事。**

## 3. 数字

```
测试    315 全绿（294 + 21）
包      7 个（新增 aiinvite.succession）
既有包  aiinvite/ aiinvite.kernel/ aiinvite.recall/ 一个字节都没动
```

## 4. 结论

```
M15：通过。AUDIT-01 里「能带走、能验明、且留下脱敏记录」全部兑现
M14.1：通过（计数口径与字节等价同时对）
```

打 tag `v0.18-m15`。
