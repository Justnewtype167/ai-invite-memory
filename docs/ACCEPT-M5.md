# M5 第一步验收（通过，待提交打 tag）

> 对象：10 个改动 + 6 个新测试文件
> 结论：**提案链路成立；「提案在→人格变、提案走→人格回来」实测成立；提案随胶囊搬家。**

---

## 1. 范围

```
改：jian/event.py（加第 6 种事件 proposal）
    jian_kernel/* 全部
    6 个新测试 P1–P6 + test_all_regression 更新
未改：jian_cn/、jian_recall/、jian/capsule.py、jian/cli.py
```

**测试：163 个（148 + 15），0 skipped。**

## 2. 我独立复现的 13 项

| 项 | 断言 | 实测 |
|---|---|---|
| P1 | 非法提案（空 model / 空 prompt_sha / 空 text） | 全拒 `E_KN_BAD_PROPOSAL` |
| P2 | 无提案 origin | `rule_only` |
| P2 | 有提案 origin | `with_proposals` |
| P2 | kid 必须不同 | A=`582180cd…` B=`aca97cad…` |
| **证明** | **提案走，人格回来** | **无提案重建 kid = `582180cd…`，与 A 完全一致** |
| P2 | 提案不得影响 canon/state | 两者逐字相同 |
| P2 | 但必须影响 self.md | 长度 +28 字符 |
| P3 | 要求提案但缺失 | `E_KN_NO_PROPOSAL` |
| P4 | `allow_fallback` | `origin=rule_fallback` |
| P4 | 三种 origin 三个 kid | `582180cd` / `aca97cad` / `a7a53fea`，互不相同 |
| P5 | `target=canon` | `E_KN_BAD_TARGET` |
| P5 | 配额 12 → 8 | **accepted=8, rejected=4** |
| P6 | 跨进程（不同 PYTHONHASHSEED） | kid 一致 |

## 3. 补测：提案能不能随胶囊搬家

官方测试没覆盖这条，我另外测了——**它是「换设备还是同一个人」的前提**：

```
提案随胶囊导出     PASS（胶囊内 jsonl 含 proposal 事件）
设备 B verify      PASS（events=3）
设备 B 重算 kid    PASS（A=`3fa542c8…` B=`3fa542c8…`）
设备 B origin      PASS（with_proposals）
```

提案进了证据层，所以它天然被打包、被哈希、被搬运。这是选「提案即证据」而不是「提案放旁路文件」的直接收益。

## 4. 三行证明（这是本步的全部意义）

```
无提案         → kid=582180cd4b21  origin=rule_only
加 1 条提案     → kid=aca97cad2b55  origin=with_proposals
删掉那条提案    → kid=582180cd4b21  origin=rule_only
```

前两行只说明「加了东西会变」；**第三行说明「人格由证据唯一决定」**。

## 5. 待办

| 级别 | 项 |
|---|---|
| 必修 | 提交 16 个文件并打 tag `v0.6-m5` |

## 6. 这一步之后，架构上还差什么

```
✅ 提案可进、可审、可搬、可重算
⬜ 真模型接入（M5 第二步）—— 唯一还没做的
⬜ PCS 度量（换模型后「像不像同一个人」）
⬜ 继承与哀悼协议（M6）
```

**接模型之前，链路已经是对的。** 这意味着一件很实际的事：
第一次接模型时如果 `kid` 乱了，问题一定在模型那一侧，不在数据层。

