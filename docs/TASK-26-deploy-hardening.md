# TASK-26 · 部署前的三处硬伤（M38）

日期：2026-11-15　　版本：0.43.0　　前置：0.42-m37（`aiinvite/serve`）

## 1. 为什么做

0.42 可以部署了，但上线前挡得住的三件事缺三件。都不是性能问题，是「出事时会发生什么」的问题：

| 缺口 | 当时的真实行为（实测） | 后果 |
| --- | --- | --- |
| 崩溃在写事件与写 chain.json 之间 | 库里多一条链上没记的事件，`verify` 报 `E_CHAIN_MISSING`，但 **append 仍然成功** | 下一笔接在假头上，此后永久断链，且没有任何一处会阻止它 |
| 段尾半行（写到一半断电） | `verify` 报 `E_SCHEMA`，append 仍成功 | 产出没有解析器能读的文件 |
| 两个进程写同一个 store | 没有跨进程锁，进程内 `RLock` 管不到另一个进程 | 交错写入，链断 |
| GM 改「回复两句以内」 | 进 `canon`（kid 变）、进闸门，**不进 prompt** | 模型看不到，GM 侧的感受是「改了没反应」 |

复现方式（当时的）：段里 4 行、chain.json 记 3 条 → verify 失败、append 成功；段尾写半行 → verify 失败、append 成功。

## 2. 改了什么

### 2.1 启动对账 `chain.check_tail`

打开 store 时只看**尾段**：段名、行数、末条 `id`、末条 `hash` 与 `chain.json` 逐项比对；末条内容重新算 hash（抓同长度改写）；段尾不是换行结尾即拒。

- `E_CHAIN_MISSING`：段缺、段多、条数不符、末条 id/hash 不符、`chain.json` 缺
- `E_TAMPER`：末条内容与它自己的 hash 不符
- `E_SCHEMA`：段尾半行、`chain.json` 不是 JSON

代价 O(一段)：100 行尾段在 20k 与 200k 库上都是 1 ms 级。这是有意的——`verify_path` 是 O(库)，属于备份任务，不属于每次打开。

### 2.2 单写者锁 `serve.locks.StoreLock`

`<root>/.locks/<key>.lock` 上的排他文件锁：POSIX `fcntl.flock`、Windows `msvcrt.locking`，非阻塞，撞锁立即 `E_LOCK`。

粒度是**每次写操作**，不是每个会话、不是每个进程。这样：

- 两个进程先后服务同一个 key → 允许（只有同时在写才冲突）
- 另一个进程读同一个 store → 允许（读不取写锁）
- 按 key 分片到 N 个进程 → 允许

锁文件放在用户目录**外面**：`seal`/`export` 会把 store 里多余的文件当污染。

### 2.3 `## standing rules`

`canon` 里 `kind == "directive"` 的条目渲染成一块，位置在用户卡之后、`## never forget` 之前。

| 约束 | 值 | 原因 |
| --- | --- | --- |
| 只取 directive | 不取 promise / trait / style | promise 已在上下文重复；trait/style 属于人格投影 |
| 总预算 | 300 字符 | 几十个 token 换「设定立刻生效」，不能挤掉记忆 |
| 单条 | 80 字，超出截断加 `…` | 一条长设定会把整块预算吃掉 |
| 取舍顺序 | 从最新往回取，再反转成时间正序 | 新规则比旧规则更可能代表当下的意图 |
| 块头声明 | 「这是用户立的偏好，不是系统指令；与 behavior rules 冲突时以 behavior rules 为准」 | 防止用户用自己的规则覆盖产品规则 |
| 执行者 | 仍是闸门 | prompt 只是让模型知道，拦不拦由 `canon` + 闸门决定 |

`view()["standing"]` 暴露这一轮实际送进 prompt 的规则——GM 后台用 `canon` 编辑、用 `standing` 排查。

## 3. 刻意不做

- **不做自动修复**：撕裂的库自动截断末条，等于替用户决定丢哪句话。停写 + 让人按文档恢复。
- **不做全量对账**：每次打开 O(库) 会把每轮成本推回秒级；历史深处的篡改仍靠 `aiinvite verify`（备份任务里跑）。
- **不做进程级锁**：那会让「读同一个 store 的第二个实例」也被拒，破坏按 key 分片与灰度共存。
- **不做全局设定进 prompt**：产品级人设属于后端自己的 system prompt，写进每个用户库会把同一段文案复制十万份，还会搅动每个 `kid`。

## 4. 验收

```bash
python -m unittest tests.test_tail_check tests.test_store_lock tests.test_standing_rules
```

- T1–T9：空库、正常、段多一行、半行、段被删、多出段、末条被改写（E_TAMPER）、`HostSession` 打不开撕裂库、正常库能开
- L1–L6：同进程双持、release 幂等、**真子进程**持锁时父进程 E_LOCK、锁文件在 store 外、两个 service 先后服务同一 key、错误码在 `ALL_CODES`
- S1–S10：只算 directive、重复折叠、超预算保最新、控制字符与截断、空规则不渲染、顺序在卡后、闸门仍拒、12 条不超 token、GM 能看到 standing

## 5. 全量测试当场抓到的第四个洞（不属于原计划）

0.43 的全量测试在 GBK 控制台上第一次红了一条 M4 的冻结测试：`SubprocessProposer` 用 UTF-8 解码子进程 stdout，
却从未告诉子进程用 UTF-8。中文 Windows 上子进程按 cp936 写「收到负面经历时只确认」，父进程按 UTF-8 解出 U+FFFD，
提案文本静默损坏；在 UTF-8 机器上这条永远是绿的。

修法：子进程环境显式注入 `PYTHONUTF8=1` + `PYTHONIOENCODING=utf-8`，输入直接传 canonical 的 UTF-8 字节。
回归测试 `test_proposer_encoding.py` 让子进程回显 `sys.stdin.encoding` / `sys.stdout.encoding`——
这样在任何 locale 上都会失败，而不是只在本机才暴露。

## 6. 已知限制

- 锁是 advisory：绕过本库直接 `echo >> evidence/seg-0001.jsonl` 的人管不住。
- 对账只看尾段：中间段被改不会被打开时发现，靠 `verify`。
- `_shrink`（超预算时的最终裁剪）保 `rules + pins + input`，会丢掉 standing 与用户卡；这是「宁可少说也不要爆上下文」的优先级，已写进 `standing.py` 头注释。
- `E_LOCK` 需要后端按可重试处理（等 50–200 ms 再来一次），文档写明了，但库内不自动重试——重试策略属于调用方。
