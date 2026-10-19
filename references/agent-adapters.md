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
| Claude Code | another Claude | `--main claude --backend claude` (reviewer defaults to `claude-peer`) |

These are examples, not restricted pairings. Any host with file/command tools and
Python can orchestrate any built-in backend. There is no automatic identification
of a host UI. Set `--main` explicitly and use that identity for sends, assessments,
extensions and proposals. The historical CLI default remains `codex` for compatibility.

For example, from an existing Claude conversation, after writing the briefing:

```bash
python3 /path/to/agent-chat/scripts/consult.py init \
  --room /shared/review.sqlite --cwd /absolute/project \
  --briefing-file /shared/briefing.json --main claude --backend codex
python3 /path/to/agent-chat/scripts/consult.py reply \
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
`.agents/skills/agent-chat` (Codex), `.claude/skills/agent-chat` (Claude Code),
`.pi/skills/agent-chat` (pi), or `.opencode/skills/agent-chat` (OpenCode).
Discovery differs by host/version; explicitly reading the absolute SKILL.md works
when discovery is unavailable. Reading a skill cannot add file/command capabilities
to a host that does not provide them.

Invited agents need configured local CLIs on PATH (`claude`, `codex`, `pi`,
`opencode`), or a role/consult `--cli` executable path. No shell command strings
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
| OpenCode | `run --format json`, stdin prompt | `--session ID` | Dedicated `agent-chat` agent with deny-by-default permissions; read/glob/grep/list allowed |

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
