# TASK-14 · 载荷与信封（M10）

> 目标：让**证据层与模态无关**。
> 现在事件把 `text` 内联，音频帧、动作序列、传感读数无处安放。
> 本里程碑**不做**任何新模态的解析——只把“装载方式”改成可扩展的。

写前已过 `docs/SPEC-CHECKLIST.md` 十问；约束 C14（绝对时延不进单测门禁）适用。

---

## 0. 一句话与边界

```
改的是「事件怎么装内容」，不是「内容是什么」。
文本仍是本轮唯一被解析的模态；音频/动作只保证能装、能验、能导出。
```

## 1. 冻结例外

| 可改 | 不可改 |
|---|---|
| `aiinvite/event.py`、`aiinvite/capsule.py`、`aiinvite/chain.py`、`aiinvite/cli.py` | `aiinvite.cn/`、`aiinvite.recall/`、`aiinvite.kernel/`、`aiinvite.pcs/` |
| `tests/` 新增 | 已有事件的哈希算法、canonical 规则 |

**本轮只动证据层。** 上层四个包一行都不许改——这是检验「地基改动是否真的对上层透明」的机会。

---

## 2. 信封 v2

```json
{"v":2,"id":"ev_000123","ep":"seg-0001","t":"2026-11-01T10:00:00Z",
 "type":"turn","modality":"text",
 "payload":"sha256:ab12cd34...",
 "summary":"我今天很累。",
 "prev":"...","hash":"..."}
```

| 字段 | 规则 |
|---|---|
| `v` | 固定 `2`；`v=1` 的旧事件继续被接受（见 §5） |
| `modality` | 必填，白名单：`text` / `audio` / `vision` / `action` / `sensor` |
| `payload` | 必填，形如 `sha256:<64 位小写十六进制>` |
| `summary` | 必填，1–200 字符，**仅供检索与预算装配**，不参与人格规则判定 |
| `text` | **v2 禁止**（出现即 `E_SCHEMA`） |

**`summary` 为什么要必填**：检索层 `aiinvite.recall` 只读文本，
若不给摘要，非文本事件在检索里等于不存在。
它也是 4k 预算机制保持不变的唯一前提。

---

## 3. 载荷存储（blob store）

```
store/blobs/<sha256 十六进制>      原始字节，文件名即内容哈希
```

| 规则 | 说明 |
|---|---|
| **内容寻址** | 文件名 = 内容的 sha256；写入前校验，不一致即 `E_BLOB_MISMATCH` |
| **只增不改** | 同一哈希只写一次；写入即不可变 |
| **可缺失检测** | 事件引用的 blob 缺失，`verify` 必须报 `E_BLOB_MISSING` |
| **不压缩不加密** | 本轮不做；加密留到具身/隐私里程碑 |

文本载荷 = UTF-8 字节；其它模态 = 原始字节，格式由 `modality` 约定，本轮不解析。

---

## 4. 链与清单

```
chain.json     仍只记录事件哈希与 head；新增 "blobs": ["ab12...", ...]
manifest.json  新增 "format": 2，"blob_count": N
```

**`blobs` 列表必须覆盖该段引用的全部载荷**。导出时只打包被引用到的 blob。

---

## 5. 兼容（硬要求）

```
① v1 胶囊必须仍能 verify / import / export
② v1 目录必须仍能 seal
③ 一个 store 的格式由 manifest.format 决定，不允许混写
④ 读到 v2 事件的旧版本实现应报 E_SCHEMA，不许崩
```

**M1 的 31 个测试必须仍全绿**——这是本轮最重要的回归项。

---

### 5.1 唯一访问器（关键决定）

上层**不许直接读原始 JSON 的 `text` 字段**——那是把模态写死在上层。
证据层提供一个访问器，作为唯一入口：

```python
def event_text(data: dict[str, object]) -> str:
    """返回事件的人类可读文本：v1 取 text，v2 取 summary。"""
```

**为什么不让 v2 同时写 `text=summary`**（曾考虑过的方案）：

```
· 两份真相：text 与 summary 可以不一致，而哈希只覆盖 summary
· 篡改面：改 text 不会被链发现——直接违反 C1
· 结论：宁可改三行上层，也不造第二份真相
```

## 6. 上层如何消费

**原文写的是「上层零 diff」——这条是我写错了。** 实测上层有三处直接读 `data.get("text")`，
v2 禁止 `text` 之后它们必然取到空串。

| 文件 | 改动 | 行数 |
|---|---|---|
| `aiinvite.recall/index.py` | 顶层 `from aiinvite.event import event_text` + 调用 | 2 |
| `aiinvite.kernel/proposer.py` | 同上 | 2 |
| `aiinvite.kernel/compiler.py` | 顶层 `from aiinvite.capsule import event_full_text` + 调用（**读全文，不读 summary**） | 2 |

**合计 6 行（每文件 2 行：import + 调用）。**
最初写的「3 行」不成立——没有 import 就无法调用，这是我第二次低估了改动面。

**除此之外，四个上层包的所有其它文件必须零 diff**，
`aiinvite.cn/` 与 `aiinvite.pcs/` 完全零 diff。

**判断标准改成：只允许这三处一行改动，且逐行可审计。**
用一条脚本列出这四个包的 diff，行数必须正好是 3。

---

## 7. 新增的篡改面（必须都能被发现）

| 攻击 | 检测 |
|---|---|
| 改 blob 内容 | 文件名与内容哈希不符 → `E_BLOB_MISMATCH` |
| 删 blob | 事件引用的载荷缺失 → `E_BLOB_MISSING` |
| 换 blob 指向 | 事件头部的 `payload` 与链上哈希绑定，改即 `E_TAMPER` |

---

## 8. 错误码（新增两个）

| 码 | 含义 |
|---|---|
| `E_BLOB_MISSING` | 引用的载荷不存在 |
| `E_BLOB_MISMATCH` | 载荷内容与其哈希不符 |

---

## 9. 验收（七个）

| # | 测试 | 断言 |
|---|---|---|
| N1 | `test_env_v2` | 五种 modality 各写一条 → seal → verify；非法 modality、缺 payload、缺 summary、v2 带 text → 各报 `E_SCHEMA` |
| N2 | `test_blob_store` | 内容寻址写入；重复内容只写一份；篡改 blob → `E_BLOB_MISMATCH`；删 blob → `E_BLOB_MISSING` |
| N3 | `test_env_roundtrip` | export → import → export **逐字节一致**，且 blob 随包往返 |
| N4 | `test_env_v1_compat` | v1 胶囊仍可 verify；只有 turn 的 v1 目录仍可 seal；**M1 的 31 个测试全绿** |
| N5 | `test_upper_layers_touch_limit` | 四个上层包的 diff **恰好 6 行**（三文件各 2 行：import + 调用）；其余文件 sha256 与基线一致；`aiinvite.cn/`、`aiinvite.pcs/` 完全零 diff |
| N6 | `test_summary_only_retrieval` | 检索只用 `summary`：把 payload 换成等长随机字节，检索结果不变 |
| N7 | `test_all_regression` | 现有 **246 个测试仍全绿** |

---

## 10. 禁止

1. 不许在本轮解析音频/视频/动作（只保证能装能验）
2. 不许改已有事件的哈希算法
3. 不许让上层产生第 4 处改动（已列的 3 行是上限，不是起点）
4. 不许把 blob 塞进 `.index/`（载荷是证据的一部分，不是派生）
5. 不许在 verify 里跳过 blob 校验以求快

---

## 11. 完成定义

```
python -m unittest discover -s tests -v      # 全绿、0 skipped
```

并附一段手工记录：

```
同一段对话：
  v1 格式 → kid=A
  v2 格式（文本转 payload+summary）→ kid=相同？
```

**如果 kid 不同，必须解释清楚为什么**——这决定 M11 的轨迹实验能不能做。


## 12. 冻结棘轮（本轮新增机制）

`tests/test_all_regression.py` 引入 `ALLOWED_CHANGES = {文件: 原因}`：

```
与上一版相比，任何文件哈希有变，必须在此声明，否则测试失败
反向也检查：声明了但实际没改，同样失败（防止声明腐烂）
```

**意义**：开冻结从「改哈希字典」变成「在测试里写一行理由」。
这一轮 `aiinvite/capsule.py`、`aiinvite/event.py`、`aiinvite/chain.py`、`aiinvite.kernel/*` 的改动全部被声明。
