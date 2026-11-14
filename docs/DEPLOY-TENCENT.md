# 部署到腾讯云轻量（Python 后端内嵌）

适用形态：爱邀后端是 Python，GM 管理后台已经存在。本文件给的是**库内嵌**方案：
记忆引擎作为包装进后端的 venv，不另起 HTTP 服务，不新建状态页——GM 后台
直接读 `MemoryService.view()` 的返回值。

> 一句话：**没有独立的"记忆服务"进程，也没有独立端口。** 记忆是后端里的一个对象，
> 数据是服务器上的一个目录树。

## 1. 服务器与系统版本

轻量（Lighthouse）最低 2C2G 够跑单用户到几十个 20k 事件用户；建议系统盘 ≥ 40 GB。

**要用 Ubuntu 24.04 镜像，不要 22.04。** 22.04 自带 Python 3.10，而 wheel 声明
`requires-python >=3.11`，在 22.04 上 `pip install` 会报 "No matching distribution"。

```bash
python3 -VV        # 需要 3.11 或更高（24.04 是 3.12）
```

如果已经在 22.04 上，两条路：重装成 24.04；或用 deadsnakes PPA 装 3.12 后用它建 venv。
重装更省事，数据还没上就不用迁移。

## 2. 安装

```bash
apt-get update && apt-get install -y python3-venv
install -d -m 0755 /opt/aiinvite
python3 -m venv /opt/aiinvite/venv
/opt/aiinvite/venv/bin/pip install --upgrade pip
/opt/aiinvite/venv/bin/pip install ai-invite-memory==0.42.0
# 国内机器可用镜像：-i https://mirrors.cloud.tencent.com/pypi/simple

/opt/aiinvite/venv/bin/python -c "import aiinvite, aiinvite.serve; print(aiinvite.__version__)"
```

还没发到 PyPI 的版本可以按 tag 装：

```bash
/opt/aiinvite/venv/bin/pip install "git+https://github.com/Justnewtype167/ai-invite-memory.git@v0.42-m37"
```

## 3. 数据目录

一个 key 一个目录，目录名就是 key。**不要放 `/tmp`**，也不要放代码目录（部署会覆盖）。

```bash
useradd --system --home /var/lib/aiinvite --shell /usr/sbin/nologin aiinvite
install -d -m 0700 -o aiinvite -g aiinvite /var/lib/aiinvite/users
```

目录结构（由库自己建，不要手改）：

```text
/var/lib/aiinvite/users/
  u_1001/            # key = 用户 id（一个用户一个角色时）
    chain.json       # 哈希链
    evidence/seg-0001.jsonl
    .index/idx.sqlite   # 可重建的检索索引
    .snapshots/         # 内核快照，可重建
  u_1001-c_7/        # 一个用户多个角色时：key = 用户+角色
```

`.index/` 和 `.snapshots/` 是派生数据，删了会自动重建；`chain.json` + `evidence/` 是唯一真相。

## 4. 后端接线

一个进程一个 `MemoryService`（模块级单例），每个请求按 key 取会话。

```python
from aiinvite.serve import MemoryService

service = MemoryService(
    root="/var/lib/aiinvite/users",
    model="glm4:9b",           # 只存进 prompt 的模型名，不发起模型调用
    budget=4096,
    max_sessions=32,           # 见第 7 节的内存预算
)
```

一轮对话的顺序是固定的：

```python
@app.post("/chat/{user_id}")
def chat(user_id: str, body: ChatIn):          # def，不是 async def：下面是阻塞调用
    turn = service.turn(user_id, body.text)    # 1. 记用户这句，拿到 prompt
    reply = my_llm(turn["prompt"])             # 2. 你自己的模型调用
    verdict = service.reply(user_id, reply)    # 3. 闸门：过了才写进证据
    if not verdict["allowed"]:
        return {"say": FALLBACK_LINE, "refused": verdict["rule"]}
    return {"say": reply, "kid": service.view(user_id)["kid"]}
```

FastAPI 里用 `def` 而不是 `async def`：`turn`/`reply` 是同步阻塞（20k 约 0.15–0.19 s，
200k 约 0.8 s），FastAPI 会把 `def` 放进线程池，不会卡住事件循环。

**`service.reply()` 不能省。** 省掉就等于没有闸门：模型说什么都直接进记忆。

## 5. GM 后台读什么、改什么

`service.view(key)` 返回一个可以直接 `json.dumps` 的 dict：

| 字段 | 含义 | GM 用途 |
| --- | --- | --- |
| `kid` | 人格身份哈希（16 进制，64 位） | 显示"身份指纹"，改设定后会变 |
| `head` | 证据链头事件 id | 排障 |
| `events` | 证据条数 | 用户资料页显示活跃度 |
| `card` | 用户卡：`address.call`（称呼）、`address.never`（忌称）、`people`、`taboos`、`promises`、`ongoing`、`prefs` | 用户资料页 |
| `canon` | 长期规则/设定（`directive/lock` 的文本） | AI 角色设定页 |
| `persona` | 自性描述（特质） | AI 角色资料页 |
| `pins` | 永不遗忘的记忆列表 | 编辑置顶 |
| `rules` | 六条行为规则（规格方维护，只读） | 只展示，不给改 |
| `store` | 磁盘目录 | 运维排障 |

修改只有三条合法路径：

| GM 动作 | 调用 | 结果 |
| --- | --- | --- |
| 改称呼/忌称/设定 | `service.remember(key, "叫我周哥")` | 写成 `directive/lock` 证据，`kid` 变，用户卡/设定立即生效 |
| 钉住一条记忆 | `service.pin(key, event_id)` | 写 pin 证据，该条进每轮 prompt |
| 取消钉住 | `service.unpin(key, event_id)` | 写 unpin 证据 |

**不要直接改用户卡、也不要手改 `.snapshots/`。** 用户卡是从证据派生的，
下一次派生会把它覆盖回去；手改快照会被 sha256 校验拒绝（`E_KN_SNAPSHOT`）。

`remember` 改称呼是可以的，因为称呼本身也参与卡片派生；改纯设定（例如
"回复控制在两句以内"）会进 `canon` 与闸门，但**目前不会出现在 prompt 里**——
见第 9 节。

## 6. 并发与进程模型

- 同一个 key 的写操作由 `MemoryService` 的**每 key 锁**串行化，进程内安全。
- **跨进程没有文件锁。** 同一个用户目录只能有一个进程写。所以：`uvicorn --workers 1`、
  `gunicorn -w 1`，不要开多 worker。
- 要横向扩，就按 key 分片：一个进程负责一段 key（例如 `hash(user_id) % N`），
  前端按同一个分片规则路由。不同 key 之间没有共享状态。
- 多角色产品（一个用户多个 AI 角色）用 `key = f"{user_id}-{character_id}"`，
  每个角色一条独立证据链、一个独立 kid。别把多个角色塞进一个 key。

## 7. 内存与容量（实测，16 GB 机器）

| 单个用户 | 磁盘 | 常驻内存（RSS） | 每轮 |
| --- | --- | --- | --- |
| 20k 事件 | 11.8 MB（证据 5.2 + 索引 6.4） | 46 MB（峰 49） | 0.15–0.19 s |
| 200k 事件 | 118.9 MB（索引 65.1 + 证据 52.1） | 165 MB（峰 244） | 0.78–0.87 s |

换算：1 GB 内存大约够 100 个 20k 会话或 8 个 200k 会话常驻。

`max_sessions` 是常驻会话上限，超了按 LRU 换出（磁盘数据不动，下次进来重建，
200k 冷启动 30–34 s，20k 约 2–4 s）。建议：

```text
max_sessions ≈ min(64, 可用内存 GB × 1024 / 300)   # 300 MB 一个 200k 会话的余量
```

2C2G 的轻量：`max_sessions=4`；4C8G：`max_sessions=16`。

## 8. 验收：四条命令

装完先跑这四条，全过再接线：

```bash
# 1. 包和版本
/opt/aiinvite/venv/bin/python -c "import aiinvite, aiinvite.serve; print(aiinvite.__version__)"

# 2. 一轮对话 + 用户卡 + 闸门（临时目录，不碰线上数据）
/opt/aiinvite/venv/bin/python - <<'PY'
import tempfile, shutil
from aiinvite.serve import MemoryService
root = tempfile.mkdtemp()
try:
    svc = MemoryService(root, "glm4:9b")
    out = svc.turn("smoke", "我叫老周，别叫我宝贝")
    view = svc.view("smoke")
    print("kid", view["kid"][:12], "events", view["events"])
    print("call", view["card"]["address"]["call"], "never", view["card"]["address"]["never"])
    print("prompt bytes", len(out["prompt"].encode()))
    svc.remember("smoke", "别叫我宝贝")   # 设定进 canon，闸门才会启用
    print("gate", svc.reply("smoke", "好的，宝贝"))
finally:
    shutil.rmtree(root, True)
PY
```

期望：`call 老周`、`never [{'text': '宝贝'...}]`、`gate {'allowed': False, 'rule': '禁称呼', ...}`。

```bash
# 3. 证据链完整性（对每个真实用户目录）
/opt/aiinvite/venv/bin/aiinvite verify /var/lib/aiinvite/users/u_1001
# OK events=… segments=… head=… state=open

# 4. 备份一份（快照不封存线上库）
/opt/aiinvite/venv/bin/aiinvite snapshot /var/lib/aiinvite/users/u_1001 /var/backups/u_1001.aiem
/opt/aiinvite/venv/bin/aiinvite verify /var/backups/u_1001.aiem
```

## 9. 备份、恢复、安全

**备份**：`aiinvite snapshot <store> <out.aiem>` 是热备份，不会封存线上库；
每天对 `users/*` 各做一份，`aiinvite verify` 过一遍，再传对象存储。
恢复用 `aiinvite import <capsule> <dir>`，导入后 `kid` 与原来一致即可确认没换人。

**安全**：库里是对话原文。

- 后端 API 必须走 HTTPS（轻量控制台可以一键申请证书，或前置 nginx/caddy）。
- 每用户请求要带 token，且服务端校验 token 属于该 `user_id`。
- `/var/lib/aiinvite` 权限 0700，只给 `aiinvite` 用户。
- GM 后台的 `view` 接口不要暴露到公网（它含用户原话派生的卡片）。

## 10. 已知缺口：设定进了内核，没进 prompt

`remember()` 写的 `directive/lock` 现在有三个作用：进 `canon`（`kid` 变）、
按关键词启用闸门规则、以及被称呼/偏好类派生带进用户卡。

但**纯设定类文本（"回复两句以内""别主动联系"）不会出现在 prompt 里**，
模型看不到，只能靠闸门事后拦截。对 GM 后台来说，这意味着"改设定"只是改了身份
与闸门，不是"告诉模型该怎么做"。

补法有两种，需产品拍板：

1. prompt 增加 `## standing rules` 块，只放 `canon` 里 `directive` 来源的条目
   （不放 promise，避免和上下文重复），排在用户卡之后、永不遗忘之前；
2. 或者 GM 的"设定"改写成行为规则文件（规格方维护），不进每轮 prompt。

选 1 更符合"设定立刻生效"的直觉，代价是每轮 prompt 多几十个 token，且要重跑
全部提示词相关测试。