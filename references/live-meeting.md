# In-meeting invitations and tasks

The original host can invite a participant or assign work in the room that is
already open. A managed `consult.py` room switches to group mode on the first
successful invitation or assignment. Keep its SQLite path, viewer, event IDs and
native peer session. From then on use `group.py status` and `group.py round` for
discussion. Manually joined and background-run rooms use their original protocol.

In the examples, `ROOM` is the existing SQLite path and `HOST` is the original
host ID. Use absolute script and input paths, quoted when needed. Write input
files beside the existing room. Use a unique request ID per action. An exact
repeat of an already recorded action can return its receipt. After a failed call,
inspect its output and use a new request ID for an explicit retry.

## Invite a role

Use a role object like the following in `guest.json`.

```json
{"id":"developer","title":"开发","focus":"核实接口限制、实现成本及验收条件","backend":"claude"}
```

Choose a unique ID and describe the role's responsibilities. The default backend
is Claude. Use `backend`, `cli` and `model` to match the user's requested local
configuration. A room can have up to eight invited roles. Write a short UTF-8
`guest-context.md` with the purpose of the invitation, the decisions already made
and the questions to address. Optionally cite up to eight room event IDs.

```bash
python3 scripts/meeting.py invite --room ROOM --as HOST --request-id invite-development \
  --role-file guest.json --context-file guest-context.md --evidence-event 4
python3 scripts/group.py round --room ROOM --request-id round-with-development
```

The guest joins the current round. If other calls have already started that round,
those roles keep their frozen input. The guest also receives the invitation
context and selected evidence. Existing participants can see the invitation in
later inputs. Before sending a conclusion draft, finish the guest's contribution.
New roles also review the meeting draft. After the discussion time passes or a
draft is submitted, follow the [continuation workflow](continuation.md) when the
user authorizes more discussion.

## Assign read-only work

Assign to a registered role, including one that just joined. Write a UTF-8
`task.json` using the five fields shown below.

```json
{
  "title": "核对接口限制",
  "instructions": "检查接口实现及现有测试，列出风险、代码位置和依据。",
  "context": "当前方案保留现有 API，重点核对错误处理分支。",
  "constraints": ["限于仓库和主持人提供的资料", "只读检查"],
  "acceptance_criteria": ["每项发现都有可核对的依据", "区分已确认事实与待验证假设"]
}
```

```bash
python3 scripts/meeting.py assign --room ROOM --as HOST --task-id verify-api \
  --request-id assign-api --to developer --type readonly --file task.json --evidence-event 4
python3 scripts/meeting.py run --room ROOM --as HOST --task-id verify-api \
  --request-id verify-api-1
python3 scripts/meeting.py review --room ROOM --as HOST --task-id verify-api \
  --request-id review-api-1 --decision accept --result RESULT_EVENT_ID --text-file feedback.md
```

The role uses its native discussion session and backend's read-only tools. A role
that has not been called yet establishes its discussion session on the first
task call. Evidence references preserve the original event IDs. The task prompt
includes excerpts, so put necessary detail and paths in the task context. Read
the result and check its sources before accepting. For gaps, use `--decision revise`
with specific feedback, then run with a new request ID. It resumes the same role
session. `--result` must name the current result event. The default per-call timeout
is 180 seconds and the default attempt budget is five. The room's time limit
still applies.

## Verify public web sources

Choose a DSH role with its DeepSeek API provider configured. Add `--web-search`
to that role's read-only assignment. Describe the exact claim and what public
sources would settle it in the task file. Ask for URLs and note any gaps. Keep
private project references and credentials out of web queries.

```bash
python3 scripts/meeting.py assign --room ROOM --as HOST --task-id verify-docs \
  --request-id assign-docs --to research --type readonly --web-search --file task.json
python3 scripts/meeting.py run --room ROOM --as HOST --task-id verify-docs --request-id verify-docs-1
```

Public search and fetch are available for this assignment, including rework.
Ordinary discussion and later local-only work have web tools disabled. The
host reviews the returned sources before citing the result. Configure DSH as
described in [hosts and adapters](agent-adapters.md#backends-sessions-and-boundaries).

## Assign implementation and tests

Use the same `assign` command with `--type implementation` and a task spec that
describes the requested change and acceptance checks. The assignee must be a
Claude role. `run` creates an isolated Git worktree and starts a native execution
session using that role's CLI and model. Later attempts resume that execution
session. It has its own context and cannot inherit the discussion session's
working directory, so include the selected evidence and constraints in the task.
The usual [worktree requirements and acceptance rules](task-workflow.md) apply.
The default child task budget is 60 minutes and five attempts; the parent room's
deadline also applies. Set `run --turn-timeout` as needed, up to 3600 seconds.

Use the following commands with the parent room. Put operation-specific flags
after the operation name.

```bash
python3 scripts/meeting.py work --room ROOM --as HOST --task-id patch-api inspect
python3 scripts/meeting.py work --room ROOM --as HOST --task-id patch-api check \
  --request-id check-api --command-file check.json
python3 scripts/meeting.py work --room ROOM --as HOST --task-id patch-api review \
  --request-id accept-api --decision accept --snapshot SNAPSHOT --check-id check-api --text-file feedback.md
python3 scripts/meeting.py work --room ROOM --as HOST --task-id patch-api apply --request-id apply-api
```

Inspect the actual diff, run the relevant checks and review the exact snapshot.
To request changes, review with `--decision revise`, record the feedback and run
again. Apply accepted changes only within the user's authorized scope. The
worktree, diff and logs are under `ROOM.group/tasks/TASK_ID/`. `work sync` can
recover committed child receipts after interruption. `work extend` takes the
arguments of `task.py extend` after the operation name. Extend the parent on the
user's decision if its time limit also needs to change.

## Continue the discussion

The page and Markdown export show task status and results in the original room.
Accepted results can be cited in the next host message, assessment and conclusion
using their event IDs. Before drafting, resolve all assignments. Use
`meeting.py cancel --room ROOM --as HOST --task-id TASK_ID --request-id REQUEST_ID --reason REASON`
to record why a task was dropped and preserve its history. Task calls do not use
discussion rounds. If the meeting is stopped, an active call ends and retains
its recorded evidence and worktree. Give the user any remaining gaps when asking
whether to extend the meeting.
