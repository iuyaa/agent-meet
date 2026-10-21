# 安装与更新

[返回首页](../README.md)

只有发起讨论的 agent 需要安装本技能。受邀参与者需要配置好各自 CLI，
不需要再安装一份 skill。讨论运行需要 Python 3.9+；命令安装使用第三方
[Skills CLI](https://github.com/vercel-labs/skills)，其当前版本需要 Node.js 22.20+。

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

## 更新

Skills CLI 提供更新检查和更新命令：

```bash
npx skills check
npx skills update agent-meet
```

安装后用 `npx skills list` 查看已安装技能；全局技能可用 `npx skills list -g`。
本项目已在临时项目中验证命令安装；上面的全局选项和更新命令遵循 Skills CLI 接口，
实际行为取决于安装器版本、宿主发现规则及访问权限。

更新后保留当前会话，让主持人重新读取安装路径中的 `SKILL.md`。
已有网页服务先关闭再启动；只刷新浏览器不会更新已加载的 Python 服务代码。
完整保留原讨论数据库、同名前缀状态目录和各 CLI 原生会话，继续使用原 `--room`。

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
