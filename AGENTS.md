# AGENTS.md — AI Invite · Memory（爱邀记忆内核）

## 0. 这个项目是什么

> **先读 [`docs/CHARTER.md`](docs/CHARTER.md)。那是宪法，这是实现说明。**

面向 AI 伴侣的**本地记忆内核与人格层**。核心命题一句话：
**人格不活在权重里，活在可重算的产物 + 可验证的测试里。**

交付物是「格式 + 参考实现 + 一致性套件 + 论文」，不是聊天产品。

**优先级（宪章 §3）**：先活着的人的路径，再死后的遗产路径。
→ `M15.1 / 协议 V7` 暂缓，设计存档于 `docs/PROTOCOL-V7.md`。

## 1. 当前阶段：M36 已封（每轮只处理新增），下一步是接爱邀阶段一

**已封版**：`v0.1-m1` … `v0.41-m36`，共 **44 个 tag、486 个测试**。

```
M1-M5    证据层 / 中文规则 / 检索装配 / 人格内核 / 提案即证据
M6-M9    行为身份 PCS / 多轮坍塌 / 规则可执行化与判定器效度 / 咨询模式
M10      载荷与信封：事件改为「信封 + 内容寻址载荷」
M11      轨迹与双投影：同一 kid 驱动文字与动作，身份不变
M12      增量编译 + 对账：增量结果与全量逐字节相同
M13-M14  动作闸门（refusal 进证据）/ 会话级等价装配 + 分块输出
M14.1    时间触发增量化
M15      遗赠胶囊（**设计已被 V7 取代，实现待重写**）
M16-M19  特质词表与风格卡 / 宿主接入层 / 命名空间合并与首次 PyPI 发布 / 演示窗口
M20-M24  桌面构建与打包守卫 / canon 规则与闸门 / 称呼修复与 98× 编译提速 / 段级证据缓存 / 用户卡逐事件 memo
M25-M30  不可遗忘层（pin）/ 同义词与单字索引 / 查询改写兜底 / 盲重写被实验推翻 / 有依据的线索 / 线索缓存
M31-M35  桥接普及度闸门 / 线索改固定清单分类 / 活库快照 / 召回失败收集 / 用户卡增量折叠
M36      每轮只处理新增：索引与证据按字节偏移续读、快照 graph 旁置、一次 prompt 一次读取
M15.1    继承模式 V2（暂缓，见 docs/PROTOCOL-V7.md）
```

**下一步是接爱邀阶段一**（只接用户卡，不接闸门与 kid；时间由用户定）。
每轮成本的现状与上限见 `docs/TASK-25-turn-cost.md` §6–§7：20k 每轮 0.67 s，200k 3.1–3.5 s，
剩下的是 `kid` 对全量 graph 的哈希（约 2 s），要消掉必须改身份语义，属产品决策。动手前必读：

```
docs/SPEC-CHECKLIST.md      十问自检
docs/FOUNDATION-INVARIANCE.md  地基不变量（为什么做 M13）
docs/AUDIT-01.md            全项目重新验证的结论与已知缺口
```

### 1.1 冻结政策（M18 重命名后统一为字节基线）

```
范围：aiinvite/** 下每个 .py 的 sha256 都在基线里 —— 新增、删除、改一个字节都会失败
改动：先在 tests/test_all_regression.py 的 ALLOWED_CHANGES 里逐文件声明原因，再同步基线
首次发布之后的每一次改动都走过这条闸门；基线按 git index 字节重算（不是工作区字节）
```

**闸门是 `tests/test_all_regression.py` 的 `ALLOWED_CHANGES`**：
改了没声明 → 失败；声明了没改 → 也失败。


## 1.1 本机模型与工具

```
qwen3.5:9b   Q4_K_M  6.55 GB   已有（提案与 PCS 基线）
glm4:9b      下载中     ~5.5 GB   跨族对照
tools/proposer_ollama.py    支持 --model / --quant（本轮补的）
tools/responder_ollama.py   支持 --model
```

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
| C13 | **Windows 子进程编码**：凡是起子进程并读输出，一律显式 `encoding="utf-8"` + `errors="replace"`，并给子进程设 `PYTHONUTF8=1` | 默认 GBK 解码 UTF-8 中文直接 UnicodeDecodeError |
| C14 | **绝对时延不进单测门禁**：单测只断言「不随规模劣化的相对属性」与「宽松健全性上限」；SLO 数字由 `tools/bench_*.py` 报告，永不作为单测断言 | 并发跑测试必然假红（已发生两次：M3 的 80ms、M9 的 200ms） |

## 3. 目录结构（严格按此，不许自创）

```
D:/projects/Memory/
  AGENTS.md            # 本文件：约束与当前阶段
  README.md            # 中文首页    README-en.md 英文首页
  LICENSE              # Apache-2.0
  CHANGELOG.md         # 版本变更（v0.24.1–v0.40 已回溯补记）
  pyproject.toml
  aiinvite/                # L0 证据层：容器、哈希链、载荷 blob
    canonical.py  errors.py  event.py  chain.py  capsule.py  cli.py
    cn/                # 中文规则层：称谓、相对时间、梗时效、繁简
    recall/            # 检索与预算装配：FTS5 + 二元切分 + 4k 上限
    kernel/            # L1 人格内核：编译、门控、历史、提案、快照与增量
    pcs/               # 行为身份：PCS、可执行规则、坍塌深度
    projection/        # L2 投影层：轨迹契约、文本投影器、动作投影器
    persona/           # L2 用户卡 / 特质 / 风格卡 / pin（card_fold 为增量折叠）
    host/              # 宿主接入层：一个类、八个方法（唯一允许组合各层的包）
    demo/              # 最小可信演示（tkinter，零第三方依赖）
    succession/        # 遗赠胶囊（V1；V7 设计见 docs/PROTOCOL-V7.md）
  tests/               # 486 个测试（unittest，无第三方依赖）
  tools/               # 唯一允许联网/调模型的地方
  corpus/              # 合成人格库（不要改）
  experiments/         # 回复集与矩阵结果
  docs/                # 规格 / 验收 / 结果 / 论文 / 审计
    TASK-01..24-*.md   # 每个里程碑的权威规格
    ACCEPT-M*.md       # 每个里程碑的验收记录（含独立复核）
    AUDIT-01.md        # 全项目重新验证
    SPEC-CHECKLIST.md  # 写规格前的十问
    PAPER.md / PAPER-en.md
```

## 4. 代码风格

- 行宽 100，用 4 空格缩进，不做花哨单行技巧
- 公开 API 只暴露必要函数，其余以 `_` 前缀
- 时间：只接受带时区的 ISO 8601 字符串，内部一律存 UTC 字符串
- 不打印调试输出；CLI 才 print
- 异常只抛自定义 `AiInviteError(code, message)`

## 5. 禁止事项（出现任意一条即任务失败）

1. `TODO` / `pass` / `NotImplementedError` 占位
2. 测试被 `skip` 或断言被弱化
3. 自己降低 `docs/TASK-01-capsule.md` 里的验收标准
4. 引入任何第三方依赖（包括 pytest）
5. 写营销式 README、写「未来将支持」
6. 越过当前里程碑范围（见 §1；M13 之前不许碰真实设备驱动）
7. 把被测核心逻辑 mock 掉
8. 一次提交超过 800 行（拆成两次）
9. 让任何单个源文件超过 700 行而不拆分

## 6. 完成定义（DoD）

```
python -m unittest discover -s tests -v
```

必须满足：**全量 486 个测试全绿，0 skipped，0 errors**（当前基线），且：

- 冻结包的改动必须在 `tests/test_all_regression.py` 的 `ALLOWED_CHANGES` 声明（改了没声明失败，声明了没改也失败）
- 存在一个 `docs/demo/` 目录，含一次真实的 init→append→seal→verify→export→import 输出记录
- 任何单个文件 > 700 行必须拆分

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

