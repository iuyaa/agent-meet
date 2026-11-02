# Installation and updates

[简体中文](INSTALLATION.md) · English

[Back to README](../README.en.md)

Only the agent initiating the discussion needs this skill. Invited participants need their own configured CLIs, without a separate skill installation.
Discussions require Python 3.9+. Command installation uses the third-party [Skills CLI](https://github.com/vercel-labs/skills), whose current version requires Node.js 22.20+.

Implementation/test/review tasks additionally need Git 2.31+, an existing commit, and a configured Claude Code CLI. Other invited backends remain discussion-only.

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

## Automatic updates

Starting with v0.12, the skill asks the host to run a version preflight before
starting a discussion, continuing one or assigning work. It checks only Agent-Meet,
with successful metadata checks cached for one hour. A published newer version is
installed in the same directory and the host re-reads SKILL.md before continuing.
There is no background updater; the host must follow the skill instructions.

```bash
python3 /path/to/agent-meet/scripts/update.py check
python3 /path/to/agent-meet/scripts/update.py apply --force-check
```

The first command only checks. The second bypasses the cache and installs when
safe. On Windows, `py -3` may replace `python3`. Run from the project directory,
outside the skill installation. No Node.js is needed for these update commands.

Offline checks do not block the current task. Active Agent-Meet calls
hold a runtime lease, so replacement is deferred while they run. Local edits,
pinned/development Git branches and unexpected file conflicts also defer rather
than overwrite. No model CLI, model selection, credentials or native session is
replaced. Explicit requests to keep the current version take precedence.

After active calls finish, pre-v0.12 installations need one initial upgrade because their SKILL.md has no
preflight instruction. Re-run the original installation command with the same
host/global options, or use `git pull --ff-only` for an unmodified Git clone.
Do not create a second install when updating a custom manual directory.

Skills CLI also offers `npx skills check` and update management. Its behavior and
lock metadata depend on the installer version; built-in updates do not rewrite
that external installer's lock file. If its display is stale, use the original
installer to refresh the same installation. `npx skills list` / `list -g` shows
project/global installations.

Files updates verify package SHA-256 and an embedded inventory, keep extra files
and room data, preserve skill-directory symlinks and retain a full backup in the
user cache. Git updates fast-forward the official release tag on clean `main`,
preserving Git metadata and recording the previous commit. See [update details](../references/updates.md).

Keep existing databases, same-prefix state directories and CLI-native sessions;
continue with the original `--room`. Retained viewers pin loaded code/assets and do not block updates; the next
view.py start refreshes an older service without resetting the room. Legacy
viewers with room data inside the skill still block replacement to avoid copying
a database that can be written during the update.

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
