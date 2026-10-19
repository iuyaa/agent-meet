# Agent Chat · 双 Agent 讨论 Skill

自动启动 Codex 和 Claude 两个后台参与者，围绕一个问题交流，
保留完整记录，并整理共识、分歧和待确认问题。发起窗口只负责发起与等待结果。
无需手动传邀请语，也无需在某一轮结束后再提醒 agent「继续」。
也保留当前窗口直接参与和两个已打开会话手动加入的方式。
Python 3.9+，仅使用标准库；讨论记录保存在共享的本地磁盘文件中。

这是一个独立实现，不依赖 Golutra，也未复制其源码。不包含团队管理、任务调度或
远程传输。自动接入使用本机 Codex/Claude CLI 已有的登录和模型配置。

## 获取

[下载独立 ZIP 包 v0.3.0](https://github.com/iuyaa/golutra/blob/feat/agent-chat-skill/skills/agent-chat/releases/agent-chat-v0.3.0.zip?raw=true)，
解压后即可按下方说明使用，无需下载或运行 Golutra。

代码位于 `iuyaa/golutra` 仓库的 `feat/agent-chat-skill` 分支、`skills/agent-chat/` 目录。
ZIP 包包含完整 skill、通信工具、测试和演示，不包含模型或讨论数据库。

## 最快开始：只在一个窗口发起

前提：本机 `codex`、`claude` 两个 CLI 都已安装并配置好登录/服务，能够正常调用模型。
只有 Codex 桌面应用而没有可用 Codex CLI 时，也需要先提供对应的 CLI 可执行文件。
更新 skill 后重新打开或重新加载发起会话，然后对 Codex 说：

> $agent-chat 和 Claude 讨论一下，glp-content 的 agent 应该怎么改。

也可以不安装，直接说：

> 请读取 `/absolute/path/agent-chat/SKILL.md`。
> 围绕「这个项目的 agent 应该怎么改」创建双边托管讨论，自动启动 Codex 和 Claude。
> 项目目录是 `/absolute/path/to/project`。只讨论，不修改业务代码，最后导出结论。

默认流程会建立讨论并启动两个新的 CLI 会话，两边自行读取、回复、审核结论和结束，
由控制进程导出报告。发起 agent 调用一个等待结果的工具，完成后读取并展示报告。
**无需复制邀请语、无需手动打开第二个窗口，也无需给后台双方另装 skill。**
每个参与者后续回合恢复自己的原生会话。它们可以读取项目，讨论模式不修改业务代码。

即使发起回合提前结束，后台双方仍可完成讨论，报告会保存在启动结果给出的路径中。
工具不接管已有窗口，也不能强制向一个已经结束回合的 UI 主动插入消息。
正常使用时发起窗口等待原工具执行完成；若宿主结束了工具等待，可稍后查询状态或直接打开报告。

因此，v0.3.0 省掉的是**讨论对人工「继续」的依赖**，没有增加桌面窗口控制或通知功能。

也可直接运行工具：把问题保存为 UTF-8 文件 `question.txt`，再执行：

```bash
python3 /absolute/path/agent-chat/scripts/discuss.py run --room /absolute/path/work/new-discussion.sqlite --cwd /absolute/path/project --topic-file /absolute/path/work/question.txt
```

`run` 会先输出启动事件，最后返回完成状态及报告路径。若宿主工具返回运行中的会话 ID，
发起 agent 应持续等待同一个执行，不应提前结束并要求你发「继续」。
也可用 `start` 后台发起，再用 `wait --timeout 25` 或 `status` 查询。

如 CLI 不在 PATH，启动时可指定 `--codex-cli` / `--claude-cli` 的可执行文件路径。
Windows 的原生可执行文件和标准 npm 包装脚本均有适配，后者解析为 Node 入口运行。
旧版 CLI 若不支持结构化输出等参数，需要更新 CLI。

## 可选：两个已打开的窗口手动加入

解压后，把 `agent-chat` 文件夹放到本机任意工作目录。分别打开两个 agent 窗口，
允许它们在该工作目录运行 Python。把路径改为本机实际的**绝对路径**。

向第一个 agent（例如 Codex）发送：

> 请阅读 `/absolute/path/agent-chat/SKILL.md` 并按它操作。
> 本次使用两个已打开窗口手动接入，不要自动启动任何参与者。
> 创建讨论文件 `/absolute/path/work/discussion.sqlite`，参与者是 `codex`、`claude`，
> 你使用 `codex` 身份。讨论问题是：「这个项目第一版应使用 SQLite 还是 PostgreSQL？」
> 最多 12 条普通消息，讨论 10 分钟。先发言，等待另一方回复，交流后提出结论草案，
> 请对方确认，并导出报告。等待消息时继续调用 wait，不要发一条消息就结束。

向第二个 agent（例如 Claude Code）发送：

> 请阅读 `/absolute/path/agent-chat/SKILL.md` 并按它操作。
> 以 `claude` 身份加入已有讨论 `/absolute/path/work/discussion.sqlite`。
> 读取记录、回应对方、提出不同意见或追问，并审核最终草案。
> 持续等待和交流直到讨论结束，然后向我报告结果。

这是保留的手动接入方式；默认双边托管时不需要这一步。
手动模式只需这一次介绍。之后消息直接通过共享讨论文件传递，无需在两个窗口之间复制。
第一窗口先完成 create，第二窗口再 join；讨论默认在创建后 10 分钟进入总结阶段，
再留 2 分钟供双方确认。创建后应及时让另一方加入。

## 可选：安装到项目的 skill 目录

将本目录完整复制到对应项目目录：

| 宿主 | 项目内路径 |
| --- | --- |
| Codex | `.agents/skills/agent-chat/` |
| Claude Code | `.claude/skills/agent-chat/` |

按宿主版本的 skill 发现方式重新载入会话。也可以一直直接指定 SKILL.md 路径。
双边托管时，只需发起宿主安装 skill。手动模式下两个宿主可以各有一份相同的
skill，但 **`--room` 必须指向同一个绝对路径**。
同名的文件若位于两个隔离沙箱中，并不是同一场讨论。

如项目由 Git 管理，把讨论目录加入 `.gitignore`，例如 `work/agent-chat-discussions/`。
工具不会改写现有项目配置，也不会自动写入用户全局 skill 目录。

## 手动检查

```bash
python3 /absolute/path/agent-chat/scripts/chat.py status --room /absolute/path/work/discussion.sqlite
python3 /absolute/path/agent-chat/scripts/discuss.py status --room /absolute/path/work/discussion.sqlite
python3 /absolute/path/agent-chat/scripts/discuss.py wait --room /absolute/path/work/discussion.sqlite --timeout 25
python3 /absolute/path/agent-chat/scripts/discuss.py stop --room /absolute/path/work/discussion.sqlite
python3 /absolute/path/agent-chat/scripts/chat.py stop --room /absolute/path/work/discussion.sqlite --reason '用户停止'
python3 /absolute/path/agent-chat/scripts/chat.py export --room /absolute/path/work/discussion.sqlite --output /absolute/path/work/report.md
python3 /absolute/path/agent-chat/scripts/peer.py status --room /absolute/path/work/discussion.sqlite --as claude
```

双边托管优先使用 `discuss.py run/start/status/wait/stop`。任务状态位于 `PATH.job/`，
各参与者状态和日志位于 `PATH.peers/`。`job.state` 为 completed / failed / stopped / expired
时结束；成功启动不等于讨论已完成。失败会停止另一方并导出已有记录，不伪造结论。
`status` / `wait` 命令成功表示查询完成，应检查返回的任务状态；`run` 遇到任务失败会返回退出码 1。

以下为可选的单边托管接口，适用于希望当前窗口直接参与的用户：
`peer.py start --room PATH --as claude --cwd PROJECT` 自动加入并启动后台参与者。
`--backend codex` 也可托管单个 Codex 参与者。
`peer.py stop --room PATH --as claude` 仅停止该参与者。`chat.py stop` 结束整场讨论，
后台参与者会随之停止。管理状态、原生会话 ID 和每轮日志在 `PATH.peers/claude/` 中。
启动返回成功表示后台进程已加入；模型认证或响应是否成功，要以消息和后续状态为准。
`failed` 状态会给出错误与日志位置；不会把 CLI 错误、无响应或超时当成同意。

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
- 手动模式每次等待最多 30 秒，默认 25 秒；托管模式的消息等待由后台运行器处理。
- 身份名不是登录账号；有本地文件权限的人均可操作讨论。仅用于可信的同机协作。
- 工具不验证模型输出的事实正确性，也不替模型推理。它保证消息和确认记录可追溯。
- 后台参与者由 OS 文件锁避免同一身份重复启动；手动会话不要占用它的身份。
- Claude 参与者只启用 Read/Glob/Grep；Codex 参与者使用 read-only 沙箱。通信写入由 Python 工具完成。
- 使用两个 CLI 的模型调用按各自已有账户/服务的规则计费，工具本身不附带模型访问。
- 双边托管启动两个新会话，不直接继承发起窗口上下文；skill 会把必要背景写进讨论问题。
- 重复运行同一托管讨论路径会返回现有任务或结果；新问题应使用新路径。

## 验证

```bash
python3 -m unittest discover -s tests -v
python3 examples/two_process_demo.py --output /absolute/path/new-demo-directory
```

演示用两个独立的 Python 进程交换预先编写的消息，验证传输与结束流程；
它不调用模型，不代表已完成真实 Codex ↔ Claude Code 联调。
自动接入与双边托管测试使用模拟 Codex / Claude CLI，覆盖双方自动讨论、会话恢复、
前台等待结果、后台完成并导出、失败终止另一方、重复启动和停止。
当前环境有 Codex CLI，其命令参数解析已验证；但没有 Claude CLI，真实双模型联调和
Windows 上的实际进程启动仍需在对应设备验证。

## 文件

- `SKILL.md`：给 agent 的操作规约。
- `scripts/chat.py`：独立命令行通信工具，无第三方依赖。
- `scripts/peer.py`：自动启动与管理新的 Codex / Claude 后台参与者。
- `scripts/discuss.py`：双边托管、等待结果、状态查询与自动导出。
- `examples/conclusion.json`：结论 JSON 结构示例。
- `examples/two_process_demo.py`：两个进程的协议演示。
- `tests/test_chat.py`：事务、恢复、边界与结论流程测试。
- `tests/test_peer.py`：模拟 CLI 的自动接入与失败处理测试。
- `tests/test_discuss.py`：无需发起窗口继续参与的完整后台讨论测试。

Claude 接入参数参考：[官方 CLI 参考](https://code.claude.com/docs/en/cli-reference)、
[程序化使用与结构化输出](https://code.claude.com/docs/en/headless)。

## 许可

本包代码采用 MIT 许可，见 LICENSE。设计调研参考了 Golutra 的公开通信流程，
本包为独立实现，不包含 Golutra 的源码、图标或其它资产。
