# TASK-01 · 容器与信任根（M1）

> 本文件是**唯一权威规格**。与 AGENTS.md 冲突时以本文件为准；对本文件有疑问必须停下提问，不许自行解释。

## 目标

让一份记忆能被写成**一个文件**、**验证没被动过**、**原样带走**。

范围：只做容器 + 事件 + 哈希链 + 校验 + 导出导入。**不写索引、不写摘要、不调 LLM、不做中文解析。**

---

## 1. 容器布局（.aiem = zip, STORE）

```
manifest.json
chain.json
evidence/seg-0001.jsonl
evidence/seg-0002.jsonl
...
REVIVAL.md
```

## 2. canonical JSON（RFC 8785 子集）

实现 `aiinvite/canonical.py::dumps(obj) -> bytes`，规则如下，**逐条都有测试**：

1. 对象键按 ASCII 排序（v1 的键全为 ASCII，用 `sorted()` 即可）
2. 分隔符固定为 `,` 与 `:`，**无任何空格**
3. 字符串：UTF-8；只转义 `"` `\\` 和 0x00–0x1F（写成 `\u00XX`）；**不得**转义 `/`、不得输出非 ASCII 转义
4. 字符串输入先做 **NFC 归一化** 再序列化
5. 数值：**v1 只允许整数**（-2^53 < n < 2^53）。**遇到 float 直接抛 `E_NOT_CANONICAL`**
6. 禁止 `NaN` / `Infinity` / `-0.0`
7. `True/False/null` 输出 `true/false/null`
8. 顶层必须是对象（v1 限制）
9. 输出为 `bytes`，UTF-8，末尾**无换行**

反例必须抛 `AiInviteError(code="E_NOT_CANONICAL")`。

## 3. 事件模型（每行一个 JSON，行尾 `\n`）

```json
{"v":1,"id":"ev_000001","ep":"seg-0001","t":"2026-10-29T06:00:00Z","type":"turn","role":"user","text":"...","prev":"00...00","hash":"9f..."}
```

| 字段 | 规则 |
|---|---|
| `v` | 固定 1 |
| `id` | `ev_` + 6 位十进制，全局单调递增，不可复用 |
| `ep` | 所属段名，如 `seg-0001` |
| `t` | 带时区 ISO 8601，**写入时统一转换为 UTC 的 `YYYY-MM-DDTHH:MM:SSZ`** |
| `type` | v1 只允许 `turn` |
| `role` | `user` / `assistant` |
| `text` | 非空字符串，长度 1–8000 字符 |
| `prev` | 上一条的 `hash`；创世为 64 个 `0` |
| `hash` | 见 §4；**计算时把 `hash` 字段排除在外** |

## 4. 哈希链

```
body    = canonical(event 去掉 hash 字段)
hash_i  = sha256( prev_i.encode('ascii') + b"\n" + body ).hexdigest()
```

- `prev_0` = `"0"*64`
- 跨段连续：`seg-0002` 的第一条事件 `prev` 等于 `seg-0001` 最后一条的 `hash`
- 每段最多 **100 条**事件

### 4.1 段的生命周期（决定 append / seal 的交互）

```
开放段 = 最后一段，且 sealed_at == null
append 规则：
  若 sealed_at != null        → 开一个新段写入（旧段永久封口）
  否则若最后一段已满 100 条    → 开一个新段写入
  否则                        → 追加到最后一行的下一行
每次 append 之后：sealed_at := null
```

**硬不变量：已封口段的文件字节永不改变。**
这是篡改检测的锚点——如果允许往已封存段里追加，段长与段尾哈希会漂移，
"封存时的快照"就不存在了，篡改检测退化成"整体重算"。

推论：`verify` 允许非最后一段的条数 < 100（它被 seal 提前封口了）。

**append 与旧 manifest 的关系（补明确）：**
`append` 之后 `sealed_at` 归 `null`，此时若目录里还存在上一次封存留下的 `manifest.json`，
**必须删除它**——它已失效，留着会让 `verify <dir>` 报"撕封"。这是唯一允许的删除动作。

### 4.2 规范字节（严格路径的新增检查）

```
每一行的字节 必须等于 canonical(event.as_dict())    // 含 hash 字段
```

不等即抛 `E_NOT_CANONICAL`，**即使语义相同**。

为什么必须查：哈希只覆盖"规范化后的 body"，所以把 `/` 改写成 `\/`、或把 LF 改成 CRLF，
哈希依然相同——语义没变，但**字节变了**。而我们的承诺是"字节可复现"，
字节漂移必须报错，否则这个承诺是半个谎。

之所以可判定：v1 的 canonical 规则已冻结，同一个字典只有唯一一种字节表示。

## 5. chain.json

```json
{"v":1,"sealed_at":"2026-10-29T07:00:00Z","segments":[{"seg":"seg-0001","count":100,"first":"...","last":"...","prev_seg":null},{"seg":"seg-0002","count":17,"first":"...","last":"...","prev_seg":"seg-0001"}]}
```

- `sealed_at`：`seal` 时写入的 UTC 时间字符串；未封存时为 `null`
- `sealed_at` 是**容器时间**（这份胶囊何时被封存），不是内容时间
- `append` 会把 `sealed_at` 重置为 `null`（表示内容已变、需重新封存）
- `count` 可以小于 100（该段被 seal 提前封口）

## 6. manifest.json

```json
{"capsule_version":1,"schema":"aiinvite.capsule/1","created":"...","hash_algo":"sha256","head":"<最后一条事件的 hash>","files":[{"path":"chain.json","sha256":"...","bytes":123}],"signature":null}
```

- `files` 按 `path` 升序，覆盖除 `manifest.json` 外的所有条目
- `signature` 在 v1 恒为 `null`（签名留给 M6）
- manifest 自身不列入 `files`

### 6.1 created 字段的取值（决定性规则，不许自行解释）

```
created := chain.json["sealed_at"]      // 直接复制，不做任何转换
```

1. `created` 是**封存时刻**，不是导出时刻；**export 过程中禁止调用任何取当前时间的方法**
2. `chain.json["sealed_at"]` 为 `null` 时，export 必须失败并抛 `E_SCHEMA`（"未封存"）
3. `import` 必须原样保留 `created`，不得重新取值
4. **不得**用首条或末条事件的 `t` 代替：那是内容时间，不是容器时间；
   且会导致"从证据重建出的胶囊，created 与原件不同"，破坏可复现性
5. 字节可复现由「只读已落盘的 `sealed_at`」保证，与导出时刻无关

## 7. zip 规则（决定字节可复现）

1. 压缩方式 **STORE**（不压缩）
2. 条目按 `path` 升序写入
3. 每个条目的 `date_time` 固定为 `(1980,1,1,0,0,0)`
4. `external_attr` 固定 `0o644 << 16`，不写 extra 字段
5. 不写目录条目

**同一输入两次导出，`.aiem` 的 sha256 必须相同。**

## 8. CLI（7 个命令）

```
python -m aiinvite.cli init    <dir>
python -m aiinvite.cli append  <dir> --role user|assistant --text "..." [--t ISO8601]
python -m aiinvite.cli seal    <dir>
python -m aiinvite.cli verify  <dir|file.aiem>
python -m aiinvite.cli export  <dir> <out.aiem>
python -m aiinvite.cli import  <in.aiem> <dir>
python -m aiinvite.cli inspect <file.aiem>
```

- `verify` 成功打印 `OK events=N segments=M head=<hex8> state=sealed|unsealed`，退出码 0
- `verify` 失败打印 `FAIL <错误码> <人话说明> [event=<id>]`，退出码 2
- 参数错误退出码 1

### 8.1 verify 的两种目标、三种状态

**核心原则：证据是唯一真源，manifest / chain 都是派生元数据。**

```
verify <dir>           证据在就能验，不要求已 seal
verify <file.aiem>     解包后必须有 manifest.json（胶囊是密封件）
```

| 输入 | manifest/chain 缺失 | 结果 |
|---|---|---|
| 目录 | 两者都缺（从未 seal） | **成功**，`state=unsealed`，退出码 0 |
| 目录 | chain 在、manifest 在 | 成功，交叉校验，`state=sealed` |
| 目录 | 两者存在但与证据不符 | 失败，`E_HEADER_MISMATCH`（manifest）或 `E_CHAIN_MISSING`（chain） |
| 目录 | **只有 manifest、没有 chain**（撕封） | 失败，`E_HEADER_MISMATCH`，**且报错文本必须提示恢复路径**：执行 `seal` 重建 chain，或删除 manifest 以证据为准 |
| .aiem | 缺 manifest.json | 失败，`E_HEADER_MISMATCH` |
| 任意 | evidence 目录缺失或为空 | 失败，`E_CHAIN_MISSING` |

**错误码归属（不许混用）：**

| 情形 | 码 |
|---|---|
| 段文件丢了 / 段内链断 / 跨段 prev 不接 | `E_CHAIN_MISSING` |
| 胶囊缺 manifest / manifest 的 files 与内容不符 / head 与末条不符 | `E_HEADER_MISMATCH` |
| 事件内容与 hash 不符 | `E_TAMPER` |

**为什么不允许"必须已 seal"：** 如果 verify 依赖 manifest 才能工作，
那 manifest 就成了真相的一部分，"只留证据能复活"这句话就是假的。
未封存目录能被验证，是这条架构承诺的第一次真实检验。

## 9. 错误码（固定，不许新增同类）

| 码 | 含义 |
|---|---|
| `E_NOT_CANONICAL` | 输入无法规范化（含 float / 非法字符） |
| `E_SCHEMA` | 字段缺失、类型错、越界 |
| `E_TAMPER` | 内容与哈希不符 |
| `E_CHAIN_MISSING` | 段或事件缺失、链断裂 |
| `E_HEADER_MISMATCH` | manifest 与实际文件不符 |
| `E_IO` | 文件读写失败 |
| `E_ARG` | 命令行参数错误 |

## 10. 八个验收测试（必须全绿，0 skipped）

| # | 测试 | 断言 |
|---|---|---|
| T1 | `test_canonical_vectors` | 10 组黄金向量输出与期望字节**完全相同**（含键序、中文 NFC、转义、大整数） |
| T2 | `test_canonical_rejects` | 输入 float / NaN / 孤立代理对 / 非对象顶层 → 抛 `E_NOT_CANONICAL` |
| T3 | `test_chain_links` | 追加 250 条 → 3 段；段内 prev 正确；跨段 prev 正确；**seal 后再 append：旧段文件字节哈希不变、开出新段、`sealed_at` 变 `null`** |
| T4 | `test_tamper_one_byte` | ①改 seg 文件里某条事件的 1 个字节 → verify 失败且**报出具体 event id**；②把某行里的 `/` 改写成 `\/`（语义相同、字节不同）→ `E_NOT_CANONICAL`；③把某行结尾改成 CRLF → `E_NOT_CANONICAL` |
| T5 | `test_missing_segment` | 删除 seg-0002 → verify 失败 `E_CHAIN_MISSING` |
| T6 | `test_zip_deterministic` | 同目录导出两次 → 两个 `.aiem` 的 sha256 相同；导出前后 `manifest.created` 不变；**未封存目录 export 抛 `E_SCHEMA`** |
| T7 | `test_roundtrip_and_perf` | export→import→export 字节一致；**import 后再 export，`created` 仍等于原值**；10,000 条事件 verify **< 2000ms**（单测只防 O(n²) 回归，不测真实 SLO） |

> 真实性能由 `tools/bench.py` 单独输出（目标 < 200ms），**不作为单测门禁**。
> 理由：墙钟受机器负载影响（实测同码同数据 0.14s–1.03s 波动），把 SLO 写进单测必然偶发红。
| T8 | `test_verify_modes` | ①未 seal 目录 verify **成功**且含 `state=unsealed`；②缺 manifest 的 `.aiem` 失败 `E_HEADER_MISMATCH`；③manifest 与证据不符失败 `E_HEADER_MISMATCH`；④**删掉 chain.json 但留着 manifest** → 失败 `E_HEADER_MISMATCH`，且输出含恢复提示 `seal`；⑤随后执行 `seal` 能修复并 verify 通过 |

## 11. REVIVAL.md（导出时自动生成）

必须包含：事件总数、段数、head、字段说明、以及**不依赖本代码的复活步骤**（用 Python 标准库读 jsonl 的 5 行伪代码）。

## 12. 明确不做

- 不做签名、不做加密（M6）
- 不做索引、不做摘要、不做检索
- 不做中文解析、不做 MCP、不做 UI
- 不写论文、不写 README 营销语

