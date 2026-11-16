# 安装与分发

> 目标读者：**开发者**（把这个内核接进自己的 AI 伴侣产品）。
> 给普通用户的成品应用见 §4。

---

## 1. 一条命令

```bash
pip install ai-invite-memory
```

零第三方依赖，Python 3.11+。装完就有 `aiinvite` 命令。

```bash
aiinvite --help
```

## 2. 不走 PyPI 的装法

从 GitHub Releases 下 `.whl`：

```bash
pip install https://github.com/Justnewtype167/ai-invite-memory/releases/download/v0.23-m18.1/ai_invite_memory-0.23.1-py3-none-any.whl
```

或者克隆仓库（开发用，含测试与实验脚本）：

```bash
git clone https://github.com/Justnewtype167/ai-invite-memory.git
cd ai-invite-memory
python -m unittest discover -s tests -v     # 524 tests
```

## 3. 装完能做什么（30 秒验证）

```python
import pathlib, tempfile
from aiinvite.capsule import append_event, init_store, seal_store, verify_path
from aiinvite.kernel.compiler import compile_kernel
from aiinvite.kernel.kernel import Policy
from aiinvite.persona import build_persona_view

store = pathlib.Path(tempfile.mkdtemp()) / "mem"
init_store(store)
append_event(store, "user", "我叫老周，别叫我宝贝", "2026-11-01T09:00:00+08:00")
seal_store(store)
kernel = compile_kernel(store, Policy(now="2026-11-01T10:00:00+08:00"))
view = build_persona_view(store, policy=Policy(now="2026-11-01T10:00:00+08:00"))
print(kernel.kid)                 # 身份，可重算
print(view.user_card.text())     # 认得的称呼与忌讳
print(verify_path(store).events) # 证据链校验
```

## 4. 仓库里有什么、没有什么

**这个仓库的主体是内核，不是成品应用。** 分三块看：

| 部分 | 是什么 | 依赖 |
|---|---|---|
| `aiinvite/`（除 `demo/`） | 内核与接入层：证据链、内核、检索、人格、闸门、`host`、`serve` | 零第三方、零网络 |
| `aiinvite/demo/` | 可选的桌面演示（tkinter 窗口 + 本地 Ollama），用来眼见为实 | 只用标准库；要 Ollama 才出回复 |
| `docs/` | 论文、任务书、验收记录、部署与宿主接入说明 | — |

谁会用到什么：

- **开发者接入自己的聊天产品**：`pip install ai-invite-memory`，用 `HostSession`（单用户）或
  `MemoryService`（多用户，0.42 起）——见 `HOST-INTEGRATION.md` 与 `DEPLOY-TENCENT.md`。
- **想先看一眼**：`docs/DESKTOP.md` 用 PyInstaller 打单文件 exe（演示目录不在内核依赖里，
  `pip install` 的用户完全不碰它）。
- **普通用户**：需要上层应用（如爱邀本体）；本仓库提供的是它脚下的地基。

仓库里**没有**：模型本身、账号与鉴权、多用户 HTTP 服务、运营后台。这些属于上层产品，
内核只保证「记忆与人格是可验证、可携带、可重算的」。

## 5. 平台支持

| 平台 | 状态 |
|---|---|
| Windows | ✅ 本地全量测试通过（524） |
| Linux | ✅ CI 通过（Python 3.11 / 3.12） |
| macOS | ⚠️ 未在真机验证（代码无平台分支，预期可用） |

## 6. 卸载

```bash
pip uninstall ai-invite-memory
```

数据在你自己指定的 `store` 目录里，**删包不会删数据**。
