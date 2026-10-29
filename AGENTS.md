# AGENTS.md — 竹简 / Jian

## 0. 这个项目是什么

面向 AI 伴侣的**本地记忆内核与人格层**。核心命题一句话：
**人格不活在权重里，活在可重算的产物 + 可验证的测试里。**

交付物是「格式 + 参考实现 + 一致性套件 + 论文」，不是聊天产品。

## 1. 当前阶段：M4（人格内核与漂移门控）

**三个已封版模块**：`jian/`（v0.1-m1）、`jian_cn/`（v0.2-m2）、`jian_recall/`（v0.3-m3），共 104 个测试。
**这三个包从此冻结**：M4 不许改动其中任何一行。

M4 只做：`jian_kernel/` —— 确定性编译 / 漂移门控 / 历史与回滚 / 全量溯源。
规格见 `docs/TASK-04-kernel.md`。**写之前先过一遍 `docs/SPEC-CHECKLIST.md` 的十问。**

**M4 不接模型**：只实现 Proposer 协议与 `NullProposer`。LLM 提案留到 M5。

M4 的唯一目标：**同一份证据，无论今天编译、明天编译、删掉重编译，得到的是同一个人格，一个字节都不差。**
越界视为任务失败，即使代码能跑。

## 2. 十二条不可协商约束

| # | 约束 | 违反的后果 |
|---|---|---|
| C1 | **证据不可变**：已封存的事件永不改写、永不删除 | 整个项目的前提塌掉 |
| C2 | **单向派生**：任何上层产物只能从证据层派生，禁止上层→上层 | 记忆会逐代腐坏 |
| C3 | **canonical JSON**：RFC 8785 子集，自己实现，禁止依赖库 | 字节可复现不成立 |
| C4 | **容器字节可复现**：zip 时间戳归零、条目顺序固定、STORE 不压缩 | 无法做完整性校验 |
| C5 | **索引可丢弃**：M1 阶段不写任何索引；将来索引必须能纯靠证据重建 | 违背「只留证据能复活」 |
| C6 | **纯标准库**：Python 3.11+，**零第三方依赖**，测试用 unittest | 十年后还得能跑 |
| C6b | **零模型**：中文解析与检索全靠规则与数据表，不许有任何 LLM/网络调用 | 这是唯一的成本与可复现优势 |
| C6c | **索引可丢弃**：`.index/` 是派生物，删掉必须能完全重建 | 「只留证据能复活」的下半句 |
| C7 | 源码 ASCII；中文只出现在数据、文档、错误信息里 | Windows 控制台乱码 |
| C8 | 全部函数带类型注解；数据用 dataclass，不用裸 dict 传参 | 可维护性 |
| C9 | 错误码固定为 E_* 常量，不许临时编 | 测试要断言错误码 |
| C10 | 进程内无网络、无 LLM 调用、无未播种随机 | 可复现 |
| C11 | 每个公开函数：docstring + 至少一个测试 | 没有测试等于没写 |
| C12 | 对规范有疑问就停下写问题，不许自己改语义 | 语义漂移无法回收 |

## 3. 目录结构（严格按此，不许自创）

```
D:/projects/Memory/
  AGENTS.md
  README.md
  pyproject.toml
  jian/
    __init__.py
    canonical.py      # C3 canonical JSON
    errors.py         # C9 错误码
    event.py          # 事件模型与校验
    chain.py          # 哈希链
    capsule.py        # 容器打包/解包/校验
    cli.py            # 7 个命令
  tests/
    test_canonical.py
    test_chain.py
    test_capsule.py
    test_cli.py
  docs/
    TASK-01-capsule.md   # 本任务规格（唯一权威）
    SPEC-CONSTRAINTS.md  # 长期约束（不要改）
  corpus/                # 合成人格库（不要改）
  tools/build_corpus.py  # 语料生成器（不要改）
```

## 4. 代码风格

- 行宽 100，用 4 空格缩进，不做花哨单行技巧
- 公开 API 只暴露必要函数，其余以 `_` 前缀
- 时间：只接受带时区的 ISO 8601 字符串，内部一律存 UTC 字符串
- 不打印调试输出；CLI 才 print
- 异常只抛自定义 `JianError(code, message)`

## 5. 禁止事项（出现任意一条即任务失败）

1. `TODO` / `pass` / `NotImplementedError` 占位
2. 测试被 `skip` 或断言被弱化
3. 自己降低 `docs/TASK-01-capsule.md` 里的验收标准
4. 引入任何第三方依赖（包括 pytest）
5. 写营销式 README、写「未来将支持」
6. 越过 M1 范围（检索、摘要、LLM、中文解析、MCP）
7. 把被测核心逻辑 mock 掉
8. 一次提交超过 800 行（拆成两次）
9. 让任何单个源文件超过 700 行而不拆分

## 6. 完成定义（DoD）

```
python -m unittest discover -s tests -v
```

必须满足：**8 个验收测试全绿，0 skipped，0 errors**，且：

- `python -m jian.cli --help` 能列出 7 个命令（命令是 7 个，测试是 8 个，别混）
- 存在一个 `docs/demo/` 目录，含一次真实的 init→append→seal→verify→export→import 输出记录
- 源码总行数 ≤ 1400 行（不含测试与文档）；**任何单个文件 > 700 行必须拆分**

## 7. 汇报格式（每次结束必须按此格式）

```
RUN:    我实际执行了什么命令
CHANGED: 改了/新建了哪些文件（逐行列出）
TEST:   unittest 输出摘要（X passed / Y failed / Z skipped）
OPEN:   不确定的地方、与规范冲突的地方、我没做的事
```

**不许在 TEST 里写「应该通过」。必须贴真实输出。**


## 8. 字节资产纪律（血换来的）

1. **`.gitattributes` 必须在第一次提交里**：`* text=auto eol=lf`、`*.jsonl text eol=lf`、`*.aiem binary`
2. **本地验过不算数**：任何影响字节的改动，必须在 `git clone` 出的干净目录里复验 `verify`
3. Windows 上 `core.autocrlf` 默认可能是 true —— 属性文件是唯一可携带的保护
4. 不要用 `git add --renormalize` 来「顺便加入新文件」，它只重规范化已跟踪的文件

