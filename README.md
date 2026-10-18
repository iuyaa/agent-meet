# Agent Chat · 双 Agent 讨论 Skill

让两个已运行的 Codex / Claude Code / 其它有 shell 能力的 agent 围绕一个问题交流，
保留完整记录，并整理共识、分歧和待确认问题。Python 3.9+，仅使用标准库。
两个 agent 必须能读写同一个**本地磁盘文件**。

这是一个独立实现，不依赖 Golutra，也未复制其源码。不包含团队管理、任务调度、
模型启动、远程传输或自动唤醒。模型仍使用各自宿主已有的登录和权限。

## 获取

[下载独立 ZIP 包](https://github.com/iuyaa/golutra/blob/feat/agent-chat-skill/skills/agent-chat/releases/agent-chat-v0.1.0.zip?raw=true)，
解压后即可按下方说明使用，无需下载或运行 Golutra。

代码位于 `iuyaa/golutra` 仓库的 `feat/agent-chat-skill` 分支、`skills/agent-chat/` 目录。
ZIP 包包含完整 skill、通信工具、测试和演示，不包含模型或讨论数据库。

## 最快开始：不用安装也能试

解压后，把 `agent-chat` 文件夹放到本机任意工作目录。分别打开两个 agent 窗口，
允许它们在该工作目录运行 Python。把路径改为本机实际的**绝对路径**。

向第一个 agent（例如 Codex）发送：

> 请阅读 `/absolute/path/agent-chat/SKILL.md` 并按它操作。
> 创建讨论文件 `/absolute/path/work/discussion.sqlite`，参与者是 `codex`、`claude`，
> 你使用 `codex` 身份。讨论问题是：「这个项目第一版应使用 SQLite 还是 PostgreSQL？」
> 最多 12 条普通消息，讨论 10 分钟。先发言，等待另一方回复，交流后提出结论草案，
> 请对方确认，并导出报告。等待消息时继续调用 wait，不要发一条消息就结束。

向第二个 agent（例如 Claude Code）发送：

> 请阅读 `/absolute/path/agent-chat/SKILL.md` 并按它操作。
> 以 `claude` 身份加入已有讨论 `/absolute/path/work/discussion.sqlite`。
> 读取记录、回应对方、提出不同意见或追问，并审核最终草案。
> 持续等待和交流直到讨论结束，然后向我报告结果。

只需这一次手动介绍。之后消息直接通过共享讨论文件传递，无需在两个窗口之间复制。
第一窗口先完成 create，第二窗口再 join；讨论默认在创建后 10 分钟进入总结阶段，
再留 2 分钟供双方确认。创建后应及时让另一方加入。

## 可选：安装到项目的 skill 目录

将本目录完整复制到对应项目目录：

| 宿主 | 项目内路径 |
| --- | --- |
| Codex | `.agents/skills/agent-chat/` |
| Claude Code | `.claude/skills/agent-chat/` |

按宿主版本的 skill 发现方式重新载入会话。也可以一直直接指定 SKILL.md 路径。
两个宿主可以各有一份相同的 skill，但 **`--room` 必须指向同一个绝对路径**。
同名的文件若位于两个隔离沙箱中，并不是同一场讨论。

如项目由 Git 管理，把讨论目录加入 `.gitignore`，例如 `work/agent-chat-discussions/`。
工具不会改写现有项目配置，也不会自动写入用户全局 skill 目录。

## 手动检查

```bash
python3 /absolute/path/agent-chat/scripts/chat.py status --room /absolute/path/work/discussion.sqlite
python3 /absolute/path/agent-chat/scripts/chat.py stop --room /absolute/path/work/discussion.sqlite --reason '用户停止'
python3 /absolute/path/agent-chat/scripts/chat.py export --room /absolute/path/work/discussion.sqlite --output /absolute/path/work/report.md
```

Windows 上可以将 `python3` 替换为 `py -3`，路径含空格时加引号。
全部命令成功时向标准输出返回 JSON（`ok: true`），业务错误向标准错误返回 JSON
（`ok: false`），退出码为 1。`wait` 正常超时退出码仍为 0。

## 实现范围与约束

- 一个文件对应一场讨论，固定两个身份；普通消息交替发送。
- `read` / `wait` 使用显式游标，读取不删除消息；重连可从 0 重读。
- 写操作使用 SQLite 事务；request-id 防止命令重试造成重复消息。
- 结论需要引用双方真实消息；另一方可接受或驳回，未确认的草案不会标为共识。
- 接受意味着「准确记录双方意见」，允许结论里仍然有分歧。
- 默认 12 条普通消息、10 分钟讨论、2 分钟总结；最多四次结论草案。
- 每次等待最多 30 秒，默认 25 秒；模型需继续执行等待工具才会处理后续消息。
- 身份名不是登录账号；有本地文件权限的人均可操作讨论。仅用于可信的同机协作。
- 工具不验证模型输出的事实正确性，也不替模型推理。它保证消息和确认记录可追溯。
- 同一身份不要同时接入两个宿主会话；本版不提供会话锁或进程管理。

## 验证

```bash
python3 -m unittest discover -s tests -v
python3 examples/two_process_demo.py --output /absolute/path/new-demo-directory
```

演示用两个独立的 Python 进程交换预先编写的消息，验证传输与结束流程；
它不调用模型，不代表已完成真实 Codex ↔ Claude Code 联调。
实际模型协作请使用上面的两个窗口流程。

## 文件

- `SKILL.md`：给 agent 的操作规约。
- `scripts/chat.py`：独立命令行通信工具，无第三方依赖。
- `examples/conclusion.json`：结论 JSON 结构示例。
- `examples/two_process_demo.py`：两个进程的协议演示。
- `tests/test_chat.py`：事务、恢复、边界与结论流程测试。

## 许可

本包代码采用 MIT 许可，见 LICENSE。设计调研参考了 Golutra 的公开通信流程，
本包为独立实现，不包含 Golutra 的源码、图标或其它资产。
