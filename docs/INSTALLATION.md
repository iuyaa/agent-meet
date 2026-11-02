# 安装与更新

简体中文 · [English](INSTALLATION.en.md)

[返回首页](../README.md)

只有发起讨论的 agent 需要安装本技能。受邀参与者需要配置好各自 CLI，
不需要再安装一份 skill。讨论运行需要 Python 3.9+；命令安装使用第三方
[Skills CLI](https://github.com/vercel-labs/skills)，其当前版本需要 Node.js 22.20+。

实现、测试、Review 任务还需要 Git 2.31+、至少一个 Git 提交，以及配置好的 Claude Code CLI；其它受邀后端目前用于讨论。

## 命令安装

在需要使用的项目目录执行：

```bash
npx skills add iuyaa/agent-meet --skill agent-meet
```

按提示选择发起端。默认安装到当前项目，安装器管理技能目录和链接。
需要跨项目使用时，加 `-g`：

```bash
npx skills add iuyaa/agent-meet --skill agent-meet -g
```

也可以明确指定发起端并跳过交互，例如：

```bash
npx skills add iuyaa/agent-meet --skill agent-meet -a codex -y
```

其它发起端将 `codex` 换成下面的标识：

| 发起端 | `-a` 参数 |
| --- | --- |
| Codex | `codex` |
| Claude Code | `claude-code` |
| OpenCode | `opencode` |
| pi | `pi` |

Skills CLI 可能为多个宿主使用共享技能目录，而不是逐一复制到宿主专属目录；
具体路径以安装结果为准。这不影响项目讨论数据仍放在 `.agent-meet/` 下。
`npx skills` 从 GitHub 安装这个仓库，本项目无需发布额外的 npm 安装包。
Node.js 用于安装器，讨论仍由 Python 和各 agent CLI 执行。

## 自动检查与更新

从 v0.12 开始，技能会引导主持人在发起讨论、继续原会话或安排任务前执行版本检查。
成功检查的元数据缓存一小时；发现已正式打包的新版时，更新当前安装目录，
重新读取 `SKILL.md` 后继续。没有常驻更新服务，实际执行取决于宿主是否遵循技能指引。

```bash
python3 /path/to/agent-meet/scripts/update.py check
python3 /path/to/agent-meet/scripts/update.py apply --force-check
```

第一条只检查；第二条绕过缓存，有新版且当前可更新时直接安装。
Windows 可用 `py -3`。请在项目目录执行，不要把当前工作目录设为技能目录。
这两条更新命令只需要 Python，不依赖 Node.js。

断网不会阻塞原任务。有正在执行的 Agent-Meet 工具调用时会延后替换；
本地修改、固定版本、开发分支或文件冲突也会保留原样。
只更新 Agent-Meet，不升级模型 CLI，不改变模型、账号或原生会话。
明确要求不更新或固定版本时，优先遵守用户要求。

v0.12 之前的安装没有这段引导，需等调用结束后先升级一次：沿用原宿主和全局/项目选项，
重新执行原安装命令；未修改的 Git 克隆也可执行 `git pull --ff-only`。
自定义的手动安装目录应更新原目录，避免另装一份。

Skills CLI 也提供 `npx skills check` 等更新管理功能；其行为和锁文件格式取决于安装器版本。
内置更新不改写外部安装器的锁文件；若安装器显示仍旧，使用原安装器刷新同一安装即可。
用 `npx skills list` 查看项目技能，全局技能用 `npx skills list -g`。

普通目录更新会校验 SHA-256 和文件清单，保留额外文件、讨论数据和目录软链接，
并在用户缓存中留存完整备份。Git 安装要求干净的 `main` 分支及官方 origin，
只快进到正式版本标签，保留 Git 元数据和旧提交号。详见[更新机制](../references/updates.md)。

已有数据库、同名前缀状态目录和 CLI 原生会话均保留，继续使用原 `--room`。
普通保留页面固定使用启动时的代码和资源，不阻止更新；下次启动该房间页面时，旧版服务会自动换新，不重置讨论。
只有把 room 数据放在技能目录内的旧页面仍会阻止更新，以免复制正在写入的数据库。

## 手动安装

没有 Node.js 时，也可以将仓库克隆到宿主支持的 skill 目录，例如 Codex 项目目录：

```bash
git clone https://github.com/iuyaa/agent-meet.git .agents/skills/agent-meet
```

也可让有文件和命令工具的 agent 直接读取任意位置的 `agent-meet/SKILL.md`。
宿主的发现路径因版本而异，Codex、Claude Code、pi、OpenCode 的常见项目路径见
[宿主与适配器说明](../references/agent-adapters.md)。

从旧 `agent-chat` 迁移时，移除重复的旧技能安装，保留原讨论数据。
如果此前手动安装过 `agent-meet`，先确认安装器将写入的目标，避免保留两份重复技能。
详见[迁移说明](../MIGRATION.md)。
