# AI Invite · Memory / 爱邀记忆内核

[![ci](https://github.com/Justnewtype167/ai-invite-memory/actions/workflows/ci.yml/badge.svg)](https://github.com/Justnewtype167/ai-invite-memory/actions/workflows/ci.yml) [![release](https://img.shields.io/github/v/tag/Justnewtype167/ai-invite-memory?label=release)](https://github.com/Justnewtype167/ai-invite-memory/releases) [![license](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

面向 AI 伴侣的**可验证、可携带的记忆内核与人格层**。

> 人格不活在权重里，而活在一份可以重算的产物 + 一组可以验证的测试里。

**当前状态**：`v0.24-m19` · 383 个测试全绿 · 27 个 tag · 0 第三方依赖

> 顺序：证据层 → 主题与规则 → 检索 → 人格内核 → 行为身份 → 载荷 → 轨迹投影 → 增量编译。（见 `AGENTS.md §1`）

论文：[中文](docs/PAPER.md) · [English](docs/PAPER-en.md)

> 另外两份完整文档：
>
> - **AI 角色哀悼与继承协议 V7.0**：[`docs/PROTOCOL-V7.md`](docs/PROTOCOL-V7.md)
>   —— 人死后人格与情感记忆如何被继承。**工程定稿，尚未实现**（`aiinvite/succession` 目前是 M15 的胶囊 V1；按宪章，活着的用户路径优先）。
> - **影响评估**：[`docs/IMPACT-PROTOCOL-V7.md`](docs/IMPACT-PROTOCOL-V7.md)

## 安装

```bash
pip install ai-invite-memory          # 零第三方依赖，Python 3.11+
```

没有 PyPI 账号也行，直接装 Release 里的 wheel：
[下载页](https://github.com/Justnewtype167/ai-invite-memory/releases) · 详见 [`docs/INSTALL.md`](docs/INSTALL.md)

**想看它到底能做什么？** 装完跑一个 60 秒的窗口：

```bash
python -m aiinvite.demo.app
```

按一次「换模型」——kid 不变、用户卡不变，回答换了一个模型的声音。详见 [`aiinvite/demo/README.md`](aiinvite/demo/README.md)。

**这是内核，不是成品应用。** 它没有界面、不调模型；要「双击就能用」的产物，需要在其上再加一层（见 INSTALL §4）。

---

## 它是什么

## 它能回答什么问题

| 问题 | 机制 | 实测 |
|---|---|---|
| 记忆有没有被改过？ | 追加链 + 哈希链 | 改 1 字节即被发现；`python -m aiinvite.kernel.cli compile` 默认先验链（`E_KN_TAMPER`） |
| 换设备还能用吗？ | 单一胶囊文件，人格到岸重算 | 设备 B 重算 kid 相同 |
| 换模型还是同一个人吗？ | 内容身份 kid + 行为身份 PCS | PCS = 0.649（95% CI [0.522, 0.754]）；PCS 是**评测结果**，不随胶囊携带 |
| 上下文会很贵吗？ | 预算装配（4k 上限） | 20 万条记忆 p50 13 ms |
| 中文能零模型解析吗？ | 规则层（称谓 / 时间 / 俚语） | 留出集 14/14 |

## 一条命令跑起来

```bash
python -m unittest discover -s tests -v     # 383 tests，期望全绿
```

零第三方依赖，Python 3.11+。核心库不联网、不调模型——网络与模型调用只出现在 `tools/`。

## 目录

```
aiinvite/          证据层：容器、哈希链、字节可复现
aiinvite/cn/       中文规则层：称谓图、相对时间、梗时效、繁简
aiinvite/recall/   检索与预算装配：FTS5 + 二元切分 + 4k 上限
aiinvite/kernel/   人格内核：确定性编译、门控、历史、提案
aiinvite/pcs/      行为身份：PCS、可执行规则、坍塌深度
tools/         外部适配器（网络只在这里）：提案器、回复采集、矩阵实验
experiments/   实验产物：回复集与矩阵结果
docs/          规格、验收记录、结果、论文
```

## 关键文档

| 文档 | 内容 |
|---|---|
| [docs/PAPER.md](docs/PAPER.md) | 论文正文（中文） |
| [docs/PAPER-en.md](docs/PAPER-en.md) | 论文正文（English） |
| [docs/RESULTS-rater-comparison.md](docs/RESULTS-rater-comparison.md) | 模型 vs 真人：同一套规则的通过率 |
| [docs/RESULTS-judge-validity.md](docs/RESULTS-judge-validity.md) | 判定器效度：κ 的四轮递进 |
| [docs/RESULTS-variance.md](docs/RESULTS-variance.md) | 方差与分辨力：采样下 PCS 测不出差异 |
| [docs/SPEC-CHECKLIST.md](docs/SPEC-CHECKLIST.md) | 规格自检清单 |
| [AGENTS.md](AGENTS.md) | 开发约束与里程碑状态 |
| [CHANGELOG.md](CHANGELOG.md) | 11 个里程碑的来龙去脉 |

## 证据一览

```
内容身份   跨进程 kid 一致 / 删内核重建一致 / 换设备一致 / 提案删了 kid 回来
行为身份   PCS = A × min(C)；80 条可执行规则探针；判定器 κ = 0.690（60 条留出集）
人类基线   191 条真人发言：R1 通过 10%、R5 通过 98% —— 规则是对 AI 的规定，不是人类行为描述
多轮坍塌   R = 0.389 / 0.556；D = 0.657 / 0.635
性能       20 万事件建索引 12 s；装配 p50 13 ms
```

## 明确没有的东西

- 没有真实长期用户数据（全部为合成场景 + 模型生成）
- 没有跨月回放
- 没有与其他记忆系统的横向实验
- 结论只适用于情绪支持模式（咨询模式规则集未做）

这些限制在论文 §7.2 逐条列出。

## 许可

Apache-2.0，见 [LICENSE](LICENSE)。

English: [README-en.md](README-en.md)
