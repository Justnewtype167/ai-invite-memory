# TASK-02 · 中文三件套（M2）

> 本文件是 M2 的**唯一权威规格**。与 AGENTS.md 冲突时以本文件为准；有疑问停下提问，不许自行解释。

## 0. 范围与边界（先看这条）

| 许做 | 不许做 |
|---|---|
| 新增顶层包 `jian_cn/` | **修改 `jian/` 里任何一行**（M1 已封版，tag v0.1-m1） |
| 新增 `tests/test_cn_*.py` | 修改 `.aiem` 容器格式或事件模型 |
| 新增 `jian_cn/data/*.json` | **调用任何 LLM、任何网络接口、任何第三方库** |
| 在 `pyproject.toml` 的 packages 里加 `jian_cn` | 引入 float（数据文件里也不行） |

**M2 全部用规则实现，模型调用次数必须为 0。** 这是本模块唯一的、也是最大的竞争优势：
别人用模型抽关系，我们用规则；成本为零、结果可复现、可审计。

---

## 1. 目录（严格按此）

```
jian_cn/
  __init__.py
  errors.py          # E_CN_* 错误码
  normalize.py       # 繁简 / 异体 / 全半角 / 空白 / 零宽
  kinship.py         # 称谓图
  timex.py           # 相对时间
  slang.py           # 梗的时效
  cli.py             # 4 个命令
  data/
    variants.json            # 繁→简、异体归一（只这一个方向）
    kinship.json             # 称谓词表
    kinship_labels.json      # 标注集（**先提交**）
    timex_labels.json        # 标注集（**先提交**）
    slang.json               # 词条：born / peak / cringe / tags / source / confidence
    slang_holdout.json       # 留出集（**先提交，实现不许读它**）
tests/
  test_cn_normalize.py
  test_cn_kinship.py
  test_cn_timex.py
  test_cn_slang.py
  test_cn_hygiene.py         # 零模型 / 确定性 / 无 float
```

---

## 2. 数据纪律（三条，全部可机器检查）

### 2.1 标签先行提交

**必须分两次提交，顺序不能反：**

```
commit A: 只提交 data/*_labels.json + data/slang_holdout.json + LABELS.md（数据来源与判据说明）
commit B: 提交实现代码
```

原因：如果实现先有、标签后补，标签必然是照着实现写的——测试就变成了自证。
验收时会用 `git log --name-only` 检查这个顺序。

### 2.2 无 float

所有 JSON 里**不得出现浮点数**。年份用 int，分数用 0–1000 的 int，概率用 0–100 的 int。
检查方式：`json.loads(..., parse_float=raise)` + 静态扫描源码里的小数字面量。

### 2.3 每条数据要能溯源

`slang.json` 每条必须有 `source`（如「百度指数峰值年」）与 `confidence`（0–100）。
`confidence < 60` 的条目**不得进入 usable 判定**（只用于展示），否则等于用猜测当标准。

---

## 3. 模块一：称谓图（kinship）

### 3.1 规范化形式

从「我」出发的**边序列**，点号分隔：

```
F 父   M 母   H 夫   W 妻
OB 兄  YB 弟  OS 姐  YS 妹
s 儿子  d 女儿
```

示例：

```
父亲        F
爷爷        F.F
外婆        M.M
伯父        F.OB
叔叔        F.YB
姑妈        F.S            （S 为姐妹，无长幼时用 S）
舅舅        M.B
姨妈        M.S
堂哥        F.OB.s  + age=older
表哥        M.S.s / F.S.s / M.B.s   （父系兄弟之子才是「堂」）
侄子        OB.s
```

### 3.2 输出类型

```json
{"term":"表哥","candidates":["M.S.s","M.B.s","F.S.s"],"age":null,"ambiguous":true,"note":"父系兄弟之子为堂，其余为表"}
```

- `candidates`：并列可能，按常见度排序
- `age`：`"older"` / `"younger"` / `null`
- `ambiguous`：true 表示仅凭词面无法确定
- 未收录的词：抛 `E_CN_UNKNOWN_TERM`，**不许猜**

### 3.3 必须覆盖

直系三代（父母/祖父母/外祖父母/子女/孙）、旁系常见（伯叔姑舅姨、堂表兄弟姐妹、侄甥）、
姻亲（配偶、公婆、岳父母、嫂子/弟媳/姐夫/妹夫、小舅子）、
称呼变体（爸/爹/老爸/父亲；妈/娘/老妈/母亲大人；干爹/干妈；师傅）；
方言变体至少 2 个（粤语「阿妈」、川渝「老汉儿」）。

### 3.4 评分

`kinship_labels.json` 至少 **120 条**，主指标 = **候选集合完全匹配率 ≥ 0.90**，副指标 micro-F1。

---

## 4. 模块二：相对时间（timex）

### 4.1 输出类型

```json
{"start":"2026-10-27","end":"2026-10-27","granularity":"day","certainty":"exact"}
{"start":"2026-08-01","end":"2026-10-31","granularity":"month","certainty":"range"}
{"start":null,"end":null,"granularity":"event","certainty":"unknown","note":"等孩子高考完"}
```

`granularity ∈ {day, week, month, season, year, event}`；`certainty ∈ {exact, range, vague, unknown}`。
锚点时间必须带时区，统一换算到 **UTC+08:00** 后计算（中文语境默认东八区）。

### 4.2 必须支持（逐条都有测试）

```
今天/昨天/前天/大前天/明天/后天/今晚/昨晚/今早
这周/上周/上上周/下周/月初/月中/月底
这个月/上个月/上上个月/下个月/季度末
今年/去年/前年/明年/去年这时候
三天前/半个月前/半年前/三年前/十年前
过了年/春节前/中秋/国庆/清明（固定节日表，按年算）
最近/那阵子/前几天（vague，给 3–7 天窗口）
秋收后/入冬前（季节窗口）
等孩子高考完/等我出院（event，certainty=unknown）
```

### 4.3 评分

`timex_labels.json` 至少 **120 条**；**区间完全一致率 ≥ 0.95**；
另附 50 条畸形输入（空串/纯符号/超长/无锚点），要求 **100% 不崩溃**且抛 `E_CN_PARSE`。

---

## 5. 模块三：梗的时效（slang）

### 5.1 曲线

每个词条给定 `born`（开始流行）、`peak`（峰值）、`cringe`（明显过时）三个年份，
可用度 `a(term, year)` 为分段折线，返回 **0–1000 的整数**：

```
year < born          a = 0
born ≤ year ≤ peak   a 从 300 线性升到 1000
peak < year ≤ cringe a 从 1000 线性降到 400
year > cringe        a = 200
```

`usable(term, year) = a >= 600`。未收录词：`usable` 返回 False，`explain` 返回「未收录」。

### 5.2 API

```python
def availability(term: str, on: date) -> int | None   # None = 未收录
def usable(term: str, on: date, threshold: int = 600) -> bool
def explain(term: str, on: date) -> str               # 人话，例如「2021 年峰值，已过时 5 年」
def lifespan(term: str) -> dict | None
```

### 5.3 留出集（这条决定整件事是否可信）

`slang.json` 是**实现可读的词表**；`slang_holdout.json` 是**独立评测集，实现不许读**。

```json
[{"term":"yyds","year":2021,"usable":true},{"term":"yyds","year":2026,"usable":false}]
```

**留出集由规格方给出（见附录 A），实现方只需保证测试读取它。**
评分：留出集上 **usable 判定准确率 ≥ 0.90**，且同一词条在 peak 之后的可用度**单调不增**。

---

## 6. 模块四：规范化（normalize）

```python
def normalize(text: str) -> str
```

顺序固定：NFC → 剥离零宽字符 → 全角转半角（仅 ASCII 范围）→ 繁转简（仅字符级）→ 空白折叠。

**只做一个方向：繁→简。禁止简→繁**（简→繁需要词级消歧，「干」会变成「乾/幹」）。
**只做字符级，不做词组转换**（避免「头发→頭髮」这类误判）。

评分：给定 200 字测试集，转换覆盖 **≥ 0.99**；且 **幂等**（`normalize(normalize(x)) == normalize(x)`）；
对已是简体、纯 ASCII 的文本 **必须零改动**。

---

## 7. 错误码（固定）

| 码 | 含义 |
|---|---|
| `E_CN_UNKNOWN_TERM` | 称谓词未收录 |
| `E_CN_PARSE` | 时间表达无法解析 |
| `E_CN_BAD_ANCHOR` | 锚点时间缺失或无时区 |
| `E_CN_DATA` | 数据文件缺失/格式错/含 float |

---

## 8. CLI（4 个命令）

```
python -m jian_cn.cli kinship 堂哥
python -m jian_cn.cli timex "大前天" --anchor 2026-10-29T10:00:00+08:00
python -m jian_cn.cli slang yyds --on 2026-10-29
python -m jian_cn.cli norm "臺灣裏面"
```

成功退出码 0；`E_CN_*` 退出码 2；参数错误 1。

---

## 9. 六个验收测试（必须全绿，0 skipped）

| # | 测试 | 断言 |
|---|---|---|
| C1 | `test_cn_kinship` | 120 条标注，候选集合完全匹配率 **≥ 0.90**；未收录词抛 `E_CN_UNKNOWN_TERM` |
| C2 | `test_cn_timex` | 120 条标注，区间完全一致率 **≥ 0.95**；50 条畸形输入 100% 不崩溃 |
| C3 | `test_cn_slang` | 留出集 usable 判定准确率 **≥ 0.90**；peak 后单调不增；`confidence<60` 不参与判定 |
| C4 | `test_cn_normalize` | 200 字覆盖 ≥ 0.99；幂等；简/ASCII 输入零改动；**反向转换不存在** |
| C5 | `test_cn_hygiene` | 全仓 `jian_cn/` 无网络/LLM/第三方导入；数据 JSON 无 float；两次运行输出字节一致 |
| C6 | `test_cn_regression` | **M1 的 31 个测试仍全绿**（跑 `unittest discover` 全量） |

---

## 10. M2 特有禁止事项

1. 不许改 `jian/` 下任何文件（改了就说明你在拿 M1 迁就 M2）
2. 不许在实现里读 `slang_holdout.json`（读一次就作废）
3. 不许为达标去改标签文件（标签先行提交后即为只读）
4. 不许用「模型兜底」——遇到不会的就抛 `E_CN_*`，**不许猜**
5. 不许引入任何第三方依赖（含 jieba、opencc、pypinyin）

---

## 附录 A · 留出集（规格方给定，直接写入 `data/slang_holdout.json`）

```json
[{"term":"yyds","year":2021,"usable":true},{"term":"yyds","year":2026,"usable":false},
 {"term":"绝绝子","year":2021,"usable":true},{"term":"绝绝子","year":2026,"usable":false},
 {"term":"尊嘟假嘟","year":2023,"usable":true},{"term":"尊嘟假嘟","year":2026,"usable":false},
 {"term":"栓Q","year":2022,"usable":true},{"term":"栓Q","year":2026,"usable":false},
 {"term":"破防","year":2021,"usable":true},{"term":"破防","year":2023,"usable":true},
 {"term":"显眼包","year":2023,"usable":true},{"term":"显眼包","year":2026,"usable":false},
 {"term":"班味","year":2024,"usable":true},{"term":"班味","year":2026,"usable":false},
 {"term":"city不city","year":2024,"usable":true},{"term":"city不city","year":2026,"usable":false},
 {"term":"躺平","year":2021,"usable":true},{"term":"躺平","year":2025,"usable":true},
 {"term":"内卷","year":2020,"usable":true},{"term":"内卷","year":2026,"usable":false},
 {"term":"emo","year":2020,"usable":true},{"term":"emo","year":2024,"usable":false},
 {"term":"芭比Q","year":2022,"usable":true},{"term":"芭比Q","year":2026,"usable":false}]
```

> 这 24 条是 v0.1 参考答案，不是真理。允许在 `LABELS.md` 里记录修订，但**修订必须保留原值**。
> 它的作用只有一个：防止实现自己出题、自己判卷。

