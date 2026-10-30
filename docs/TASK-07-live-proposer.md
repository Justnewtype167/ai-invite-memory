# TASK-07 · 接本地模型（M5 第二步）

> 路线：`docs/M5-ROUTE.md`（A 提案即证据 + B 规则提交）。
> 目标：把 `qwen3.5:9b` 接到 `self.style` 与 `self.conduct` 两个面上，**但不让核心库碰网络**。
> 写前已过 `docs/SPEC-CHECKLIST.md` 十问。

## 0. 这一步只证明一件事

```
本地模型能产出可用提案；提案进证据；人格由此变化；
而核心库仍然是零依赖、零网络、测试不联网。
```

不做：PCS 度量、多模型对比、流式输出、模型微调。

---

## 1. 冻结例外

| 可改 | 不可改 |
|---|---|
| `jian/event.py`（`proposal` 增加 4 个可选字段） | `jian/capsule.py`、`jian/cli.py` |
| `jian_kernel/*` | `jian_cn/`、`jian_recall/` 全部 |
| `tools/proposer_*.py`（新增） | 事件哈希算法、canonical 规则 |
| `tests/` 新增 | —— |

---

## 2. `proposal` 事件扩字段

```json
{"v":1,"type":"proposal","id":"ev_000123","ep":"seg-0001","t":"…",
 "target":"self.conduct","text":"收到负面经历时只确认，不评价情绪",
 "model":"qwen3.5:9b","prompt_sha":"a1b2c3d4",
 "quant":"Q4_K_M","weights_sha":"9f8e7d6c","temp_milli":0,"seed":42,
 "prev":"…","hash":"…"}
```

| 字段 | 必填 | 规则 |
|---|---|---|
| `model` | ✅ | 非空，≤64 字符 |
| `prompt_sha` | ✅ | 十六进制，≤64 |
| `quant` | 可选 | 如 `Q4_K_M`，≤32 |
| `weights_sha` | 可选 | 十六进制，≤64 |
| `temp_milli` | 可选 | **整数 0–2000**（即温度 ×1000，禁 float） |
| `seed` | 可选 | 整数，0 ≤ seed < 2^31 |

**为什么用 `temp_milli` 而不是 `temperature`**：全链路禁 float。1000 = 1.0。

### 2.1 target 白名单（本轮扩到两个）

```
self.style      → self.md 的「说话风格」小节
self.conduct    → self.md 的「行为准则」小节
```

**canon 仍然只能由 `directive` 事件改。** 提案永远碰不到 canon / state / graph。

---

## 3. 证据阈值（实测逼出来的）

```
可提案的最小证据量 = 10 条 turn/feedback 事件
不足 → record_proposal 直接抛 E_KN_THIN_EVIDENCE，提案不进证据层
```

**为什么**：实测用「在吗 / 在」一轮对话，模型会推出「禁止使用任何修饰性词语」——
一句话定义整个人格。这种提案一旦进证据，就会永久污染 kid。

---

## 4. 外部提案器协议（核心库不碰网络）

```
核心库                             外部进程
  subprocess.run([cmd], stdin=PIPE, stdout=PIPE)
  → 写一行 JSON 请求
  ← 读一行 JSON 响应
```

**请求**：

```json
{"target":"self.conduct","evidence":"[…对话摘要…]","prompt_sha":"a1b2c3d4"}
```

**响应**：

```json
{"ok":true,"text":"收到负面经历时只确认，不评价情绪","model":"qwen3.5:9b",
 "quant":"Q4_K_M","weights_sha":"9f8e7d6c","temp_milli":0,"seed":42}
```

失败响应：`{"ok":false,"code":"E_PROPOSER_FAILED","message":"…"}`

### 4.1 参考实现 `tools/proposer_ollama.py`

- 只用 stdlib（`urllib.request`）
- 读 stdin 一行 → 调 `http://127.0.0.1:11434/api/generate` → 打 stdout 一行
- **必须 `"think": false`**（实测：否则输出全进 thinking，`response` 为空）
- 超时 180s；失败按上面格式返回 ok=false

### 4.2 核心侧

```python
class SubprocessProposer:
    def __init__(self, command: list[str], timeout: int = 200): ...
    def propose(self, target: str, evidence: str, prompt_sha: str) -> Proposal: ...
```

`compile --proposer-cmd "python tools/proposer_ollama.py"` 触发实时提案。

---

## 5. Prompt 模板（写死，改动即 prompt_sha 变）

```
你在帮一个 AI 伙伴修订「{style|conduct}」。根据下面这段真实对话，写一条具体、可执行的要求。
要求：
- 不超过 40 个字
- 不许用形容词堆砌（温柔、体贴、善解人意这类一律不许）
- 要写成行为规则，能照着判断「做到了没有」
- 只输出这一条，不要解释

对话：
{evidence}
```

`prompt_sha = sha256(模板原文 + target)[:16]`。

---

## 6. `META` 还要多记两项

```
proposals: {"accepted": N, "rejected": M}
models:    ["qwen3.5:9b/Q4_K_M/9f8e7d6c", ...]   ← 参与过的模型，升序去重
```

`models` 进 META ⇒ 进 kid。**同一份证据、换一个模型出提案，kid 必然不同**——这正是要的。

---

## 7. 验收（六个，全绿 0 skipped）

| # | 测试 | 断言 |
|---|---|---|
| Q1 | `test_kn_proposal_fields` | 四个新字段写入/读回/校验；`temp_milli` 越界、`seed` 负数、`quant` 超长 → `E_SCHEMA`；带 `temperature`（float 字段名）→ 拒绝 |
| Q2 | `test_kn_two_targets` | `self.style` 与 `self.conduct` 分别写入 → 两段独立出现在 `self.md`；两者 kid 不同 |
| Q3 | `test_kn_thin_evidence` | 9 条事件 → `record_proposal` 抛 `E_KN_THIN_EVIDENCE`；10 条 → 成功 |
| Q4 | `test_kn_subprocess_proposer` | 用**假提案器脚本**（固定输出）跑 `SubprocessProposer`：成功/失败/超时三条路径；**全程不联网** |
| Q5 | `test_kn_models_in_meta` | 两个不同 model 的提案 → `META.models` 有两条且升序；`kid` 与单模型时不同 |
| Q6 | `test_all_regression` | 现有 **163 个测试仍全绿**；`jian_cn/`、`jian_recall/` 零 diff |

---

## 8. 禁止

1. 不许在 `jian_kernel/` 里 `import urllib`、`socket`、`requests`（网络只允许出现在 `tools/`）
2. 不许测试里调真模型（只用假提案器脚本）
3. 不许让提案影响 `canon` / `state` / `graph`
4. 不许用 float 存温度
5. 不许跳过证据阈值

---

## 9. 完成定义

```
python -m unittest discover -s tests -v      # 全绿、0 skipped
python tools/proposer_ollama.py < request.json   # 手工跑通一次真实提案
```

并附一段**真机记录**：

```
同一 store，三个状态：
  无提案                       → kid=A  origin=rule_only
  qwen3.5 产 1 条 conduct      → kid=B  origin=with_proposals  models=[qwen3.5:9b/Q4_K_M/…]
  删掉那条提案                 → kid 必须回到 A
```

**第三行仍然是全部意义所在。**

