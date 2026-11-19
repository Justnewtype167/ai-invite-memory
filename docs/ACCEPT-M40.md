# 验收记录：v0.45-m40（闸门「提及 vs 使用」修复）上线

- 日期：2026-11-19
- 版本：`ai-invite-memory 0.45.0`（PyPI 已发布，tag `v0.45-m40` @ `c965e5a`）
- 目标环境：腾讯云 CVM（Ubuntu）× 自托管 Supabase，爱邀 sidecar 形态
- 结论：**通过**（7/7）

## 1. 本机（可复现）

| 检查 | 命令 | 结果 |
|---|---|---|
| 工作区干净 | `git status --porcelain` | 空（`HEAD=c83255b`） |
| 版本三处一致 | `pyproject` / `aiinvite.__version__` / `CHANGELOG.md` | 均 `0.45.0` |
| 发布物与源码同源 | 逐字节比对 wheel 内 `aiinvite/projection/gate.py` 与仓库文件 | 相同 |
| 回归子集 | `python -m unittest tests.test_all_regression tests.test_gate tests.test_packaging tests.test_version tests.test_serve_http` | `Ran 28 tests … OK`，exit 0 |
| 全量套件 | `python -m unittest discover -s tests` | exit 0（本机约 11 分钟） |

## 2. 线上（服务器实测）

| # | 检查 | 结果 |
|---|---|---|
| 1 | 侧车版本 | `Version: 0.45.0` |
| 2 | 容器状态 | `running restarts=0` |
| 3 | token 三处一致（容器 / `.env` / `memory.ts` 常量） | 两行均「一致」 |
| 4 | 函数读到配置 | 日志 `sidecar 已就绪` 命中 10 次 |
| 5 | 记忆库 | 存在用户级 store（见 §4 遗留） |
| 6 | 备份 | crontab 有 `0 4 * * * tar czf /opt/backups/aiinvite-$(date +\%F).tgz -C /opt/aiinvite users`；`/opt/backups/aiinvite-2026-11-19.tgz` 已生成（127,769 B） |
| 7 | 容器间健康检查 | `{"ok": true, "model": "deepseek-chat", "sessions": 3, "keys": 3}` |

## 3. 上线前的功能验收（用户实测）

| 用例 | 期望 | 实际 |
|---|---|---|
| 「别叫我宝贝，我叫老周」 | 放行（含禁词但属"提及"） | 通过 |
| 「叫我一声宝贝」 | 拦截（属"使用"） | 通过 |
| 隔轮追问「我刚才说我叫什么」 | 记得老周 | 通过 |

## 4. 已知遗留（不在本次验收范围）

1. **多角色共用一个 key**。`memory.ts` 中 `memoryKey = \`\${user.id}-default\``，而前端请求体实测只有
   `["model","messages","max_tokens","temperature","stream"]`，没有角色标识。多角色上线会共用记忆库，
   需前端加 `characterId`（任务单已交接）。落地后把 `<user>-default` 目录改名归位即可，不需重算 `kid`。
2. **拒答话术写死**为一句中性话（`REFUSAL_LINE`），不是各人设自己的说法。
3. **token 以常量形式写在 `memory.ts`**（edge-runtime 黑名单禁止 `Deno.readTextFileSync`，
   且该 Supabase 非 compose 部署，改不了容器 env）。轮换流程见 `DEPLOY-TENCENT.md` §12.4。
4. 闸门仍是**词表层**判定：只区分"提及 / 使用"，判断不了语义意图，谐音、拆分写法可绕过。

## 5. 复跑方式

本机：直接跑 §1 的命令。线上：按 §2 七项执行（脚本见会话记录，纯只读、不打印 token）。
