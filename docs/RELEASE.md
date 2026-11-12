# 发布流程（PyPI 与 Release）

> 面向维护者。**PyPI 发布需要你本人的账号 token，我无法代做。**

---

## 1. 当前状态

```
GitHub Release   ✅ 已有 wheel + sdist（v0.23-m18.1）
PyPI             ⬜ 名字可用（ai-invite-memory 未被占用），尚未发布
```

## 2. 发布到 PyPI（三步，约 10 分钟）

### 2.1 一次性：创建账号与 token

```
① https://pypi.org/account/register/
② https://pypi.org/manage/account/token/ → 新建 token（scope 选 Entire account 或本项目）
③ token 形如 pypi-AgEIcHl...，只显示一次，复制保存
```

### 2.2 本地发布

```bash
python -m pip install --upgrade build twine
python -m build                    # 生成 dist/*.whl 与 dist/*.tar.gz
python -m twine check dist/*       # 元数据检查，必须 PASSED
python -m twine upload dist/*      # 提示输入 __token__ / 粘贴 token
```

### 2.3 验证

```bash
pip install ai-invite-memory
aiinvite --help
```

## 3. 版本规则

```
pyproject version 必须与 tag 一致
tag 格式：v<major>.<minor>-m<里程碑序号>   例：v0.23-m18.1
PyPI 上不可覆盖版本号，发布后只能升版本
```

## 4. 自动化

`.github/workflows/release.yml`：push 一个 `v*` tag 时自动

```
① 构建 wheel + sdist
② twine check
③ 在干净的 venv 里装一次、跑 aiinvite --help 与 import 冒烟
④ 把产物挂到对应的 GitHub Release
```

**注意**：PyPI 那一步没有自动化（需要 API token 存放在仓库 secret）。
如果要接入，加 `PYPI_API_TOKEN` secret 并补一段 `pypa/gh-action-pypi-publish`。

## 5. 发布前检查清单

```
[ ] python -m unittest discover -s tests     486 全绿
[ ] CI 在 main 上为绿
[ ] pyproject version == tag
[ ] twine check dist/*                       PASSED
[ ] 干净 venv 安装后 aiinvite --help 可用
[ ] wheel 内含 aiinvite/*/data/*.json（14 个）
[ ] CHANGELOG 已写本次变化
```

## 6. 已知的打包坑（已踩过）

| 坑 | 症状 | 处理 |
|---|---|---|
| 只声明部分包 | 装上缺 pcs/persona/succession | 用 `packages.find`，不要手写列表 |
| 缺 data 文件 | 装上运行时报 FileNotFoundError | `package-data` 里逐包写 `data/*.json` |
| 行尾不统一 | CI 冻结基线比对失败 | `.gitattributes` 统一 LF |
| 弃用的 license classifier | 构建直接失败 | 用 PEP 639 的 `license = "Apache-2.0"` |
