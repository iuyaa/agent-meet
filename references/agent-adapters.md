# Hosts and CLI adapters

The host is the current agent reading this skill. It keeps its existing conversation
and orchestrates the Python tools. It is independent of the invited CLI backend.
Do not start another copy of the host to run the discussion.

| Host | Invited participant | Init options |
| --- | --- | --- |
| Codex | Claude | `--main codex --backend claude` |
| Claude Code | Codex | `--main claude --backend codex` |
| pi | OpenCode | `--main pi --backend opencode` |
| OpenCode | pi | `--main opencode --backend pi` |
| Codex | DeepSeek Harness | `--main codex --backend dsh` |
| Claude Code | Qwen Code | `--main claude --backend qwen` |
| Codex | ZCode | `--main codex --backend zcode` |
| Codex | Hermes Agent | `--main codex --backend hermes` |
| Hermes Agent | Qoder CLI | `--main hermes --backend qoder` |
| Codex | Antigravity CLI | `--main codex --backend antigravity` |
| Claude Code | another Claude | `--main claude --backend claude` (reviewer defaults to `claude-peer`) |

These are examples, not restricted pairings. Any host with file/command tools and
Python can orchestrate any built-in backend. There is no automatic identification
of a host UI. Set `--main` explicitly and use that identity for sends, assessments,
extensions and proposals. The historical CLI default remains `codex` for compatibility.

For example, from an existing Claude conversation, after writing the briefing:

```bash
python3 /path/to/agent-meet/scripts/consult.py init \
  --room /shared/review.sqlite --cwd /absolute/project \
  --briefing-file /shared/briefing.json --main claude --backend codex
python3 /path/to/agent-meet/scripts/consult.py reply \
  --room /shared/review.sqlite --request-id codex-1
```

The foreground result returns to that same Claude. To follow up, it sends as
`claude` and calls `reply` again. Proposal/review/extension rules stay the same.
`--reviewer` sets a participant identity independently of backend; `--model` selects
a model using that CLI's syntax. Model access comes from its existing account.

For a group, each role uses its own configuration and native conversation:

```json
[
  {"id":"pm","title":"产品经理","focus":"价值与范围","backend":"claude"},
  {"id":"architect","title":"架构师","focus":"边界与取舍","backend":"codex"},
  {"id":"dev","title":"开发","focus":"可实施性","backend":"pi"},
  {"id":"owner","title":"业务负责人","focus":"业务目标与风险","backend":"opencode"}
]
```

Use `group.py init ... --main ACTUAL_HOST --roles-file ...`; role defaults still
use Claude when `backend` is omitted. Two roles may use the same backend but must
have distinct identities and native sessions. The host can fill one requested
role with `--main-title`/`--main-focus`, instead of creating an extra copy of itself.

## Discovery and installed tools

Only the host needs the skill. Put it where that host discovers skills, for example
`.agents/skills/agent-meet` (Codex), `.claude/skills/agent-meet` (Claude Code),
`.pi/skills/agent-meet` (pi), or `.opencode/skills/agent-meet` (OpenCode).
Discovery differs by host/version; explicitly reading the absolute SKILL.md works
when discovery is unavailable. Reading a skill cannot add file/command capabilities
to a host that does not provide them.

Invited agents need configured local CLIs on PATH (`claude`, `codex`, `pi`,
`opencode`, `dsh`, `qwen`, `zcode`, `hermes`, `qoder`, `agy`), or a role/consult `--cli` executable path. No shell command strings
or extra argument injection are supported. Windows Claude/Codex npm wrappers
resolve their Node entry point; pi supports the original `@mariozechner` package
and the newer `@earendil-works` bundled entry. OpenCode requires its native platform
executable, including `opencode.exe` on Windows; unresolved wrappers fail clearly.
The skill neither installs models nor changes login settings.

## Backends, sessions and boundaries

| Backend | Foreground transport | Original conversation | Project tool limit |
| --- | --- | --- | --- |
| Claude | `-p`, JSON + structured schema | `--resume ID` | Read/Glob/Grep, no shell/edit/MCP |
| Codex | `exec`, JSONL + output schema | `exec resume ID` | Read-only sandbox; no approval bypass |
| pi | `--print --mode json`, stdin prompt | Explicit `--session` file and its header ID | read/grep/find/ls; extensions, skills and templates disabled; built-in MCP disabled when supported |
| OpenCode | `run --format json`, stdin prompt | `--session ID` | Dedicated `agent-meet` agent with deny-by-default permissions; read/glob/grep/list allowed |
| DeepSeek Harness | Official `headless --json`, stdin prompt | `--session-id ID` | Read-only preset and file inspection. An individual web task can enable public search and fetch |
| Qwen Code | `--output-format stream-json`, stdin prompt | `--resume ID` | Safe mode with the supported release's non-read built-ins excluded |
| ZCode | Official `app-server --stdio` protocol | `session/resume` with the exact ID | Plan mode with a `Read`, `Glob`, `Grep` tool allowlist |
| Hermes Agent | `chat --format stream-json`, stdin prompt | `--resume ID` | Supplied evidence and Hermes' native web toolset when available |
| Qoder CLI | `-p --output-format stream-json`, stdin prompt | `--resume ID` | `Read`, `Glob`, `Grep` plus native `WebSearch`/`WebFetch` when available and permitted |
| Antigravity CLI | `agy --input-format stream-json --output-format stream-json` | `--conversation ID` | Dedicated agent with native file inspection and public web tools as available |

On Windows, an explicit Codex executable and `codex` on PATH take precedence.
With the default `codex` selection and no PATH match, Agent-Meet checks the
registered ChatGPT Desktop package and its per-user runtime cache for a CLI
that can run `codex exec`. The CLI uses its existing authentication and
configuration. The participant starts its own meeting conversation and resumes
it on follow-up. The original host session stays in the host application.

Select `backend: antigravity` to use the configured `agy` executable. The
adapter accepts versions that support its headless streaming protocol and
validates the selected agent, final result and conversation ID. This protocol
was verified with official CLI **1.5.18**. An optional model uses Antigravity's
model identifier. The adapter stores a dedicated agent definition in the role's room
data and adds the project directory for file inspection. The agent's tool list
limits it to native read and web capabilities. Normal CLI startup still uses the
configured profile and its trusted extensions. Preserve the CLI's conversation
storage with the meeting data for continuation. [Antigravity headless protocol](https://antigravity.google/docs/cli/headless/)

Hermes targets **0.21.5** (release `v2026.9.24`) with local single-query
execution. Use the configured `hermes` CLI and its native model identifier
for `--model`. Hermes groups file reading and editing in the same toolset, so
include relevant excerpts in the briefing or meeting evidence for repository
reviews. Existing trusted Hermes profile extensions and hooks operate under the
user's Hermes configuration. Use a trusted profile for meeting participants.

Qoder targets **1.1.93** with an existing Qoder login. Use `qoder` on PATH or
set `--cli` to the official `qodercli` executable or npm bundle. Use the
CLI's model name or custom model ID with `--model`. The adapter restricts
built-in tools, disables hooks, skills and MCP for the turn, and denies
unattended permission prompts. Preserve each CLI's native session storage
alongside the Agent-Meet room when continuing Hermes or Qoder meetings.

ZCode targets the official CLI **0.17.1**, built from ZCode release `v3.18.2`.
Use `zcode` on PATH, the native
executable, or an explicit absolute path to the built `zcode.cjs` Node bundle.
For a Node bundle retain its adjacent assets and use the Node version specified
by ZCode. Configure the CLI's model provider normally. When selecting a model
for a ZCode role, use `providerId/modelId` as configured in that CLI. For a
model that requires a reasoning level, use `providerId/modelId$reasoningLevel`.

Meeting data for ZCode lives in `ROOM.peers/IDENTITY/zcode-runtime`. Keep it
with the SQLite room. The adapter scopes the session database and logs and
leaves provider configuration and credentials in their usual locations.
It sends prompts over stdio even on Windows and waits for the successful turn
event for that exact input before recording an answer. It rejects interactive
permission requests. Use the role in trusted workspaces because ZCode's
model-facing allowlist does not isolate the CLI's configured startup extensions
or trusted hooks at the operating system level.

DSH targets the official `@deepseek-ai/dsh@0.2.2-rc.5` and requires Node.js ≥24.9.
It uses a role-local `DSH_HOME` under `ROOM.peers/IDENTITY/dsh-home` to retain
its native sessions and control provider and permission configuration. Supply
`DEEPSEEK_API_KEY` through the host environment or the project's `.env` as
supported by upstream. DSH uses its `deepseek-official` provider. `--model` can
select a model supported by that provider. The per-call patch disables shell,
writes, delegation and interactive tools. A read-only task can opt in to public
web tools with `meeting.py assign --web-search`.

Qwen Code targets `@qwen-code/qwen-code@0.28.0` and requires Node.js ≥22.
Use a configured Qwen provider or its supported environment credentials. Native
recording is enabled and stored under `ROOM.peers/IDENTITY/qwen-runtime` while
the existing provider configuration remains available. Keep these directories
with the SQLite room. Windows npm wrappers for both backends resolve to their
Node entry points.

Each call checks the installed version against a supported release so changes
to upstream tool names or permission flags cannot silently change behavior.

Pi here means the **pi-mono coding agent**, now maintained at earendil-works/pi.
The adapter uses JSON session headers and completed assistant messages; it does
not export thinking blocks. The session file is `ROOM.sqlite.peers/IDENTITY/native-session.jsonl`.
Keep the complete discussion directory for continuation, including this file.
Missing/corrupt files or changed IDs cause an error, never a silent new session.
The adapter inspects `--help` to disable newer built-in MCP; old pi has no built-in
MCP and uses the same extension disable and read-tool allowlist.

OpenCode targets **1.x and 2.x** CLIs supporting the documented run interface.
It probes `--version`, then applies a per-process configuration overlay and a named
read-only discussion agent. For 2.x it adds `--standalone`: a leased service uses
this call's environment rather than an existing daemon's stale configuration.
The native sessions persist in OpenCode's own storage; keep that storage too.
MCP/custom tools cannot be used under the deny-by-default tool permissions, but
existing trusted OpenCode plugins/server configuration are not an OS sandbox.
No claim is made that arbitrary user-installed plugins are disabled. An existing
`OPENCODE_CONFIG_CONTENT` is rejected rather than overwritten. Resolve that explicit
configuration conflict before retrying; the skill does not rewrite project settings.

Pi/OpenCode do not provide this runner's native JSON schema output mode. The
runner requests one JSON response, parses completed assistant text, and applies
normal protocol validation. Malformed, truncated or failed turns produce errors
and no invented messages. OpenCode assistant messages are separated by message ID
so prose from an earlier tool step is not treated as the final response. Returned
native IDs must match the established ID for every resumed call.

These adapters were checked against upstream CLI source and simulated subprocesses.
Real authenticated Claude/pi/OpenCode calls and Windows execution have not been
verified in the development environment; test your installed version and account.
Unknown interfaces fail instead of being run as another backend.

## Adding an agent

Register an adapter in `scripts/adapters.py` with:

- `command(...)` returning an argument list and optional scoped environment.
- `parse(...)` returning a validated discussion response and native session ID.
- A reliable resume mechanism, tool restrictions, error/truncation handling and
  Windows launcher handling (or a clear native-executable requirement).

`peer.py` owns process cancellation, timeouts and the unchanged-session check.
`consult.py` and `group.py` handle caching, readiness, user-approved continuation
and protocol writes independently of the backend. Add subprocess integration tests
covering resumed replies and failure modes before claiming a new engine is supported.
A new participant CLI needs an adapter; merely changing its label is insufficient.

Source references:

- [Claude CLI](https://code.claude.com/docs/en/cli-reference)
- [pi CLI](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/cli.md)
- [pi JSON mode](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/json.md)
- [OpenCode 1.x run](https://github.com/anomalyco/opencode/blob/v1.2.27/packages/opencode/src/cli/cmd/run.ts)
- [OpenCode 2.x run](https://github.com/anomalyco/opencode/blob/dev/packages/cli/src/run/run.ts)
- [DeepSeek Harness headless](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.2-rc.5/packages/bundle/headless/README.zh.md)
- [Qwen Code headless](https://github.com/QwenLM/qwen-code/blob/v0.28.0/docs/users/features/headless.md)
- [ZCode CLI and configuration](https://github.com/zai-org/ZCode/blob/v3.18.2/apps/zcode-cli/docs/usage/README.md)

New consult/group rooms default to `PROJECT/.agent-meet/UNIQUE_DISCUSSION/discussion.sqlite`
when init omits `--room`. For skill workflows, use `storage.py prepare` first and
keep all inputs in that discussion directory. Always use the returned explicit room
for later commands; existing custom room paths remain valid and are not moved.
