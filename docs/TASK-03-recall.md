# TASK-03 · 检索与预算装配（M3）

> 本文件是 M3 的**唯一权威规格**。与 AGENTS.md 冲突以本文件为准；有疑问停下提问。

## 0. 范围与三个必须先定的取舍

| 取舍 | 决定 | 理由 |
|---|---|---|
| 向量检索 | **M3 不做** | 嵌入模型会引入三方依赖与网络调用，直接摧毁「零成本、可逐字节复现」这个卖点。留给 M4/M5 单独决策 |
| 词法检索 | **做**：SQLite FTS5 + 中文二元切分 | Python 自带 sqlite3 3.49 已编译 FTS5（实测索引 20 万条 1.25s、查询 1.8ms） |
| token 计数 | **代理估算器** | 无 tokenizer 依赖；估算偏保守，真实差异 ±30%，接口可替换 |

| 许做 | 不许做 |
|---|---|
| 新增 `jian_recall/` | 修改 `jian/`（M1 冻结）、`jian_cn/`（M2 冻结）任何一行 |
| 新增 `tests/test_rc_*.py` | 调用任何模型、任何网络接口、任何第三方库 |
| 在 `pyproject.toml` packages 里加 `jian_recall` | 引入 float（数据 JSON 里也不行） |

---

## 1. 目录

```
jian_recall/
  __init__.py
  errors.py          # E_RC_*
  tokenizer.py       # estimate_tokens + bigrams
  index.py           # build / update / status（FTS5）
  retrieve.py        # query → candidates
  assemble.py        # 预算装配
  trigger.py         # 同日历史 + 承诺关键词
  cli.py             # build / update / status / ask
  data/qa_labels.json
tests/test_rc_tokenizer.py · test_rc_index.py · test_rc_retrieve.py
      test_rc_assemble.py · test_rc_trigger.py · test_rc_perf.py
      test_rc_quality.py · test_rc_regression.py
```

---

## 2. token 估算器（必须先写，后面全靠它）

```python
def estimate_tokens(text: str) -> int
```

规则（固定，不许自行调整权重）：

```
汉字        1.0 token / 字
ASCII 字母  0.25 token / 字符，每个 ASCII 词最少算 1
数字        0.5 token / 字符
标点/符号   1.0 token / 个
每条消息    +8 token 固定开销
结果向上取整
```

**为什么保守**：真实中文 tokenizer 通常 1 字 ≈ 0.6–0.8 token。按 1.0 估，
4k 预算实际约等于 5–6k 真实 token 的安全区。宁可少装，不可超限。

### 2.1 中文二元切分

```python
def bigrams(text: str) -> str        # 用于 FTS5 索引列，空格分隔
```

- 只取汉字（U+4E00–U+9FFF），其余字符丢弃
- 连续汉字串切成重叠二元：`手术很顺利` → `手术 术很 很顺 顺利`
- 长度 1 时输出该字本身；空输入返回空串

---

## 3. 索引（可从证据完全重建）

```
store/            ← M1 的证据目录（evidence/seg-*.jsonl）
store/.index/idx.sqlite   ← 派生物，可随时删除重建
```

表结构（FTS5 虚拟表 + 一张元数据表）：

```sql
CREATE VIRTUAL TABLE ev USING fts5(event_id UNINDEXED, seg UNINDEXED, ts UNINDEXED, bg);
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);   -- head / count / version
```

### 3.1 三个 API

```python
def build_index(store: Path) -> IndexStatus     # 全量重建
def update_index(store: Path) -> IndexStatus    # 按 LSN 增量
def index_status(store: Path) -> IndexStatus    # events_indexed / lsn / stale
```

### 3.2 四条硬规则

1. **索引只是派生物**：删掉 `.index/` 必须能靠 `build_index` 完全恢复
2. **LSN**：`meta.head` 记录已索引到的最后一条事件 id；`update_index` 只处理 head 之后的事件
3. **stale 检测**：`meta.head` ≠ 证据最后一条 id 时 `stale=True`；消费方必须处理，不许静默用旧索引
4. **单写者**：只有 `index.py` 写 `.index/`，其它模块只读

---

## 4. 检索

```python
def search(store: Path, query: str, k: int = 50) -> list[Hit]
```

- 查询同样过 `bigrams()`，用 FTS5 MATCH 取前 k
- `Hit = {event_id, seg, ts, score, text}`
- 打分：FTS5 的 bm25 分数取负（越大越相关），再乘时间衰减——

```
final = bm25_relevance * (0.5 + 0.5 * exp(-days_since / 365))
```

- 无命中返回空列表，不抛错

---

## 5. 预算装配（M3 的核心）

```python
def assemble(store: Path, query: str, budget: int = 4096, now: str | None = None) -> Context
```

### 5.1 三个槽位（kernel 槽位预留但 M3 为空）

| 槽位 | 预算占比 | 内容 |
|---|---|---|
| kernel | 20% | **M3 恒为空**（内核在 M4 才有），额度并入 retrieved |
| recent | 25% | 最近 8 条事件原文 |
| retrieved | 55%（含 kernel 让出的 20%） | 检索命中，去重后按分数排序 |
| trigger | 10% | 同日历史 + 承诺关键词命中 |

### 5.2 装配算法

```
候选池 = recent ∪ retrieved ∪ trigger
目标：max Σ utility(c) - λ·ΣΣ sim(i,j)   s.t.  Σ tokens(c) <= budget
utility = 槽位权重 × 检索分数 × 时间因子
贪心：每步选边际收益/代价最大者；同类相邻事件合并为一个块
输出顺序固定：trigger → retrieved（分数降序）→ recent（时间降序）
```

### 5.3 三条输出规则

1. `Context` 必须带 `total_tokens`、`items`（每条含 event_id / 槽位 / 文本）
2. **确定性**：同一 store + 同一 query + 同一 budget + 同一 now ⇒ 输出**字节一致**
3. 超出预算时**先丢 retrieved 尾部**，再丢 trigger，最后才动 recent

---

## 6. 触发器（规则，不调模型）

```python
def triggers(store: Path, now: str) -> list[Hit]
```

只有两条规则：

1. **同日历史**：`now` 的月-日，在过去年份中出现的同月同日事件（最多 3 条）
2. **未完成承诺**：文本含「答应」「保证」「说好」「下次一定」且不含「已」「完成了」的事件（最多 2 条）

---

## 7. 错误码

| 码 | 含义 |
|---|---|
| `E_RC_NO_INDEX` | 索引不存在，需先 build |
| `E_RC_STALE` | 索引落后于证据（meta.head ≠ 证据 tail） |
| `E_RC_BAD_BUDGET` | budget < 256 或 > 200000 |
| `E_RC_IO` | 读写失败 |

---

## 8. CLI

```
python -m jian_recall.cli build  <store>
python -m jian_recall.cli update <store>
python -m jian_recall.cli status <store>
python -m jian_recall.cli ask    <store> "问题" --budget 4096 --now 2026-10-29T10:00:00+08:00
```

`ask` 输出 JSON：`{total_tokens, items:[{event_id,slot,tokens,text}], stats:{candidates,took_ms}}`

---

## 9. 评估集（规格方给定，实现只需读它）

`data/qa_labels.json` 共 20 条，每条：

```json
{"id":"Q01","question":"我妈手术是什么时候","gold":"我妈下周三做手术","ts":"2024-03-12T21:10:00Z"}
```

测试做法（`test_rc_quality.py` 必须这样做）：

1. 用 20 条 gold 各建一条事件（时间取 `ts`），再加 **N 条干扰事件**
2. 干扰事件从规格 §10 的 50 句池中确定性抽取，seed 固定 `20261029`，铺满 2023-01-01 到 2026-10-01
3. 对每条 Q，用 `assemble(budget=4096)` 取上下文，判定 **gold 文本是否出现在装配结果里**
4. 保真度 = 命中数 / 20；基线 = 同样数据下 `budget=32768` 的命中率
5. 要求：**保真度 ≥ 0.90 × 基线**，且 **保真度 ≥ 0.85**

---

## 10. 干扰句池（50 句，测试用）

```
今天天气不错 / 中午吃了碗面 / 地铁上人很多 / 晚上加班到九点 / 周末想睡个懒觉
楼下的花开了 / 手机又没电了 / 快递放在门口 / 明天要早起赶车 / 杯子摔碎了
会议改到下午三点 / 空调有点冷 / 路上下起了雨 / 冰箱里没有鸡蛋了 / 记得交水电费
同事换了新工位 / 电影票买好了 / 衣服该洗了 / 键盘有点卡 / 路上堵了半小时
晚饭吃的是面 / 买了双新鞋 / 头有点疼 / 周日去看牙 / 院子里的猫又来了
电话打不通 / 文件传不上去 / 网慢得要命 / 咖啡洒在桌上 / 想换个手机
下班路上听了会儿歌 / 楼下在装修 / 灯坏了一盏 / 又涨房租了 / 公交挤不上去
菜市场的鱼很新鲜 / 热水器不热 / 用了半年的耳机坏了 / 隔壁很吵 / 银行卡找不到了
忘记带钥匙 / 早上起晚了 / 邮箱里全是广告 / 朋友约了爬山 / 想去看海
打印纸用完了 / 窗台上落了灰 / 昨晚没睡好 / 雨伞落在公司了 / 忙到没吃午饭
```

---

## 11. 验收测试（八个，全绿 0 skipped）

| # | 测试 | 断言 |
|---|---|---|
| R1 | `test_rc_tokenizer` | 20 组固定向量；`bigrams("手术很顺利")=="手术 术很 很顺 顺利"`；空串/单字/纯 ASCII 边界 |
| R2 | `test_rc_index` | 建索引 20 万条 < 60s；删 `.index/` 后 rebuild 得到相同 head/count；增量 update 后 head 正确；head 落后 → `E_RC_STALE` |
| R3 | `test_rc_retrieve` | 20 条 gold 各自能被 search 命中 top-50；无命中返回 `[]`；结果按分数降序 |
| R4 | `test_rc_assemble` | 3k 预算实测 token ≤ 预算；两次装配**字节一致**；超预算时按 §5.3 顺序丢弃 |
| R5 | `test_rc_trigger` | 同日历史最多 3 条且月日正确；承诺规则命中且能排除「已完成」 |
| R6 | `test_rc_perf` | 20 万事件索引下，`assemble(4096)` **p95 < 80ms**（50 次查询取样） |
| R7 | `test_rc_quality` | 按 §9 方法：**保真度 ≥ 0.90 × 基线** 且 **≥ 0.85** |
| R8 | `test_rc_regression` | M1 的 31 + M2 的 44 = **75 个测试仍全绿** |

---

## 12. 禁止事项

1. 不许改 `jian/` 与 `jian_cn/`（两个模块都已封版）
2. 不许引入向量/嵌入模型（哪怕本地）
3. 不许为了让 R6 过而缩短测试集或跳过预热
4. 不许把检索写成一堆 if/elif 关键词分支来通过 R3 与 R7
5. 不许省掉 stale 检测

