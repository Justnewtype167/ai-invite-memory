# TASK-25 · 每轮成本：从 O(n) 重建到只处理新增（M36）

> 目标：20k 事件的每轮成本从约 1.7 s 降到毫秒级，200k 不要退化成分钟级。
> 手段：索引按字节偏移增量、证据段按字节偏移增量、快照把 graph 旁置、每次 prompt 只读一次证据。
> 结果：**20k 每轮 1.7 s → 0.67 s；200k 每轮 5.4–6.6 s → 3.1–3.5 s。没有达到「200k ≤ 150 ms」，原因见 §7。**

---

## 0. 一句话

```
每轮真正变动的只有「新追加的那几十条」。
索引、证据解析、用户卡都能只读新增；但 kid 要对全量 graph 做一次哈希，
这一次 O(n) 是身份的代价，不是实现的疏漏。
```

---

## 1. 先量（20k 合成库，单次 prompt_for）

| 阶段 | 旧成本 | 占比 |
|---|---|---|
| 索引全量重建 `build_index` | 860–1180 ms | 最大头 |
| 内核快照重写 `write_snapshot` | 470–580 ms | 第二 |
| 证据段重解析 `EvidenceCache.read` | 180–245 ms | 第三 |
| pins 全扫 | 67–97 ms | |
| 用户卡 | 3–21 ms（M35 已增量） | |

合计约 1.7 s/轮。三个大头各有各的原因，必须分开治。

---

## 2. 索引：按字节偏移续写

旧 `update_index` 已经有「只插 head 之后的事件」的语义，但它为此要**解析全部证据文件**才能找到 head 之后的行。
解析本身是 O(n)，所以「增量」只省了插入，没省读取。

现在 `aiinvite/recall/index.py`：

- `meta` 记 `last_seg` / `last_size`（已索引到的段与字节偏移）与 `head`
- `_read_appended(path, offset)` 从偏移处 `rb` 读余下字节，只解析**完整行**，返回新的完整偏移
- 续写前校验边界：`_last_event_id(path, offset)` 必须等于 `meta["head"]`，文件变短或边界行被改写 → `E_RC_STALE`（让调用方全量重建，而不是悄悄索引错位）
- 段滚动：从新段的首字节读；末段记新的 `last_seg` / `last_size`
- 半行（进程在写事件中途死掉）不索引，`status.stale = True`，下一轮补全后自然接上

**不改 `build_id`**：`aiinvite/recall/stream.py` 用 `build_id` 判断「索引是否被重建」来失效触发器缓存；增量更新若换了 `build_id`，热路径会每轮误判重建。

---

## 3. 证据解析：段级偏移增量 + 一次目录枚举

旧 `EvidenceCache` 按整段缓存，追加一条事件就让**整段**（100 条）重解析；并且每轮对每个段文件调一次 `path.stat()`。

两个都修了，第二个比第一个重要得多：

- 键从 `(size, mtime)` 改为「已解析字节数 + 末条 id」；增长时只解析 offset 之后的行；截断 / 同尺寸原地改写 → 整段重解析
- `_scan(folder)` 用 `os.scandir` 一次枚举拿 `(name, path, st_size, st_mtime_ns)`，不再逐文件 `stat()`

**为什么 `stat` 是黑洞**：本机（Windows + Defender 实时扫描）单次 `path.stat()` 约 3 ms，200 个段文件 ≈ 640 ms，
而 `EvidenceCache.read()` 每轮被调 3 次（内核、用户卡、pins 各一次）≈ 1.9 s。`scandir` 直接读目录项，200 个文件 4–8 ms。
这不是「解析慢」，是「问文件系统问得太多次」。

---

## 4. 快照：graph 旁置，少两次全量序列化

`kid = hash(self_md, canon_md, state, graph, origin, models)`，所以每轮至少要对全量 graph 做一次规范化编码。
旧 `write_snapshot` 在这一次之外又做了三次：算摘要一次、写文件一次、`load_snapshot` 校验再一次。

`SNAPSHOT_FORMAT = 2`：

- graph 写入同目录 `graph.json`，`snapshot.json` 只存 `graph_digest`
- 写入路径：graph 只编码一次，`digest = sha256(graph_raw)`，两次原子替换
- 读取路径：读 `graph.json` 字节 → 比对 sha256 → `json.loads`。摘要不符 / 文件缺失 → `E_KN_SNAPSHOT`（手改必须被发现，不能静默接受）
- `format == 1`（v0.40 及更早写的库，graph 内联）继续可读，读到即迁移为 2

真实用户库（%APPDATA%\AIInvite\memory，20 事件，format 1）验证：迁移后 `graph.json` 生成、
用户卡仍是「称呼：老周」、冷启动会话读 v2 快照正常。

---

## 5. 一次 prompt 只读一次证据

`prompt_for` 需要证据三次（内核、用户卡、pins）。改为：

```python
try:
    events = self._events()
except (KernelError, AiInviteError):
    events = []
card, persona, view = self._card_and_persona(events)
pinned = self._pinned(events)
```

空库仍走原来的降级路径（`_kernel([])` 抛错被 `_card_and_persona` 原有 except 捕获，返回空卡）。
`tests/test_host_adapter.py::test_prompt_reads_evidence_once` 用计数包装 `session._evidence.read` 守门。

---

## 6. 实测

同一台机器（Windows 11，16 GB，测量时 Trae / DSH / 微信在跑，可用内存约 2.6 GB），
合成库每 100 条一段，`STAMP = 2026-11-12T10:00:00Z`，cold = `on_user` + 首次 `prompt_for`，warm = 三轮 `on_user/prompt_for/on_assistant`。

| 事件数 | 旧每轮 | 现在每轮 | 冷启动 |
|---|---|---|---|
| 20k | ~1.7 s | **666–695 ms** | 13.2 s |
| 200k | 5.4–6.6 s | **3.06–3.51 s** | 130.0 s |

20k 热轮分解（ms）：kernel 339–361、stream.context 136–146、index_update 74–81、snapshot_write 105–117、
snapshot_load 44–56、pins 32–35、events 19–21。

200k 热轮分解（ms）：kernel 2052–2391、snapshot_write 527–643、pins 304–340、
snapshot_load 235–273、stream_context 162–191、index_update 120–140、events 105–121。

演进（20k 每轮）：1.7 s →（scandir 证据枚举）0.88–0.95 s →（快照旁置）0.88–0.95 s →（一次读）0.67 s。

---

## 7. 没做到的部分，以及为什么

**200k 距离 150 ms 还有 20 倍，而且不是再优化一下就能到的。**

剩下的都是设计层面的 O(n)：

1. `kernel_kid` 对全量 graph 做 `canonical.dumps`（200k 约 2 s 中的大部分）。只要 kid 的定义是
   「对 graph 的全部内容做哈希」，它就必须每次看全部内容。这不是缓存能解决的——缓存只能省重复调用，省不了这一次。
2. `write_snapshot` 还要对 graph 编码一次（200k 约 0.5 s）。这一点**可以**和 kid 共用同一份字节，但需要让
   `canonical.dumps` 支持「已编码片段」——在身份代码里开这种口子，收益 1 s、风险是 kid 值可能因编码路径不同而变，我判断不值。
3. `_merge_graph` 排序 O(n log n)、`_render_self_stats` 扫全部边、`load_snapshot` 反序列化全量 graph、pins 全扫、stream 索引。
4. 冷启动 200k 130 s（索引 39 s、证据解析 34 s、内核 49 s）——这是首次见面的一次性成本，不随轮数增长，但仍需在文档里说清。

**真正的 O(delta) 需要改身份语义**，三条路，都需要你拍板：

- **A. kid 改为对 `graph_digest` 做哈希**：O(1)，但**所有已有库的 kid 都会变**，导出的胶囊身份对不上。可做 `kid_v2`，但那样每轮仍要算 v1 才能兼容，等于没省。
- **B. kid 延迟计算**：只在导出 / 校验 / 展示时算。prompt 路径能省约 2 s（200k），但每轮快照写入的 kid 字段就必须变成「上次算过的」，`kid` 与当前 graph 的对应关系不再是每轮强一致。
- **C. 接受现状**：把 200k 当容量上限的一部分写进文档（每轮 3 s，界面可感知但不算卡死）。

我的建议是 **C，并把 B 作为将来的可选项**：陪伴场景里 20k 事件（约两年、每天几十句）每轮 0.67 s 已经够用；
200k 是「十年不离不弃」的极端情形，那时如果真到 3 s，用户换机的动机也出现了。

---

## 8. 测试

| 文件 | 条数 | 守什么 |
|---|---|---|
| `tests/test_index_increment.py` | 7 | 同段追加 / 滚动新段后与全量重建逐表相等；无变化 no-op 且 `build_id` 不变；增量不动 `build_id`；截断 → `E_RC_STALE`；边界行改写 → `E_RC_STALE`；半行不索引 |
| `tests/test_snapshot_graph.py` | 4 | graph 旁置布局与摘要吻合；改 / 删 graph → `E_KN_SNAPSHOT`；format 1 内联快照仍可加载且 kid 相同 |
| `tests/test_evidence_cache.py` | 10 | 追加一条只解析一条；连续追加只解析新增；半行不解析、补全后接上；同尺寸改写整段重解析 |
| `tests/test_host_adapter.py` | 17 | 一次 prompt 只读一次证据；增量卡 == 全量卡；热会话 prompt == 冷会话 |

一条被测试逼出来的注意事项：`update_index` 先看 `index_status`，**尺寸没变就不 stale**，直接早退。
所以「同尺寸原地改写」只有在下一次追加时才会被抓住；内容审计要用 `index_status(verify_sample=...)`。
这是有意的分工（每轮不做全量审计），测试里写明了。

---

## 9. 改动清单

- `aiinvite/recall/index.py`：`update_index` 偏移续写；`_index_rows` / `_insert_rows` / `_read_appended` / `_last_event_id`
- `aiinvite/kernel/cache.py`：`_scan`（scandir）、`_advance` / `_parse_from` / `_tail_event_id`、`parsed_events` 计数
- `aiinvite/kernel/snapshot.py`：`SNAPSHOT_FORMAT = 2`、`graph.json` 旁置、`_load_graph`、format 1 兼容
- `aiinvite/host/__init__.py`：`_ensure_index` 先 `update_index` 再回退全量；`_kernel` / `_pinned` / `_card_and_persona` 接受共享 events；`prompt_for` 一次读取
- 新增 `tests/test_index_increment.py`、`tests/test_snapshot_graph.py`；`tests/test_evidence_cache.py` +4；`tests/test_host_adapter.py` +1
