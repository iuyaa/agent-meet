# Configurable roles and discussion rounds

Use this flow when the user specifies roles, requests multiple participants, or
sets a number of discussion rounds. The existing main conversation remains the
host. For a plain two-agent exchange without these options, `consult.py` remains
available. Never initialize both modes into the same room.

## Interpret the user's request

Users can set everything in their initial natural-language instruction, e.g.:

> $agent-chat 评审 glp-content 的 agent 改造方案，最多讨论 3 轮。
> 我当前的 Codex 主持，请产品经理、架构师、开发、用户、业务负责人五个角色参加。
> 默认全部使用 Claude，架构师改用 Codex；最后汇总共识、分歧和待验证问题。

- A role is a title plus a clear focus, independent of the CLI backend/model.
- Default additional roles use **Claude**, as requested by the user. Override
  each role's `backend` with `codex` or `claude` if specified. Do not silently mix.
- Each additional role gets its own native session and independently resumed
  context. Codex roles require an installed/configured local Codex CLI. Claude
  roles require the Claude CLI. The current host itself needs no additional CLI.
- By default, five requested roles means five roles **plus the current host**.
  If the user assigns the current host one of the roles (e.g. architect), use
  `--main-title 架构师 --main-focus ...` and create only the other four in the file.
  You must adopt that host role in your own judgement and follow-ups.
- A round is **one host message plus one reply from each additional role**.
  The opening briefing is the first host message. A three-round five-role room
  has at most 18 ordinary messages. Proposal/review events are additional and do
  not consume discussion rounds. Default 3 rounds, supported range 1–20.
- A maximum allows early conclusion after a complete round if the question is
  resolved. If the user explicitly requires exactly N rounds, complete N unless
  stopped, timed out or blocked; do not fill missing replies with invented text.
- Roles such as "user" are simulated perspectives; they are not actual customer
  research. Record real user input only when supplied by the user or evidence.

No extra confirmation is needed for a clear request. Use a fresh room path,
keep the user's original scope, and tell them the roles, engines and round limit.

## Initialize

Prepare the same eight-field context briefing described in SKILL.md. Then write
a UTF-8 roles JSON. `examples/roles.json` contains the five roles above. Each role:

```json
{
  "id": "architect",
  "title": "架构师",
  "focus": "审视系统边界、方案取舍及维护成本，结合真实代码提出依据",
  "backend": "claude"
}
```

`id` must be unique and use 1–48 ASCII letters, digits, `_` or `-`, distinct from
the host. Required fields are `id`, `title`, `focus`; backend defaults to Claude.
Optional `cli` selects an executable path (not a shell command), and `model`
selects a model supported by that CLI/account. Omitting model uses its current
configuration. Do not invent model identifiers. A single additional role works
for configurable two-person discussions. Supported additional roles: 1–8.

```bash
python3 /path/to/agent-chat/scripts/group.py init \
  --room /shared/new-group.sqlite --cwd /absolute/path/project \
  --briefing-file /shared/briefing.json --roles-file /shared/roles.json \
  --rounds 3 --minutes 30
python3 /path/to/agent-chat/scripts/view.py start --room /shared/new-group.sqlite --open
```

Default main identity is `codex`, title `主持人`. Initialization validates all
CLIs before creating the room, saves the configuration and opening briefing, but
does not call any model. Exact repeated initialization is idempotent; changing
roles, project, briefing or round budget requires a fresh room. Do not rewrite
roles in a running discussion or convert an older room in place.

## Run one round and remain in the current host turn

```bash
python3 /path/to/agent-chat/scripts/group.py round \
  --room /shared/new-group.sqlite --request-id discussion-1
```

This FOREGROUND tool execution calls every due role in parallel and returns their
recorded replies and errors. Keep waiting for this execution if the host returns
a running session ID. Do not end your turn at "started" or ask the user to say
"continue". No replacement host or background conversation manager is started.

All roles in this batch see the same saved snapshot. They do not see other
replies arriving during that batch. From the second round, each sees all prior
rounds' recorded views, their own resumed native context, and your new host
message. This makes cross-examination possible without arrival-order bias.
The same snapshot is preserved for partial retries or later `--only` calls in
this logical round/proposal, so a retry does not gain access to same-round answers
or other votes on the proposal before writing its own response.

Evaluate all replies against your original long-running context. Add missing
constraints, identify contradictions, and ask roles to respond to one another:

```bash
python3 /path/to/agent-chat/scripts/chat.py send \
  --room /shared/new-group.sqlite --as codex --request-id host-2 \
  --text-file /shared/host-follow-up.txt
python3 /path/to/agent-chat/scripts/group.py round \
  --room /shared/new-group.sqlite --request-id discussion-2
```

Use unique request IDs. A successful or old batch retry returns existing records
without extra model calls or moving cursors backwards. If some roles fail, the
other actual replies remain recorded. Inspect the errors/logs, fix the cause,
then use a NEW batch ID: only currently missing roles are called. `--only ID`
can select one due role. A retry of a ready, uncommitted response with its
original ID can commit it without another model call. Failed/interrupted IDs
are not blindly retried. Do not move to another host round while roles are missing.

## Conclude and gather every role's review

Before any draft, and particularly after the final planned round, follow
[readiness and continuation](continuation.md): record the original host's
assessment deciding whether the question can be concluded or needs further
discussion. Do not let the round cap make that judgement. If extra budget is
needed, explain why and wait for the user's decision, then extend the SAME room
and resume the original sessions. Do not reinitialize roles.

After a complete round and a fresh `conclude` assessment, the original host prepares the same conclusion JSON
schema as SKILL.md. Cite real message IDs from **the host and EVERY role**.
Preserve disagreements and unknowns. Only the original host may propose.

```bash
python3 /path/to/agent-chat/scripts/chat.py propose \
  --room /shared/new-group.sqlite --as codex --request-id host-conclusion-1 \
  --file /shared/conclusion.json
python3 /path/to/agent-chat/scripts/group.py round \
  --room /shared/new-group.sqlite --request-id review-1
```

The same round command now asks every pending role to review this proposal.
Only all roles explicitly accepting marks the record confirmed. One acceptance,
a majority, no response or timeout is insufficient. One rejection keeps the
record disputed. Wait for all reviews before revising; address the objections
and reassess before a new draft under a new ID, at most four drafts per continuation period. Approval means
the record reflects the role's view, not that all advice is factually validated.

Use `chat.py export/stop/read` as in SKILL.md. Reads are paginated; follow
`next_after` until `has_more` is false. The viewer shows role titles, engines,
per-role progress, rounds and actual review counts. Fold settings survive polls
and browser refreshes. The page does not inject messages into the original UI.

Default discussion window: 30 minutes plus 10 minutes for review. Per-role CLI
timeout defaults to 180 seconds (`--turn-timeout 1–600`). More roles use more
model calls/account quota. Reaching the round cap stops new ordinary messages;
the conclusion/review window remains. If time expires mid-round or a role cannot
respond, report the partial record; never fabricate a finished round or approval.
Stopping the room cancels active role CLIs. Logs and batch caches are in
`ROOM.sqlite.group/`; role sessions and process state are in `ROOM.sqlite.peers/`.
