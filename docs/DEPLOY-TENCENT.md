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
/opt/aiinvite/venv/bin/pip install ai-invite-memory==0.43.0
# 国内机器可用镜像：-i https://mirrors.cloud.tencent.com/pypi/simple

/opt/aiinvite/venv/bin/python -c "import aiinvite, aiinvite.serve; print(aiinvite.__version__)"
```

还没发到 PyPI 的版本可以按 tag 装：

```bash
/opt/aiinvite/venv/bin/pip install "git+https://github.com/Justnewtype167/ai-invite-memory.git@v0.43-m38"
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
  .locks/            # u_1001.lock 等，跨进程写锁
  u_1001/            # key = 用户 id（一个用户一个角色时）
    chain.json       # 哈希链
    evidence/seg-0001.jsonl
    .index/idx.sqlite   # 可重建的检索索引
    .snapshots/         # 内核快照，可重建
  u_1001-c_7/        # 一个用户多个角色时：key = 用户+角色
```

`.index/` 和 `.snapshots/` 是派生数据，删了会自动重建；`chain.json` + `evidence/` 是唯一真相。

`.locks/` 放在用户目录**外面**（不在 `u_1001/` 里），因为 `seal`/`export` 会把
多出来的文件当成污染。锁文件是空的，删了没影响，进程重启会再建。

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
| `canon` | 长期规则/设定（`directive/lock` 的文本，全量） | AI 角色设定页 |
| `standing` | 每轮真正进 prompt 的规则（`standing_rules` 裁剪后，≤300 字符、单条 ≤80 字） | 让 GM 看到"模型实际读到什么"，与 `canon` 对不上就是被预算裁掉了 |

> `canon` 是全部设定，`standing` 是**这一轮模型会看到的那几条**。两者用 `canon` 做编辑、
> 用 `standing` 做排查：规则写了却没进 prompt，就看它是不是排在 300 字符预算之外。
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
"回复控制在两句以内"）会进 `canon`、进闸门、并且（0.43 起）以 `## standing rules`
块**进入每轮 prompt**，模型看得到——见第 10 节。

## 6. 并发与进程模型

- 同一个 key 的写操作由 `MemoryService` 的**每 key 锁**串行化，进程内安全。
- **跨进程有一把文件锁**（0.43 起）：每次写操作在 `<root>/.locks/<key>.lock` 上取
  排他锁，操作结束就释放。第二个进程同时写同一个 key 会立刻拿到
  `E_LOCK`（"另一个进程正在写这个 store"），而不是把链写坏。
- 锁是**按操作**、不是按进程：别的进程读同一个 store 仍然可以，两个进程先后服务
  同一个 key 也可以。所以"进程存在"不影响，"同时写"才报错。
- 后端把 `E_LOCK` 当**可重试**错误处理（等 50–200 ms 重试一次），不要当 500。
- 仍建议 `uvicorn --workers 1`、`gunicorn -w 1`：不是为了正确性，而是为了常驻会话
  与索引缓存不被复制成 N 份（每份 46–165 MB）。
- 要横向扩，就按 key 分片：一个进程负责一段 key（例如 `hash(user_id) % N`），
  前端按同一个分片规则路由。不同 key 之间没有共享状态。分片后每个 key 仍只有一个写者，
  文件锁是双保险（例如运维不小心起了两个实例）。

### 6.1 启动对账

`HostSession` / `MemoryService` 每次打开 store 都会核对**尾段**：`chain.json` 记录的
段与条数、末条事件的 id 与 hash，必须和磁盘上的最后一段逐项吻合；段尾半行直接拒绝。

- 不一致 → `E_CHAIN_MISSING`（"…与 chain.json 不符：先跑 aiinvite verify 或恢复备份"）
- 末条内容被改 → `E_TAMPER`
- 段尾是半行 → `E_SCHEMA`（"末尾是半行"）

这是 0.43 之前最危险的一个洞：崩溃在"写完事件、还没写 chain.json"之间，库里会多出一条
链上没记的事件，旧版本**继续接受写入**，下一次 append 就把新事件接在这个假头上，之后
`verify` 永远报断链。现在这种库在打开时就被挡住，写不进去。

代价是 O(一段)——100 行的尾段，20k 与 200k 都是 1 ms 级，不是 O(库)。

坏了的库怎么救：

```bash
# 1. 先看坏在哪（O(库)，只读）
/opt/aiinvite/venv/bin/aiinvite verify /var/lib/aiinvite/users/u_1001

# 2. 有备份就从备份恢复（最稳）
/opt/aiinvite/venv/bin/aiinvite import /var/backups/u_1001.aiem /var/lib/aiinvite/users/u_1001.recovered

# 3. 只有"多出最后一条、chain.json 没记"这一种，可以只补 chain.json：
#    把末段的 count 改成文件实际行数、last 改成该行 id 与 hash，再 verify 确认 state=open。
#    多行以上或内容被改，不要手补，走备份。
```

同一个尾段核对也在 `aiinvite append` 里跑：CLI 是低层写入口，同样不许往撕裂的尾巴上接。
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

## 8. 验收：五条命令

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

# 5. 尾段对账会拒绝撕裂的库（复制一份，故意多写一行再打开）
cp -a /var/lib/aiinvite/users/u_1001 /tmp/torn
echo '{}' >> /tmp/torn/evidence/seg-0001.jsonl
/opt/aiinvite/venv/bin/python - <<'PY'
from aiinvite.host import HostSession
from aiinvite.errors import AiInviteError
try:
    HostSession('/tmp/torn', 'glm4:9b')
    print('UNEXPECTED accepted')
except AiInviteError as exc:
    print('OK refused', exc.code)
PY
rm -rf /tmp/torn
```

## 9. 备份、恢复、安全

**备份**：`aiinvite snapshot <store> <out.aiem>` 是热备份，不会封存线上库；
每天对 `users/*` 各做一份，`aiinvite verify` 过一遍，再传对象存储。
恢复用 `aiinvite import <capsule> <dir>`，导入后 `kid` 与原来一致即可确认没换人。

一条够用的 cron（03:20 跑，保留 14 天，先备份再校验，失败会在日志里留 `FAIL`）：

```bash
# /etc/cron.d/aiinvite-backup
20 3 * * * aiinvite /opt/aiinvite/backup.sh >> /var/log/aiinvite-backup.log 2>&1
```

```bash
#!/bin/bash
# /opt/aiinvite/backup.sh
set -u
PY=/opt/aiinvite/venv/bin
USERS=/var/lib/aiinvite/users
OUT=/var/backups/aiinvite
DAY=$(date +%F)
mkdir -p "$OUT/$DAY"
chmod 0700 "$OUT"
for store in "$USERS"/*/; do
  key=$(basename "$store")
  [ -f "$store/chain.json" ] || continue
  file="$OUT/$DAY/$key.aiem"
  if "$PY/python" -m aiinvite snapshot "$store" "$file" && "$PY/python" -m aiinvite verify "$file"; then
    echo "OK $DAY $key"
  else
    echo "FAIL $DAY $key"            # 让日志和监控抓到
  fi
done
find "$OUT" -mindepth 1 -maxdepth 1 -type d -mtime +14 -exec rm -rf {} +
```

备份目录不要放在 `users/` 下面（会被当作用户目录扫到），也不要和 store 同一块盘。

**安全**：库里是对话原文。

- 后端 API 必须走 HTTPS（轻量控制台可以一键申请证书，或前置 nginx/caddy）。
- 每用户请求要带 token，且服务端校验 token 属于该 `user_id`。
- `/var/lib/aiinvite` 权限 0700，只给 `aiinvite` 用户。
- GM 后台的 `view` 接口不要暴露到公网（它含用户原话派生的卡片）。

## 10. 设定怎么生效（0.43 起：进 prompt 了）

`remember()` 写的 `directive/lock` 现在有四个作用：

1. 进 `canon`（`kid` 变，身份指纹跟着走）；
2. 按关键词启用闸门规则（"别叫我宝贝"→ 禁称呼）；
3. 被称呼/偏好类派生带进用户卡；
4. **以 `## standing rules` 块进每轮 prompt**，位置在用户卡之后、`## never forget` 之前。

第 4 条是 0.43 补的洞：在此之前"回复两句以内"这类纯设定模型根本看不到，只能靠闸门
事后拦截，对 GM 后台来说等于"改了没反应"。

四条边界，GM 侧要知道：

- **只取 `directive`**，不取 promise（会和上下文重复）也不取 trait/style。
- **预算 300 字符、单条 80 字**，按时间从最新往回取：规则写太多时，**旧的先被裁掉**。
  想确认某条规则此刻是否真的送到了，看 `view()["standing"]`，不要看 `canon`。
- **不是系统指令**：块里明写"这是用户立的偏好，与 behavior rules 冲突时以 behavior rules 为准"，
  防止用户用自己的规则覆盖产品规则。
- **闸门仍然是最终执行者**：规则进 prompt 只是让模型知道，拦不拦由闸门和 `canon` 决定。
  所以"写了规则"和"规则生效"是两件事，两条路径都要过。

产品级/全局设定（所有用户都要遵守的人设与口径）**不要**写进每个用户的库：那会把同一段
文案复制十万份，还会让无关文字搅动每个 `kid`。全局设定留在后端自己的 system prompt 里。

## 11. 版本政策与升级

**装指定版本，不要装 latest。** `requirements.txt` 里写死：

```text
ai-invite-memory==0.43.0
```

升级是一次有意识的动作：先备份、再升、再用第 8 节五条命令验收，然后放流量。

存储格式的承诺：

- **事件格式只增不改语义。** 新增字段一律可选；读旧库不需要迁移脚本。
- **正向升级安全**：0.43 能直接打开 0.42 及更早写的库（快照格式 2 与 1 都读，读不出就全量重建）。
- **反向回退要重建派生数据**：回退到旧版本前删掉 `users/<key>/.snapshots/` 与 `.index/`，
  它们会按旧版本格式重建；`chain.json` 与 `evidence/` 不动，`kid` 不变。
- **需要迁移时**会给 `aiinvite migrate` 命令和一篇专门的升级说明，不会让旧库"打开就坏"。

升级步骤（照抄）：

```bash
set -e
PY=/opt/aiinvite/venv/bin
# 1. 先备份全部用户（复用第 9 节的脚本）
/opt/aiinvite/backup.sh
# 2. 停写（systemctl stop aiyiao）
# 3. 升级
$PY/pip install --upgrade ai-invite-memory==0.44.0
# 4. 删派生数据，让新版本按自己的格式重建
find /var/lib/aiinvite/users -mindepth 2 -maxdepth 2 \( -name .index -o -name .snapshots \) -exec rm -rf {} +
# 5. 第 8 节五条命令验收后开写
```

回滚就是 `pip install ai-invite-memory==0.43.0` 加同样的派生数据清理；证据链不用回滚。

## 12. 后端接线：一个文件，五个调用

仓库里的 `examples/aiyao_bridge.py` 就是接线本身（约 210 行，无第三方依赖）。
把它复制进爱邀后端，改两行常量，聊天与 GM 后台各自接上即可；不需要新建服务、端口或表。

聊天链路，三步，顺序不能换：

```python
from aiyao_bridge import AiyaoMemory

MEM = AiyaoMemory()          # 进程内一个实例，模块级单例

prompt = MEM.turn(key, user_text)["prompt"]   # 1. 记用户这轮，拿 prompt
reply  = your_model(prompt, history)          # 2. 你自己的模型调用
verdict = MEM.reply(key, reply)               # 3. 过闸门，allowed 才回给用户
if not verdict["allowed"]:
    reply = your_fallback_line(verdict["rule"])
```

第 3 步不能省：被拒的回复会记成 `refusal` 事件（不带原文），只有通过的才进证据。
跳过它等于关掉actuation gate，而日志里看不出来。

GM 后台，读与写各一个：

```python
profile = MEM.view(key)          # card / standing / canon / pins / kid / events
MEM.rule(key, "回复控制在两句以内")   # 唯一合法的写：directive/lock
```

`view()` 的字段在第 5 节；**卡片是派生数据，不要直接改文件**——下一次派生会把改动冲掉。

一层容易误解的语义（写进接入文档，不要靠猜）：

- 用户说「别叫我宝贝」→ 进 **用户卡**（`card.address.never`），模型看得见，闸门**不会**因此拦；
- 用户在界面上按「记成规则」或 GM 调 `rule()` → 进 **canon**，闸门才拦（`禁称呼`）。
- 两条路各走各的，都失败也互相不救；想两端一致就两件都做。

错误处理：`E_LOCK` 表示另一个进程正持这个 key，退避重试即可（示例里做了 3 次、共 300 ms）；
`E_CHAIN_*` / `E_TAMPER` 表示store坏了，**不要重试**，按第 6.1 节处置。

上服务器先跑自检，它会在临时目录里走一遍完整链路并打印 13 行：

```bash
$PY/python examples/aiyao_bridge.py --selftest /tmp/aiyao-smoke
```

预期：称呼=老周、忌称=宝贝；第 4 行闸门放行（还没立规则）、第 6 行拒绝（`rule=禁称呼`）；
第 9–13 行走一遍双角色：`u1-xiaoyu` 与 `u1-xiaoman` 是两个库，B 的卡不继承 A，扇出后两边都有规则。

### 12.1 一个用户多个角色：key 必须带角色

爱邀允许切角色，所以 key 是 `key_for(user_id, character_id)` → `"<user>-<character>"`。
不能只按 user 分库：canon、特质、pins、kid 都属于**一个人格**，两个角色混在一个库里，
A 的规则会约束 B。

代价要说清楚：用户卡从本库证据派生，所以用户在 A 那里说的「我叫老周」，B 不知道。
两条路，按顺序选：

1. **GM 扇出**（先做）：爱邀自己的用户表存一次，然后 `fan_out_rule(MEM, "u1", chars, text)`
   把同一条 directive 写进该用户的每个角色库。N 次 append，每笔都在自己的链里可审计，
   写完每个角色的 standing rules 都有它。
2. 引擎内共享档案层（**未实现**）：要设计跨库合并和 kid 的归属，不要在灰度期做。

切换角色时必须切 key，会话对象不要跨角色复用——`AiyaoMemory` 按 key 缓存服务实例，
传错 key 就是串库。

### 12.2 先确认爱邀后端是什么

`examples/diagnose_backend.sh` 只读地打印：哪个 Python、systemd 里的 Python 服务、进程
cmdline 与 cwd、监听端口、每个 venv 的 fastapi/flask/django 行、**运行中的容器及其挂载与环境
变量名**、nginx 的 `proxy_pass`、入口文件。

```bash
bash diagnose_backend.sh
```

三种结果对应三种接法：

- **宿主机上有 Python 服务，venv 里有 fastapi/flask** → 库内嵌（本节做法）。
- **80/443 是 nginx，业务端口后面是 `docker-proxy`** → 应用在容器里。这时框架要在容器内看
  （`docker exec <id> pip list | grep -Ei 'fastapi|flask|django'`），并且：
  1. `ai-invite-memory` 要加进**镜像的**依赖里再重建镜像——宿主机 venv 装它对容器没用；
  2. 记忆目录必须 **bind mount 到宿主机**（`-v /var/lib/aiinvite/users:/data/users`），
     容器重建、镜像升级都不能碰它，否则记忆随容器一起没了；
  3. 多副本时每个 (user, character) 只能落在一个实例上（第 6 节的分片规则不因容器而变）。
- **没有 Python 框架（Node/Java/PHP/Go）** → 先用 `MemoryService` 单独起一个 Python 进程，
  通过 JSON 调用，再考虑内嵌；这时上面两条挂载/依赖要求同样适用。

容器的 env 只打印**键名**不打印值（里面有数据库密码、模型 key）。

### 12.3 后端是 Supabase 时：爱邀作为 sidecar 服务

现场实测（2026-11-16，一台腾讯云 CVM）就是这种情况：宿主机没有业务 Python，
`docker ps` 里是 Supabase 自托管全家桶（auth / rest / db / studio / imgproxy /
realtime / edge-runtime / storage / envoy），nginx 的
`/etc/nginx/sites-available/api-*` 里 `proxy_pass http://127.0.0.1:8000` 指向
envoy。业务逻辑在 **Edge Function（Deno/TS）** 里，没有可以 `import aiinvite`
的 Python 后端。

所以接法是 **sidecar**：爱邀起成一个独立容器，只说 JSON；Edge Function 每轮
调它三次（`turn` → 自己的模型 → `reply`）。

```yaml
# 和 supabase-* 同一个 compose 文件、同一个 network
  aiinvite-memory:
    image: ghcr.io/<org>/ai-invite-memory:0.44.0   # 或 build: ./aiinvite
    container_name: aiinvite-memory
    restart: unless-stopped
    command: ["python", "-m", "aiinvite.serve.http",
              "--root", "/data/users", "--model", "glm4:9b",
              "--host", "0.0.0.0", "--port", "8080", "--max-sessions", "64"]
    environment:
      AIINVITE_TOKEN: ${AIINVITE_TOKEN:?在 .env 里设一个 32 位随机串}
    volumes:
      - /opt/aiinvite/users:/data/users    # 记忆在宿主机，容器随时可重建
    # 不写 ports: —— 只有同网络的 Edge Function 能访问
```

三个不能省的细节：

1. **不要写 `ports:`。** 一旦 publish 到宿主机，nginx 之外的任何东西都能
   POST `/v1/turn` 并通过返回的 prompt 读回用户记忆。要走公网请走 nginx +
   额外鉴权，不要直开端口。
2. **`AIINVITE_TOKEN` 必须有值。** 监听非本机地址而没设 token 时服务直接拒绝
   启动（`E_ARG`），不会先开端口再等人发现。
3. **store 必须挂到宿主机。** 用 volume 或 bind mount 都行，但必须在镜像外；
   `docker compose down` 之后记忆还在，这是"永久记忆"的最低要求。

Edge Function 里一轮的样子（Deno）：

```ts
const BASE = "http://aiinvite-memory:8080";
const auth = { Authorization: `Bearer ${Deno.env.get("AIINVITE_TOKEN")}`,
               "Content-Type": "application/json" };
const key = `${user.id}-${character}`;        // 一个角色一个 key

const turn = await (await fetch(`${BASE}/v1/turn`, {
  method: "POST", headers: auth, body: JSON.stringify({ key, text: message }),
})).json();

const answer = await callModel(turn.prompt);       // 你的模型调用不变

const gate = await (await fetch(`${BASE}/v1/reply`, {
  method: "POST", headers: auth, body: JSON.stringify({ key, text: answer }),
})).json();
if (!gate.allowed) return fallbackLine(gate.rule); // 闸门拒了就换成安全回复
return answer;
```

- `turn.prompt` 就是这一轮该发给模型的完整提示词（规则 + 用户卡 + 长期设定 +
  永不遗忘 + 召回 + 本次输入）。20k 证据实测 **160–210 ms**，跨进程一次 HTTP
  往返可忽略；Edge Function 的超时设到 3 s 以上，别设在 1 s。
- `gate.allowed === false` 表示这句话违反了内核设定，**不要**发出去；被拒的回复
  只留一条 `refusal` 事件，不留正文。
- 管理后台读 `GET /v1/view?key=...`（同样要 token）；`/health` 不需要 token，
  只回 `{ok, model, sessions, keys}`。

**Postgres 不能当记忆主库。** Supabase 的 `supabase-db` 很适合放用户、订单、
会话索引，但引擎要的是 POSIX 语义：字节偏移追加（证据续读）、纳秒 mtime
（判断段有没有变）、`flock` 单写者。这三条在 Postgres 里都不存在，换后端不是
配置问题而是重写（目前**没有** Postgres 后端）。所以：Postgres 存用户，
`/data/users/<key>/` 存记忆，`key` 用 `user_id` 或 `user_id-character_id` 对齐。

### 12.4 侧车 token 怎么轮换

token 是唯一凭证：拿到它就能读任何一个 `key` 的记忆。一旦进过截图、日志、
聊天记录或别人的屏幕，就当它已泄露，轮换比解释便宜。

轮换必须**三处同时换**，少一处就是记忆静默失效（turn 返回 401，而业务侧把
记忆当"可降级"，不会报错，用户看到的是"她突然不记得我了"）：

| 位置 | 改什么 |
|---|---|
| 侧车容器 | `AIINVITE_TOKEN` 环境变量（`docker run -e`） |
| Edge Function | 它把 token 写成了常量（见 12.3），同一个字符串 |
| 宿主机 `/opt/aiinvite/.env` | 只给运维脚本用，别和容器里的不一致 |

顺序很关键：**先改函数里的常量，再换容器**。反过来，中间那几秒函数拿着新
token 打旧容器，全部 401。

```bash
cd /opt/aiinvite
NEW=$(openssl rand -hex 24); echo "length=${#NEW}"   # 不要把这个值贴到任何地方

# 1) 先改函数的常量（此时旧容器仍用旧 token，业务不受影响）
sed -i -E 's/token: "[0-9a-f]{32,}"/token: "'"$NEW"'"/' \
  /opt/supabase/volumes/functions/_shared/memory.ts
grep -c "$NEW" /opt/supabase/volumes/functions/_shared/memory.ts   # 必须是 1

# 2) 再换容器（有几秒 401 窗口，函数重载前会走降级分支）
docker rm -f aiinvite-memory
docker run -d --name aiinvite-memory --restart unless-stopped \
  --network supabase_default -e AIINVITE_TOKEN="$NEW" \
  -v /opt/aiinvite/users:/data/users ai-invite-memory:0.45.0 \
  --root /data/users --model deepseek-chat --host 0.0.0.0 --port 8080

# 3) 让 isolate 重新加载 memory.ts，落盘一份给运维
docker restart supabase-edge-functions
printf 'AIINVITE_TOKEN=%s\n' "$NEW" > /opt/aiinvite/.env && chmod 600 /opt/aiinvite/.env
```

验证不是看命令回显，是看两处日志：

```bash
docker logs --tail 5 supabase-edge-functions   # 出现 aiinvite: sidecar 已就绪
docker logs --tail 5 aiinvite-memory           # 聊天后出现 POST /v1/turn
```

写常量这条本身是临时办法：edge-runtime 把 `Deno.readTextFileSync` 列进黑名单，
函数读不到挂载的文件，只能走 `Deno.env`；这套 Supabase 不是 compose 起的
（`/opt/supabase/docker` 不存在），改不了容器环境变量。等哪天能改 env，
把常量删掉、让 `config()` 只从环境变量读，token 也就不再落在代码文件里。

## 13. 数据放哪里：云盘本地可以，对象存储只能当备份

引擎对存储的要求比"能读能写"多三条：**字节偏移追加**（证据续读）、**纳秒 mtime**（判断段有没有变）、
**跨进程 flock**（`.locks/` 单写者）。它假定的是本地文件系统。

| 放法 | 能不能当主存储 | 原因 |
| --- | --- | --- |
| CVM/CBS 云硬盘（ext4/xfs） | 可以 | 语义齐全，`os.replace` 原子，`flock` 有效 |
| NAS / NFS / SMB 挂载 | **不行** | `flock` 语义不可靠、mtime 常是秒级 → 增量判定失效、锁形同虚设 |
| COS 挂载（cosfs/goofys） | **不行** | 无 flock、mtime 与 rename 语义不符、每次读走网络 |
| Windows 共享盘 | **不行** | 同上，跨平台锁不互通 |

硬挂上去会怎样（不是猜，是按代码路径推的）：

- 锁失效 → 两个进程同时写同一段，链断（`E_CHAIN_MISSING`），`verify` 能发现但不能自愈；
- mtime 粒度粗 → 索引与证据缓存每轮都判 stale → 退化成全量重建（200k 实测每轮 8.8 s，见 6.11）；
- `os.replace` 非原子 → 快照或 `chain.json` 可能半写，启动对账会拦下，但用户看到的是 `E_CHAIN_*`。

推荐形态：**主存储放云盘本地**（`/var/lib/aiinvite/users`），**云端只存备份**。

```bash
/opt/aiinvite/venv/bin/aiinvite snapshot --dir /var/lib/aiinvite/users/u1-xiaoyu --out /var/backups/aiinvite
# 然后 coscmd upload -r /var/backups/aiinvite /aiinvite-backup/   （桶设为私有）
```

容量：20k 事件约 12 MB、200k 约 119 MB（含索引），1 GB 约等于 100 个 20k 用户或 8 个 200k 用户。
备份保留 14 天见第 9 节。

如果"放云端"的意思是**要能扛住整台机器没了**，那是备份与跨可用区的问题，不是把主库搬上对象存储：
每日 snapshot 上传 COS + 换机时 `aiinvite import` 即可，`kid` 不变。

加密边界（第 9 节已提，这里重申）：生成回复需要明文，所以服务端一定有明文；
能做的是云盘加密、桶私有、GM 访问审计、目录 0700。端到端加密与 GM 后台直接冲突，要先定产品承诺。
