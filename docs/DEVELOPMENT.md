# Meet 开发说明

简体中文 · [English](DEVELOPMENT.en.md)

[返回首页](../README.md) · [操作指南](USAGE.md)

Meet 使用 Python 标准库、SQLite 和本地静态页面。无需 Golutra 应用或前端构建。
仓库根目录也是 skill 根目录。

## 代码位置

| 文件 | 职责 |
| --- | --- |
| `scripts/chat.py` | 事件协议、草稿、审核、导出和 CLI 入口 |
| `scripts/consult.py` | 保留原主持人的逐次双人调用 |
| `scripts/group.py` | 多角色轮次、并行调用、全体审核 |
| `scripts/lifecycle.py` | 结束前评估、用户决定追加、原房间续聊 |
| `scripts/finalization.py` | 最后审核意见处理与最终结论归档 |
| `scripts/storage.py` | 项目内独立讨论目录及 Git 忽略 |
| `scripts/adapters.py` | Claude、Codex、pi、OpenCode 的命令和输出适配 |
| `scripts/peer.py` | 公共进程控制、超时、停止及原生 ID 校验 |
| `scripts/view.py`、`web/` | 本地网页服务与消息展示 |

`conclusion_status` 继续表达草案是否获审核接受；前台讨论获全体接受后进入
`phase=finalizing`。只有 `finalization_status=finalized` 才表示主持人已保存最终结论。
页面与导出使用 `latest_finalization.body.conclusion`。新增事件保留原草稿和审核原文，
续聊后旧结果作为历史。未使用 lifecycle 的原始手动/后台协议维持原有行为。

工具验证意见来自当前审核、每份审核均有处理记录、依据来自真实消息、原生 ID 未被替换。
它不判断自然语言是否完整或事实是否正确；这些仍需要主持人结合项目证据评估。

## 本地验证

```bash
python3 -m unittest discover -s tests -v
```

测试使用真实临时文件、SQLite 和模拟 CLI 子进程，不调用付费模型。
可选浏览器检查需要开发环境已安装 Playwright 与 Chromium，运行 skill 无需安装它们：

```bash
CHROMIUM=/path/to/chromium node tests/browser_view.cjs
CHROMIUM=/path/to/chromium node tests/browser_group.cjs
```

详细范围、结果和实机限制见 [验证记录](../VALIDATION.md)。

## 扩展与贡献

新增 agent 后端时，先阅读 [适配器说明](../references/agent-adapters.md)。
命令构造和输出解析属于 adapters，停止、超时及会话一致性由公共层管理。
必须覆盖原生会话恢复、错误与截断、重复请求及中断后的行为。

本包为独立实现，未复制 Golutra 应用源码或资产。历史来源见
[迁移说明](../MIGRATION.md)，原始后台模式见[可选模式](../references/alternative-modes.md)。
