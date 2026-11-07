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
python -m unittest discover -s tests -v     # 470 tests
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

## 4. 给普通用户的应用产物：还没有

**这个仓库是内核，不是成品应用。** 它没有界面、不调模型、不打包成 exe。

| 谁能直接用 | 怎么用 |
|---|---|
| 开发者 | `pip install`，五个方法接进自己的聊天前端（见 `HOST-INTEGRATION.md`） |
| 普通用户 | **需要上层应用**（如爱邀本体）；本仓库提供的是它脚下的地基 |

要变成「用户双击就能用」的产物，需要在它之上加一层：

```
① 本地聊天界面（桌面或网页）
② 一个可选的本地模型接入（Ollama）
③ PyInstaller 单文件打包
```

这三件事都**不属于本仓库的范围**，因为它们会引入第三方依赖、界面代码与模型调用，
而内核的底线是「零依赖、零网络、只做确定性派生」。

## 5. 平台支持

| 平台 | 状态 |
|---|---|
| Windows | ✅ 本地全量测试通过（470） |
| Linux | ✅ CI 通过（Python 3.11 / 3.12） |
| macOS | ⚠️ 未在真机验证（代码无平台分支，预期可用） |

## 6. 卸载

```bash
pip uninstall ai-invite-memory
```

数据在你自己指定的 `store` 目录里，**删包不会删数据**。
