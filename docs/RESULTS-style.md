# RESULTS-style · 四组对照（M16 / Task 7）

> 规格：`docs/TASK-21-traits-style.md` §6。
> **结论先行：本地模型不可用，四组对照未测量。**
> 唯一可报告的真实数字是四组 prompt 的装配成本（dry-run）。本文件不含任何编造的
> `C` / `A` / `PCS` / 事实命中率。

---

## 1. 环境实测

```
ollama.exe    C:\Users\justn\AppData\Local\Programs\Ollama\ollama.exe   （存在）
模型目录      %USERPROFILE%\.ollama\models                             （不存在）
服务端口      127.0.0.1:11434                                          （连接被拒绝）
```

`--dry-run` 之外的第一次真实调用即失败，脚本按设计非零退出，未打印任何数字：

```
$ python tools/style_experiment.py --group A B C D --models qwen3.5:9b glm4:9b
E_STYLE_EXPERIMENT: <urlopen error [WinError 10061] 由于目标计算机积极拒绝，无法连接。>
EXIT=2
```

**没有模型，就没有数字。** 报告里不会出现「预计」「参考量级」之类的替代值。

## 2. dry-run：四组 prompt 的真实装配成本

命令：

```
python tools/style_experiment.py --group A B C D --dry-run
```

真实输出（连跑两次逐字相同）：

```
A prompt_chars=129 prompt_tokens=124
B prompt_chars=162 prompt_tokens=147
C prompt_chars=283 prompt_tokens=213
D prompt_chars=388 prompt_tokens=297
probes=80 facts=30 groups=4 store=C:\Users\justn\AppData\Local\Temp\jian_style_exp_bf3h7xv2\style_store
```

说明两点，避免误读：

1. 这里的 `chars` / `tokens` **只是 system prompt**（规则 6 条 + 人格段），
   不含探针原文与模型回复；`tokens/轮` 的真实值一定大于此数。
2. 探针是 `load_all_probes()` 的 80 条（base 30 + more 30 + real 20），
   与 V5 的 PCS=0.649 同一集合；事实是 `jian_persona/data/facts.jsonl` 的 30 条。

## 3. 四组表

| 组 | C(qwen) | C(glm) | A | PCS | 事实命中率 | tokens/轮 | 复读率 |
|---|---|---|---|---|---|---|---|
| A | 0.863（引自 V5） | 0.838（引自 V5） | 0.775（引自 V5） | **0.649（引自 V5）** | 未测量 | ≥124（仅 system） | 未测量 |
| B | 未测量 | 未测量 | 未测量 | 未测量 | 未测量 | ≥147（仅 system） | 未测量 |
| C | 未测量 | 未测量 | 未测量 | 未测量 | 未测量 | ≥213（仅 system） | 未测量 |
| D | 未测量 | 未测量 | 未测量 | 未测量 | 未测量 | ≥297（仅 system） | 未测量 |

A 行数字来自 `docs/ACCEPT-M8.3.md` / `docs/RESULTS-cross-model-v2.md`
（80 条探针、qwen3.5:9b 与 glm4:9b、temp=0、seed=42，95% CI [0.522, 0.754]）。
**它不是本轮重测的结果**，只作为可比基线引用。

## 4. 判据（写死，不因未测量而放宽）

```
有效 ⇔ ΔPCS > 0.13 或 Δ事实命中率 > 0.15
```

且现有 PCS 的 95% CI 宽 0.232：小于它的提升本来就不能宣称。
未测量 ⇒ 本轮**不能宣称任何组有效**，包括 B/C/D 的负结果也不成立——
没有观测，就没有结论。

## 5. 两句结论

1. **锚定（B、C）把 PCS 提高了多少？** 未测量。因此 0.649 仍是当前唯一可引用的
   行为身份分，不能因为加了特质与风格卡就说它变好了。
2. **用户卡（D）把事实命中率提高了多少？** 未测量。唯一可确认的代价是
   D 的 system prompt 每轮比 A 多 `297 - 124 = 173` tokens（约 2.4 倍），
   而 `pin_user_card` 的 400 字符预算（见 `test_user_card_budget_and_pin`）
   保证卡片不会被检索挤掉。

**负结果也是结果，但这里是「未测量」，不是负结果。** 两者不能混写。

## 6. 复现步骤（模型就绪后）

```
ollama serve
ollama pull qwen3.5:9b
ollama pull glm4:9b
python tools/style_experiment.py --group A B C D --dry-run          # 先确认四组 prompt 已装配
python tools/style_experiment.py --group A B C D --models qwen3.5:9b glm4:9b
```

跑通后把真实四行替换上表，并在本文件顶部改掉「未测量」的结论。
在此之前，任何引用本文件的文字都只能引用 §2 的装配成本与 §5 的「未测量」。
