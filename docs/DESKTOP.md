# 桌面应用（Windows 单人版）

> 生成一个**不依赖 Python 环境**的 `AI Invite Memory.exe`，双击即用。

---

## 用户拿到的是什么

```
C:\Users\<你>\AppData\Local\AIInvite\AI Invite Memory.exe     12.7 MB，单文件
桌面快捷方式：AI Invite Memory.lnk
记忆目录：    %APPDATA%\AIInvite\memory         （卸载 exe 也不删记忆）
```

**依赖：** 本地 Ollama（默认模型 `glm4:9b`）。没有 Ollama 也能开窗口，只是发消息会提示连不上。

---

## 怎么构建

```powershell
# 1. 一个只用来打包的 venv
python -m venv $env:LOCALAPPDATA\AIInvite\venv
$venv = "$env:LOCALAPPDATA\AIInvite\venv"
& "$venv\Scripts\python.exe" -m pip install ai-invite-memory pyinstaller

# 2. 打成单文件窗口程序（--collect-all 必须带，否则包内 data/*.json 不会被打进去）
& "$venv\Scripts\python.exe" -m PyInstaller --noconfirm --onefile --windowed \`
    --name "AI Invite Memory" --collect-all aiinvite \`
    --distpath apps --workpath build\pyinstaller --specpath build \`
    packaging\launcher.py

# 3. 装到固定位置
Copy-Item "apps\AI Invite Memory.exe" "$env:LOCALAPPDATA\AIInvite\" -Force
```

---

## 桌面快捷方式

```powershell
$desktop = [Environment]::GetFolderPath("Desktop")
$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut((Join-Path $desktop "AI Invite Memory.lnk"))
$sc.TargetPath = "$env:LOCALAPPDATA\AIInvite\AI Invite Memory.exe"
$sc.WorkingDirectory = "$env:LOCALAPPDATA\AIInvite"
$sc.Save()
```

---

## 踩过的坑（都在这里，别再踩一遍）

| 坑 | 症状 | 处理 |
|---|---|---|
| 忘了 `--collect-all` | exe 一起就弹 "Unhandled exception"，日志说找不到 `variants.json` | 打包必须带 `--collect-all aiinvite` |
| `pythonw -m aiinvite.demo.app` | 本机 pythonw + tkinter 起不来（最小窗口也一样） | 用 PyInstaller 打 exe，别赌 pythonw |
| venv 没有 pip | `pip install` 静默失败、`import` 找不到包 | 建完 venv 先确认 `pip.exe` 存在，否则 `ensurepip` |
| 默认记忆目录在 temp | 每次打开都忘掉你 | 已改为 `%APPDATA%\AIInvite\memory` |
| 第二次打开崩溃 | `目录已存在且非空` | 已有 `chain.json` 时不再 init |

---

## 与 PyPI 的关系

| 谁 | 装什么 |
|---|---|
| 开发者 | `pip install ai-invite-memory` |
| 普通用户 | 直接拿这个 exe |
