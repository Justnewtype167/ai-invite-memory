# M1 验收报告（独立复核）

> 验收人：外部复核脚本（**没有复用项目自带的测试**）

---

## 7. 第二轮验收（整改复验）

> 时间：2026-10-29 稍后。结论：**M1 通过，可封版。**

**23 项独立检查，0 项失败。**（其中 1 项是复核脚本的误报：`.gitignore` 里新增了 `!docs/demo/memory.aiem`，我的检查用子串 `docs/demo` 判断，误判为仍被忽略。实际未被忽略。）

### 五项整改的落实

| # | 要求 | 实测 | 结论 |
|---|---|---|---|
| 1 | 不压行数 | 1279 行；`capsule.py` 664 行（<700 拆分线） | 合规 |
| 2 | T7 不测 SLO | 断言 `assertLess(elapsed, 2.0)`；新增 `tools/bench.py` 只报告 | 合规 |
| 3 | append 删旧 manifest | seal 后 append → `manifest.json` 消失，verify 报 `state=unsealed` | 合规 |
| 4 | 规范字节强校验 | `\/` 与 CRLF 双双报 `E_NOT_CANONICAL`，带 `event=ev_000001`；新增 2 个测试 | 合规 |
| 5 | demo 入库 | `.gitignore` 改为 `*.aiem` + `!docs/demo/memory.aiem` | 合规 |

### 关键实测数据

```
31 tests, OK, 0 skipped
10,000 事件：seal 126.5ms / verify 121.6ms   （目标 <200ms）
真实流程 import→append→verify→seal→export 全通
```

### 错误信息质量（这一轮最明显的变化）

```
撕封：FAIL E_HEADER_MISMATCH manifest 存在但缺少 chain.json，请执行 seal 修复
字节：FAIL E_NOT_CANONICAL 事件 ev_000001 不是规范字节 [event=ev_000001]
```

两条都做到了「说清是什么 + 说清怎么办 + 能定位到具体事件」。

### 封版前唯一没做的事

仓库还没有 `git init`。**M1 的代码只在本地文件系统里，没有历史。**
下一步：`git init` → 首次提交 → 打 tag `v0.1-m1`。

