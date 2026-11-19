# ACCEPT-M41：称呼误学「早起」的修复与上线验收

日期：2026-11-19 · 版本：0.46.0 · tag：`v0.46-m41` · 提交：`8cfce21`

## 1. 现场症状

线上真实数据：`newtest02@qq.com`（key `cca1f42a-05ed-4c6c-819b-2c7d44402785-default`，当时 165 条事件）的用户卡记着 `称呼：早起`。

反查整库只有一处来源：

```bash
docker exec aiinvite-memory sh -c "grep -h -o '叫我[^\"]\{0,12\}' /data/users/cca1f42a-…-default/evidence/*.jsonl | sort | uniq -c | sort -rn | head -20"
# 1 叫我早起
```

用户说过「叫我早起」（使役：叫醒我），`call` 规则 `叫(我)?([^，。！？,.!?]{1,10})` 把后面的「早起」当成起名。与 v0.45 的闸门事故同源：**词面分不清「起名」和「提要求」**。

## 2. 修法

`aiinvite/persona/user_card.py` 新增 `_is_command(name, before, after)`，三条判据，命中就不当称呼：

| 判据 | 内容 | 例 |
|---|---|---|
| 命令词表 `COMMAND_ACTIONS` | 18 个日常指令 | 起床 吃饭 睡觉 回家 上班 喝水 吃药 |
| 时段副词前缀 `TIME_PREFIXES` | 早/晚/快/慢/多/少 + 长度 ≤3 | 早点睡 早起 快起 |
| 频率线索 `COMMAND_CUES` | 每天/天天/记得/别忘了/按时/准时/必须/一会儿/等下/现在，位于「叫」前 6 字内 | 每天叫我背单词 |

反向保护：候选后紧跟 `就好/就行/好了/也可以` 时不判使役——`每天叫我老周就好` 是在起名。

对**忌称**同样生效：`别叫我早起` 不再写进 `never`（不是称呼，谈不上忌讳）。

## 3. 测试

`tests/test_address_commands.py`，7 个：早起 / 背单词 / 起床 / 早点睡 都不成称呼；老周 / 宝贝 / 小王 / 每天叫我老周就好 仍然成称呼；命令不污染 never；忌称照旧。

全量 **543 tests OK**（本机 145.4 s，exit 0），`twine check` PASSED。

## 4. identity 对照实验（本次关键证据）

升级后发现 `4890db4a` 库事件数未变（98）而 kid 与更早的记录不一致，需要排除「0.46 改了身份」的可能：

- 本机：同一个库，0.45.0（PyPI wheel）与 0.46.0（源码）各算一次 → 都是 `f40036a603e2bf8fbccb923e9b80e5fe6c86ecd4814ac2c5f44c51c82d9e2ed1`
- 线上：同一份 `/opt/aiinvite/users`，用 `python:3.12-slim` + `ai-invite-memory==0.45.0` 只读算一遍：

```
0.45 4890db4a events=98  kid=0ce87cc3168d
0.45 cca1f42a events=171 kid=29f378a3abe6
```

与 0.46 输出逐个相同 → **升级没有动 kid**。较早记录里的那个 kid 是转录错误，不是代码行为。kid 由 `hash(canon, graph, models, origin, self, state)` 决定，版本号不进哈希。

`cca1f42a` 的 kid 从 `9e8b13418091` 变为 `29f378a3abe6` 属于正常变化：事件 165 → 171，内容变了身份就该变。

## 5. 上线

```bash
cd /opt/aiinvite && set -a && . ./.env && set +a
printf 'FROM python:3.12-slim\nRUN pip install --no-cache-dir ai-invite-memory==0.46.0\nENTRYPOINT ["python","-m","aiinvite.serve.http"]\n' > Dockerfile
docker build -t ai-invite-memory:0.46.0 .
docker rm -f aiinvite-memory
docker run -d --name aiinvite-memory --restart unless-stopped \
  --network supabase_default -e AIINVITE_TOKEN="$AIINVITE_TOKEN" \
  -v /opt/aiinvite/users:/data/users ai-invite-memory:0.46.0 \
  --root /data/users --model deepseek-chat --host 0.0.0.0 --port 8080
```

0.45.0 镜像保留可回滚。

## 6. 验收（线上实测）

| 库 | events | call | kid |
|---|---|---|---|
| `4890db4a`（1314@qq.com） | 98 | `老周` | `0ce87cc3168d` |
| `cca1f42a`（newtest02@qq.com） | 171 | **空**（原 `早起`） | `29f378a3abe6` |
| `5dd9bc2f` | 2 | 空 | `09d662b8491e` |
| `89b727d4` | 2 | 空 | `09d662b8491e` |

- `never`：`4890db4a` 仍为 `['宝贝']`；其余为空，符合预期
- `canon`：`4890db4a` 仍为 `['别叫我宝贝，叫我老周']`，未被重算
- 两个 2 条事件的库 kid 相同：kid 是**内容身份**，同内容必然同 kid，不是串库
- beta-check 已归档到 `/opt/backups/archived/beta-check-2026-11-19.tgz` 并删除

## 7. 已知局限（不留给以后猜）

命令词表是**兜底**，不是名字词表。`每天叫我背单词` 靠频率线索拦住；若有人说「叫我背单词」而前后没有任何线索词，仍会被误记成称呼。根治要「起名必须确认一次」（`记成规则` 已是那条通道），属于交互改动，不在本次范围。

## 8. 发布

- PyPI：https://pypi.org/project/ai-invite-memory/0.46.0/
- GitHub：tag `v0.46-m41` @ `8cfce21`；CI success（1m5s），release workflow success
