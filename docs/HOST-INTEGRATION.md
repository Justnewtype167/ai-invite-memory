# 宿主接入说明（一页）

> 给写聊天前端的人看。**你只需要五个方法，模型调用由你负责。**

---

## 1. 装上

```bash
python -m pip install -e .            # 零第三方依赖
```

## 2. 一轮对话

```python
from aiinvite.host import HostSession

session = HostSession(store=Path("./memory"), model="qwen3.5:9b")

session.on_user("我叫老周，别叫我宝贝", "2026-11-01T10:00:00+08:00")
prompt = session.prompt_for("我叫老周，别叫我宝贝")   # 纯函数，不写盘
reply = my_llm(prompt)                                # 你自己调模型
verdict = session.reply(reply, "2026-11-01T10:00:05+08:00")
if not verdict.allowed:
    pass      # 已被拒绝并记为 refusal，别把这条回复发给用户
```

---

## 3. 提示词里有什么（顺序固定）

```
1  ## behavior rules              六条行为规则
2  ## who you both are            用户卡：称呼/忌讳/重要他人/承诺（≤400 字）
3  ## recent and recalled memory   最近对话 + 检索命中的记忆（预算 4k）
4  ## persona                      人格视图（特质与冲突）
5  ## this turn                    本轮用户输入
```

**第 2 项必须在第 3 项之前**，否则用户卡会被检索结果挤掉（M16 的 U3 钉死了这条）。

---

## 4. 存储与迁移

```
memory/
  evidence/seg-0001.jsonl    只追加，改一个字节就会被发现
  chain.json                 哈希链
  blobs/                     载荷（v2）
  .index/                    派生索引，删了能重建
```

**迁移 = 打包这个目录。** 换设备、换模型，人格与记忆都在里面。

```bash
python -m aiinvite.cli export ./memory ./me.aiem      # 带走
python -m aiinvite.cli import ./me.aiem ./memory2     # 到岸
python -m aiinvite.cli verify ./memory2               # 验明
```

---

## 5. 你会踩到的三件事

| 现象 | 原因 | 处置 |
|---|---|---|
| `E_RC_NO_INDEX` | 索引没建（派生数据） | 调一次 `build_index(store)`，或让 `HostSession` 自己建 |
| `E_TAMPER` | 证据被改过 | **不要绕过**，先查是谁改的 |
| `allowed=False` | 回复违反人设约束 | 换一条回复，别让闸门失效 |

---

## 6. 不要做的事

```
× 不要直接往 evidence/ 里手写 JSON
× 不要把用户卡放到上下文之后
× 不要在 prompt_for 里调模型
× 不要在闸门拒绝后仍把回复发出去
```

## 7. 最小验证

```bash
python tools/host_adapter.py --store /tmp/demo --say "你好" --dry-run
```

打印这一轮会发出去的完整提示词，不调用任何模型。

