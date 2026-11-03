# M5 第二步验收（核心通过；一处必须降级）

> 对象：`aiinvite/event.py` + `aiinvite.kernel/*` + `tools/proposer_ollama.py` + 5 个新测试
> 结论：**真机三行证明成立。但 8GB 显卡上的间歇 OOM 会让整次编译失败，必须降级。**

---

## 1. 测试

```
Ran 175 tests, OK, 0 skipped        （163 + 12）
```

## 2. 真机三行证明（最重要的一条）

用本地 `qwen3.5:9b` 实跑：

```
A 无提案        kid=b3ff34e0ab11  origin=rule_only
真模型 1.3s      text=「当用户分享困难或疲惫时，AI 需明确记录并承诺具体支持行动。」
B 有提案        kid=f1ade839c331  origin=with_proposals  models=('qwen3.5:9b/Q4_K_M',)
C 同证据无提案  kid=b3ff34e0ab11  origin=rule_only

A == C ? True          ← 提案走了，人格回到原样
A != B ? True          ← 提案在，人格变了
conduct 入 self.md ? True
```

**这是整个项目第一次由真模型参与人格，而身份仍然可验证。**

## 3. 我独立复现的其余项

| 项 | 断言 | 实测 |
|---|---|---|
| Q3 | 9 条证据 → 拒绝 | `E_KN_THIN_EVIDENCE`（阈值 10） |
| Q3 | 10 条 → 通过 | 通过 |
| Q2 | 两个 target 互不污染 | A 只有 `## Style`、B 只有 `## Conduct` |
| Q2 | 两者 kid 不同 | `3e48b0bb…` / `fca058d4…` |
| Q5 | 两个模型 → models 两条且升序 | `('gpt-5/api/bbbb', 'qwen3.5:9b/Q4_K_M/aaaa')` |
| Q4 | 假提案器成功/失败/超时 | 三条路径全部正确抛 `E_PROPOSER_FAILED` |
| Q4 | 测试不联网 | 全程 subprocess + 假脚本 |

## 4. 两处规格偏差（都是我写错）

### 4.1 错误码：`E_KN_BAD_PROPOSAL` 而不是 `E_SCHEMA`

规格 Q1 写的是字段越界报 `E_SCHEMA`，实现报 `E_KN_BAD_PROPOSAL`。

**实现更对。** 两者的分工应该是：

```
E_SCHEMA              事件结构错（缺 type / id / 字段集不对）
E_KN_BAD_PROPOSAL     业务字段非法（temp_milli 越界、seed 负数、quant 超长）
```

已按实现修正规格。

### 4.2 `self.md` 的标题是英文

```
## Style
## Conduct
```

`self.md` 是喂给人看、将来贴进提示词的中文人格叙事，标题却是英文。
不影响功能，但读起来别扭。**低优先级，记在待办。**

## 5. 阻塞级发现：8GB 卡上的间歇 OOM 会打死编译

实测（RTX 2070 Super 8GB + 6.55GB 模型）：

```
第一次发请求    HTTP 500  CUDA out of memory / std::bad_alloc
模型加载后又发   1.0s 正常
3 次连跑        3/3 成功，且输出逐字相同（temp 0 + seed 42）
```

**OOM 不是稳定的，是加载态的偶发失败。**

问题在于当前行为：

```
提案器失败 → SubprocessProposer 抛 E_PROPOSER_FAILED → compile 整个失败
```

**一次 OOM 就把人格编译打死**，而这是消费级显卡上的常态。

对一个「本地优先、十年可用」的系统，这是设计错误：
**提案必须是可选增强，不能是必经路径。**

### 建议改法

```
compile 默认：捕获提案器失败 → 降级为规则，origin=rule_fallback，proposals.failed += 1
compile --strict-proposals：才硬失败（CI 与调试用）
```

降级后 kid 会变（origin 进 kid），所以**不会静默等价**——这正好复用了 M5 第一步的机制。

### 顺带记两条运行建议（写进 adapter 文档）

```
num_ctx 固定 2048、num_predict ≤ 200、keep_alive 设长（避免重载）
```

我实测 `num_ctx 4096` 更容易 OOM。

## 6. 待办

| 级别 | 项 |
|---|---|
| 必修 | 提案器失败降级 + `--strict-proposals` |
| 必修 | 提交并打 tag `v0.7-m5` |
| 建议 | `self.md` 标题改中文 |
| 建议 | adapter 写死 num_ctx / num_predict |


---

# M5 第二步终验（功能全过，但测试在本机不是全绿）

> 复核 tag `v0.7-m5`（`f94aaca`），工作区干净。
> **结论：降级机制完全正确，但 180 个测试里有 1 个在本机报错——tag 需要重打。**

## 1. 降级机制：5 项全对

| 项 | 断言 | 实测 |
|---|---|---|
| `ingest_live` 失败 | 不抛，计失败数 | `failed=2 recorded=0 errors=2` |
| `strict=True` | 抛 `E_PROPOSER_FAILED` | 正确 |
| `force_fallback` | `origin=rule_fallback` | 正确 |
| 成功路径 | `origin=with_proposals` | `models=('fake',)` |
| **CLI 端到端** | 失败的提案器下 **exit 0** 且降级 | `rc=0`，stderr 打 `proposer fallback:` |

**设计比我写的规格更好**：我把 try/except 写进了 `compile_kernel`，实现把它放在了 `ingest_live`（进程边界），
`compile_kernel` 保持纯函数。这才是对的——**容错属于边界，不属于纯函数**。已按实现修正规格。

## 2. `META` 干净

```
keys: compiler_version / generation / head / kid / models / origin / policy_hash / proposals / version
含 failed ? False      ← 按约定，失败计数只进 RecordResult 与日志
```

## 3. 阻塞项：`test_cli_downgrades_by_default` 报错

```
Ran 180 tests
FAILED (errors=1)
  test_cli_downgrades_by_default → UnicodeDecodeError: 'gbk' codec can't decode byte 0xa1
```

**根因**：`tests/test_kn_live_fallback.py:122` 用 `subprocess.run(..., text=True)` 但没指定 `encoding`，
Windows 默认按 GBK 解码，而子进程输出的是 UTF-8 中文（`proposer fallback: …外部提案器无法启动…`）。

**讽刺之处**：崩的正是刚做好的降级路径——因为它第一次在 stderr 上输出中文。

### 修法

```python
subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
              encoding="utf-8", errors="replace", timeout=120,
              env={**os.environ, "PYTHONUTF8": "1"})
```

同样要改 `tests/test_kn_proposal_determinism.py:55`——它现在能过，只因为子进程只打印 ASCII 的 kid。

### 该记进规则的一条

> **Windows 上，凡是起子进程并读输出，一律显式 `encoding="utf-8"`，并给子进程 `PYTHONUTF8=1`。**
>
> 这条不改，以后每加一个带中文 stderr 的子进程都会踩一次。

## 4. 其余待办（不阻塞）

| 项 | 状态 |
|---|---|
| adapter 加固（num_ctx 2048 / num_predict 200 / keep_alive 1h） | ✅ 已做 |
| `self.md` 标题中文 | ⬜ 仍是 `## Style` / `## Conduct` |

## 5. 结论

功能层面 M5 第二步成立，而且真机三行证明已经跑过。
但 **tag `v0.7-m5` 是在一个本机会红的测试树上打的**，必须修完重打。


---

# M5 第二步终验（通过，v0.7-m5 重打）

> tag `v0.7-m5` → `8856b36`（重打后指向修复提交），工作区干净。
> **180 测试全绿，干净克隆复验通过。**

## 1. 编码修复已落实

```
tests/test_kn_live_fallback.py:125   encoding="utf-8", errors="replace"
tests/test_kn_live_fallback.py:126   env={**os.environ, "PYTHONUTF8": "1"}
tests/test_kn_proposal_determinism.py:55  env["PYTHONUTF8"] = "1"
tests/test_kn_proposal_determinism.py:59  encoding="utf-8", errors="replace"
```

并升格为约束 **C13**（AGENTS.md:48）：

> Windows 上凡是起子进程并读输出，一律显式 `encoding="utf-8"` + `errors="replace"`，并给子进程设 `PYTHONUTF8=1`

## 2. 复验结果

```
本机     Ran 180 tests, OK, 0 skipped
干净克隆 tag v0.7-m5 · Ran 180 tests, OK
         M1 verify OK head=61a5d726
         M4 CLI compile/propose/record/history/verify/diff
```

## 3. M5 两步的完整结论

| 能力 | 状态 |
|---|---|
| 提案进证据（第 6 种事件） | ✅ |
| 三态 origin，且进 kid | ✅ |
| 提案在→kid 变，提案走→kid 回来 | ✅ 真机验证 |
| 提案随胶囊搬家，设备 B 重算一致 | ✅ |
| 本地模型真机接入（qwen3.5:9b） | ✅ 1.3s/条 |
| 两个作用面（style / conduct）互不污染 | ✅ |
| 证据不足 → 拒绝（阈值 10） | ✅ |
| 提案器失败 → 降级不打死编译 | ✅ CLI rc=0 |
| 核心库零依赖零网络 | ✅ 网络只在 tools/ |

## 4. 下一步

```
⬜ PCS：换模型后「像不像同一个人」的度量
⬜ 继承与哀悼协议（M6）
⬜ self.md 标题中文化（低优先级）
```

