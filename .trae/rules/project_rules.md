---
description: 竹简 / Jian 项目规则（记忆内核 M1）
globs:
alwaysApply: true
---

# 项目规则

这是一个**零依赖、纯标准库**的 Python 项目，交付「可携带记忆容器」。

## 必须遵守

1. 先读 `docs/TASK-01-capsule.md`（唯一权威规格）与 `AGENTS.md`，再动手。
2. 只用 Python 3.11+ 标准库，**不许引入任何第三方依赖**（包括 pytest，测试用 unittest）。
3. 只做 M1 范围：容器 + 事件 + 哈希链 + 校验 + 导出导入。
   不做索引、不做摘要、不调 LLM、不做中文解析、不做 MCP、不做 UI。
4. 每个公开函数：类型注解 + docstring + 一个测试。
5. 不许 `TODO` / `pass` / `NotImplementedError` 占位，不许 skip 测试。
6. 不许降低规格里的验收标准；规格有歧义时**停下来提问**，不要自己决定。
7. 代码 ASCII；中文只出现在文档、错误信息、测试数据里。

## 完成标准

`python -m unittest discover -s tests -v` 七个验收测试全绿、0 skipped。

## 汇报格式

```
RUN:     实际执行的命令
CHANGED: 新建/修改的文件
TEST:    真实测试输出摘要
OPEN:    不确定点、未完成项
```

