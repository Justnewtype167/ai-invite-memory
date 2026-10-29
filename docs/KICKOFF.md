# KICKOFF · 给编码代理的开场指令

把下面这段整段粘进 Trae（或任何编码代理）。

---

```text
你在 D:/projects/Memory 这个仓库里工作。

第一步，先完整读这三个文件，读完再动手，不要先写代码：
1. docs/TASK-01-capsule.md   ← 唯一权威规格
2. AGENTS.md                  ← 约束与禁止事项
3. docs/SPEC-CONSTRAINTS.md   ← 长期约束（本次用不到，但不要违背）

任务：实现 M1「容器与信任根」。只做这一件事，不要扩展范围。

硬性要求：
- Python 3.11+，零第三方依赖，测试用 unittest（不要用 pytest）
- 严格按 TASK-01 的目录结构与七个验收测试实现
- 每个公开函数：类型注解 + docstring + 测试
- 不许 TODO / pass 占位，不许 skip 测试，不许改验收标准
- 规格有歧义就停下来问我，不要自己决定语义

完成的标准是这条命令的输出，七个测试全绿、0 skipped：
python -m unittest discover -s tests -v

做完后按这个格式汇报，TEST 部分必须贴真实输出，不许写“应该通过”：
RUN:     你实际执行了什么命令
CHANGED: 新建/修改了哪些文件
TEST:    测试输出摘要
OPEN:    不确定的地方、没做的事
```

---

## 建议的推进节奏（每轮一个，别一次给太多）

| 轮次 | 你让它做 | 预期产出 |
|---|---|---|
| 1 | canonical.py + errors.py + T1/T2 | 两个测试绿 |
| 2 | event.py + chain.py + T3 | 第三个绿 |
| 3 | capsule.py + T6/T7 | 导出导入可复现 |
| 4 | cli.py + T4/T5 + demo 记录 | 七个全绿 |

**每轮结束先看 TEST 是不是真输出，再给下一轮。**

