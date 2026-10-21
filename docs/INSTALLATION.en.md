# Installation and updates

[简体中文](INSTALLATION.md) · English

[Back to README](../README.en.md)

Only the agent initiating the discussion needs this skill. Invited participants need their own configured CLIs, without a separate skill installation.
Discussions require Python 3.9+. Command installation uses the third-party [Skills CLI](https://github.com/vercel-labs/skills), whose current version requires Node.js 22.20+.

## Install with a command

Run this from the project where you want to use the skill:

```bash
npx skills add iuyaa/agent-meet --skill agent-meet
```

Select the initiating agent when prompted. Installation is project-local by default, and the installer manages skill directories and links.
Add `-g` for use across projects:

```bash
npx skills add iuyaa/agent-meet --skill agent-meet -g
```

You can also select the initiating agent explicitly and skip the prompts:

```bash
npx skills add iuyaa/agent-meet --skill agent-meet -a codex -y
```

Replace `codex` with the relevant identifier:

| Initiating agent | `-a` value |
| --- | --- |
| Codex | `codex` |
| Claude Code | `claude-code` |
| OpenCode | `opencode` |
| pi | `pi` |

Skills CLI may use a shared skill directory for several hosts instead of copying into a separate directory for each host.
Check the installer output for the actual paths. Project discussion data still goes under `.agent-meet/`.
`npx skills` installs this repository from GitHub; this project does not need a separate npm installer package.
Node.js runs the installer; Python and the agent CLIs run the discussions.

## Update

Skills CLI provides commands to check for updates and install them:

```bash
npx skills check
npx skills update agent-meet
```

Use `npx skills list` to inspect installed skills, or `npx skills list -g` for global skills.
Command installation has been verified in temporary projects. The global and update commands above follow the Skills CLI interface; actual behavior depends on its version, the host's discovery rules, and access permissions.

After updating, keep the current conversation and have the host reread `SKILL.md` from the installation path.
Close and restart any running viewer service; refreshing the browser does not reload the Python service code.
Preserve the discussion database, all state directories sharing its filename prefix, and each CLI's native session data. Continue using the original `--room`.

## Manual installation

Without Node.js, you can clone the repository into a skill directory supported by your host. For example, from a Codex project directory:

```bash
git clone https://github.com/iuyaa/agent-meet.git .agents/skills/agent-meet
```

An agent with file and command tools can also read `agent-meet/SKILL.md` from any location directly.
Discovery paths vary by host version. See [hosts and adapters](../references/agent-adapters.md) for common project paths for Codex, Claude Code, pi, and OpenCode.

When migrating from `agent-chat`, remove the duplicate old skill installation while preserving discussion data.
If you previously installed `agent-meet` manually, check the installer's target path first to avoid duplicate installations.
See [Migration](../MIGRATION.en.md).
