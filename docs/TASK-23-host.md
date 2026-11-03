# TASK-23 · 宿主接入（M17）

> 目标：让**任何聊天前端**用最少代码接入这套地基。
> 这是把 M1–M16 变成「能被使用的东西」的那一层。

---

## 0. 一句话

```
宿主只需要做三件事：写事件、取提示词、发出回复。
其余（身份、人格、记忆、闸门）都由地基负责。
```

---

## 1. 一个类，五个方法

```python
class HostSession:
    def __init__(self, store: Path, model: str, budget: int = 4096,
                 now: str | None = None) -> None: ...

    def on_user(self, text: str, t: str) -> None:
        """记录用户一句话（写证据，不写人格）。"""

    def on_assistant(self, text: str, t: str) -> None:
        """记录 AI 一句话。"""

    def prompt_for(self, user_text: str) -> str:
        """返回这一轮该发给模型的完整提示词。"""

    def reply(self, text: str, t: str) -> Verdict:
        """过闸门后记录并返回判定；被拒则只记录 refusal。"""

    def stats(self) -> dict[str, int]: ...
```

**没有第六个方法。** 多一个都说明职责没分对。

---

## 2. 一轮对话的完整时序

```
① 用户说话      host.on_user(text, t)
② 要提示词      prompt = host.prompt_for(text)
③ 宿主调模型     （地基不调模型——这是宿主的职责）
④ 模型回复      host.reply(response, t)
⑤ 落盘完成      store 里多两条 turn 事件
```

**地基在②里做完所有事**：读证据、算人格、取上下文、拼用户卡、加规则。

---

## 3. `prompt_for` 的拼装顺序（固定，不许改序）

```
1 行为规则        六条可执行规则的自然语言版
2 用户卡           ≤400 字符，固定钉在上下文首位
3 上下文           最近对话 + 检索命中的记忆 + 时间触发（预算 4k）
4 人格视图         PersonaView.self_md（特质/冲突，L2 渲染）
5 本轮用户输入
```

**第 2 项必须在第 3 项之前。** 用户卡是「它是谁、你是谁」的锚，
不能被检索结果挤掉——M16 的 U3 已把这条钉死。

---

## 4. 三条硬约束

| # | 约束 | 理由 |
|---|---|---|
| 1 | **地基不调模型** | 宿主可能用任何模型、任何协议；核心包零网络是底线 |
| 2 | **`prompt_for` 只读，不写证据** | 提示词可以被重算多次，落盘只能一次 |
| 3 | **`reply` 被拒时仍写 refusal** | 拒绝必须留痕（M13） |

---

## 5. 验收（六个）

| # | 测试 | 断言 |
|---|---|---|
| H1 | `test_round_trip` | on_user → prompt_for → reply，之后证据 +2 条；`kid` 与「直接 append 同样两条」的孪生 store 相同（**turn 是内核事件，会改 state，所以 kid 会变——这是我原文写错的一条**） |
| H2 | `test_prompt_order` | 用户卡出现在上下文之前；规则在最前；本轮输入在最后 |
| H3 | `test_prompt_is_pure` | 连调两次 `prompt_for` 不写任何事件；返回字节相同 |
| H4 | `test_refusal_recorded` | 违规回复 → `reply` 返回 `allowed=False`，证据多一条 `refusal`，正常回复不产生 refusal |
| H5 | `test_budget_respected` | 20 万条证据下 `prompt_for` 的 token ≤ budget（按 `estimate_tokens`） |
| H6 | `test_all_regression` | 现有全部测试全绿；新代码不改任何既有包 |

---

## 6. 参考实现位置

```
tools/host_adapter.py     ← 可运行的参考适配器（不放进核心包）
docs/HOST-INTEGRATION.md  ← 给前端工程师的一页接入说明
```

**不进 `aiinvite.*` 包**：它是宿主侧的胶水，不是地基的一部分。

---

## 7. 禁止

1. 不许在 `HostSession` 里调模型
2. 不许让 `prompt_for` 写数据
3. 不许把用户卡放到上下文之后
4. 不许跳过闸门直接写助手回复

---

## 8. 完成定义

```
python -m unittest discover -s tests -v      # 全绿
python tools/host_adapter.py --store /tmp/x --say "我叫老周" --dry-run
```

`--dry-run` 打印这一轮会发出去的完整提示词，**不上屏任何真实 API key**。

