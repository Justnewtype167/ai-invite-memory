# ACCEPT-M42：多角色记忆落地 + 身份时钟修复（2026-11-25 凌晨）

版本：`0.47.0`，tag `v0.47-m42`（`fbaf458`）。这一轮是**首次改动生产架构**（之前只有部署），全部在凌晨完成，停机窗口合计约 25 秒。

## 1. 做了什么

### 1.1 记忆按角色分库（后端接上 `characterId`）

前端从 1.0.0 起已经在请求体里带 `characterId`（实测 178 次请求 100% 带），后端一直忽略它、写死 `${user.id}-default`。现在：

```ts
const rawCharacter = (body as { characterId?: unknown } | null)?.characterId;
const characterId =
  typeof rawCharacter === 'string' && /^[a-z0-9][a-z0-9_-]{0,63}$/.test(rawCharacter)
    ? rawCharacter : 'default';
const memoryKey = `${user.id}-${characterId}`;
```

- 只接受 `characters.slug` 形状（`xingci`/`yuanqi`/…，与 `chat_sessions.char_id` 完全一致）；不合格落 `default`，因为 key 会成为磁盘目录名。
- 临时 `[body-keys]` 探针已删除，换成正这一行 `[memory] character=<slug>`（不含用户 id）。

### 1.2 历史库一次性认领（按真实使用量，不靠猜）

| 账号 | 昵称 | 历史库 | 认领给 | 事件数 |
|---|---|---|---|---|
| `newtest02@qq.com` | 咸鱼茄子煲 | `cca1f42a…-default` → `-xingci` | 沈星辞（379/471 条消息，占 80%） | 552 |
| `1314@qq.com` | 爱吃香菜 | `4890db4a…-default` → `-yuanqi` | 明玥（唯一角色） | 130 |

其余三个测试账号（大娘子 / 自律练习生 ×2）保持 `-default` 不动。

已知残留：`xingci` 库里仍有约 90 条其它角色的历史对话（`yuanqi` 48 / `youya` 31 / `zhixing` 10 / 各 1 条 3 个）。证据里没有角色标记，**无法事后拆分**；新对话按角色隔离，这部分会随时间稀释。这是选 A（认领）的已知代价。

## 2. 顺手抓到并修掉的两个真 bug

### 2.1 kid 会随时钟漂移（P0，身份不稳）

发现过程：同一个 552 条证据的库，隔着几十分钟读出两个不同 kid。定位到 `HostSession.__init__` 的 `self.now = now or utc_now()`：policy 时钟被钉在**进程启动时刻**，而 `kid` 里含 `self.md` 的 `known_days = 时钟日期 − 首条证据日期`。

服务器上同一份证据、三个时钟三种身份：

```
no_now       kid=6a3315596546…  known_days: 7
policy 11-19 kid=519ea77464bd…  known_days: 2   ← 旧进程启动日
policy 12-31 kid=0f21d5054859…  known_days: 44
```

后果：跨午夜 kid 会变、重启换日期 kid 会变、快照与全量重编两条路径可能给出不同身份——直接把「可验证、可携带」这条承诺打穿。

修法：默认不注入墙钟（`self.now = now`），`Policy(now=None)` 回落到**最新一条证据的时间**；`StreamSession` 处显式 `now=self.now or utc_now()`，流式仍有时钟。`known_days` 语义从「进程活了几天」变成「记忆跨度」。故意钉时钟的调用方（测试/回放）行为不变。

### 2.2 句子尾巴被学成忌称

`cca1f42a` 的卡里曾有 `never=['了啊不许反悔']`，来自「那以后就这样叫了啊不许反悔」：`叫(我)?` 抓到 `了…` 六个字。新增 `_is_addressable`：称呼/忌称必须 1–4 字且不以 了/的/吧/啊/呢/吗/嘛/呀 开头。

## 3. 验证

- 全量 **548 tests OK**（本机 786 s，exit 0）。新增 `tests/test_kid_clock.py` 4 条、`test_address_commands.py` +1。
- 线上 `aiinvite-memory`：`0.47.0`、`running restarts=0`、`listening on 0.0.0.0:8080 (token: on)`。
- 每个库连读两次 kid 一致（`stable=True`），且等于证据时钟算出的值。
- `xingci` 库：`ev=552`、`kid=6a3315596546`、`taboo=[]`（垃圾忌称已消失）、`call='节奏大师'`（见下）。
- `yuanqi` 库：`ev=130`、`kid=64849a9df17b`、`call='老周'`、`taboo=['宝贝']`——正确的卡没被这次改动影响。
- `/health`：`{"ok": true, "model": "deepseek-chat", "sessions": 5, "keys": 5}`。

## 4. 遗留

1. **`call='节奏大师'` 仍在**：一句「请叫我节奏大师」的玩笑被永久记住。根治要「名字至少出现两次才算数」，会改到 10 余条既有测试与首轮命名体验，需要单独决策。
2. **PyPI 0.47.0 未发布**：这次没有 token，改为把本机构建的 wheel 拷到服务器 `/opt/aiinvite/buildctx/wheels/` 用 Dockerfile 安装，部署链路不依赖 PyPI；发版待 token。
3. **待确认真实请求里的 `characterId` 值**：等一条真实消息，看 `docker logs supabase-edge-functions | grep '\[memory\] character='`。若是 `xingci` 之类的 slug，则分库立即生效；若是 UUID，会落到新目录（需要再对一次）。

## 5. 回滚

镜像 `ai-invite-memory:0.46.0` 仍在；函数侧备份 `index.ts.bak-charid-20261125-*`。