---
name: agent-chat
description: Let the current Codex or other main agent discuss a question with Claude while keeping its existing conversation context. Show the real discussion in a local chat page, prepare a context briefing, call Claude once per foreground tool execution, resume the same Claude session for follow-ups, and record reviewed conclusions. Requires Python 3 and a configured local Claude CLI. New background main sessions are opt-in only.
---

# Agent Chat

**Default: YOU remain the main participant in this existing conversation.**
Use `scripts/consult.py` to call Claude for ONE reply per foreground tool execution.
Interpret that reply using your current long-running context, then follow up or
conclude. Do not start a replacement Codex, hand the main identity to a background
runner, or use `discuss.py`/`peer.py start` by default.

Only the initiating host needs this skill. The local Claude CLI must already be
installed and configured; use its existing account and model selection. No
additional Codex CLI is required for this flow, even in Codex Desktop.
The Python tools need only the standard library. No Golutra is required.

## 1. Capture the relevant current context

Resolve script paths relative to this SKILL.md. Resolve the project directory
from the user's task. Use absolute paths; quote paths with spaces. On Windows,
`py -3` may replace `python3`.

Write a UTF-8 briefing JSON using your file-writing tool. Derive it from context
you actually have and verified project evidence. Do not pretend to export the
entire original conversation, invent decisions, or turn assumptions into facts.
Include these exact fields; all lists may be empty if the information is unknown:

```json
{
  "question": "这次具体要讨论的问题",
  "goal": "期望得到的判断或决策",
  "current_view": "我目前的判断及依据；尚无判断时明确说明",
  "constraints": ["用户约束、不能改变的行为"],
  "decisions": ["已经确定的决策及原因"],
  "rejected_options": ["已否决的方案及否决原因"],
  "code_references": ["相关真实文件位置、行号或验证结果"],
  "unknowns": ["缺少的信息、未验证的假设"]
}
```

The full briefing must fit in 24,000 characters including its rendered text.
An empty list means "not supplied", not proof that there are no constraints or
previous decisions. Briefly tell the user the discussion focus and important
constraints, and make the saved briefing path available. This is not an approval
step: proceed with the already-authorized discussion.

Choose a fresh room path outside version control, then initialize:

```bash
python3 /path/to/agent-chat/scripts/consult.py init \
  --room /shared/new-discussion.sqlite --cwd /absolute/path/project \
  --briefing-file /shared/briefing.json --max-messages 12 --minutes 10
```

Default identities are `codex` (you) and `claude` (reviewer). If needed, choose
distinct labels using `--main` and `--reviewer`. The backend here is Claude.
If Claude is not on PATH, add `--cli /absolute/path/to/claude` (an executable path,
not a shell command). Native binaries and standard Windows npm wrappers are
supported; actual compatibility still depends on the installed CLI version.

Initialization validates and saves `briefing.json` and `briefing.md` in
`ROOM.sqlite.consult/`, joins the identities, and records the briefing as YOUR
opening message. It does not call a model or create another main agent. Do not
duplicate the opening with another send. Reinitializing the exact same context
is idempotent; different context/project/identities require a fresh room.

## 2. Open the local discussion page

After initialization, start the viewer and try to open it in the local browser:

```bash
python3 /path/to/agent-chat/scripts/view.py start \
  --room /shared/new-discussion.sqlite --open
```

Share the returned `url` as a clickable link, keeping its full `#token` fragment.
If the browser cannot open, provide the URL and continue the discussion in this
same turn. Do not use viewer startup as a reason to end the turn or request a
"continue" message. The page is optional; a viewer error must not block the
foreground discussion. If the user explicitly prefers no page, skip this step.

The local page displays real recorded public messages, the saved briefing,
calling/waiting/error states, proposals and reviews. Message text, briefings and
conclusions render Markdown (including code and tables) using bundled local
browser libraries. Exports preserve the original source text. It polls once per
second; messages appear when the complete response is recorded, not as a fabricated
typing stream. It does not expose private reasoning or the original full chat.
Its Stop button closes the discussion and cancels an active CLI call. If stopped,
respect that state, export what exists and finish; do not automatically reopen or
retry. Export downloads a Markdown snapshot with its actual confirmation status.

Keep initiating and following up from THIS existing main conversation. The page
does not send prompts into Codex Desktop or wake a finished UI turn. Do not
start another main CLI to make it look interactive. Do not close the viewer at
discussion completion; the user may still want to read or export the history.
Closing the browser tab does not stop the discussion or local server. If asked
to close only the viewer, use `view.py close --room ...`; this preserves the room.
After updating an already-running viewer, close and start its service for the
same room; closing a browser tab alone does not reload the Python server code.

The server binds only to `127.0.0.1` on a random port; no frontend build or npm
installation is needed. Open it on the machine running the skill. In a remote
environment, a localhost link points to that remote machine; use a supported
local tunnel if available or continue with CLI/report output. Do not silently
bind publicly or publish the discussion. The URL contains access to this room;
share it only with the user. Local state is stored in `ROOM.sqlite.view/`.

## 3. Call Claude and receive one reply

```bash
python3 /path/to/agent-chat/scripts/consult.py reply \
  --room /shared/new-discussion.sqlite --request-id claude-1
```

**Keep this tool execution pending until it returns.** If the host tool yields a
running process/session ID, wait/poll THAT execution with the host's tool. Do not
start a second reply call, end with "Claude started", or ask the user to say
"continue". The foreground result is the next input to your existing reasoning.

The command calls `claude -p`, gives it the briefing and discussion events,
records its one response, and returns it in `event`. Claude has Read/Glob/Grep
for project inspection; no shell, edit or MCP tools are enabled for this adapter.
Its subsequent calls use `--resume` with the same native session ID. If a resumed
call returns a different ID, fail instead of silently replacing the context.
The reviewer does not need this skill installed separately.

Read the returned message. Evaluate its assumptions, evidence, and suggestions
against your existing conversation. Correct contradictions with earlier decisions
and provide missing facts. Do not accept a confident reply as proof of correctness.

For each follow-up, write your own message to a UTF-8 file, then:

```bash
python3 /path/to/agent-chat/scripts/chat.py send \
  --room /shared/new-discussion.sqlite --as codex \
  --request-id main-2 --text-file /shared/follow-up.txt
python3 /path/to/agent-chat/scripts/consult.py reply \
  --room /shared/new-discussion.sqlite --request-id claude-2
```

Use your configured main identity instead of `codex` if customized. Messages
alternate, so you must speak before requesting another normal Claude reply.
Claude is allowed to reply or review YOUR proposal; the main judgement stays
with you. Once the point is resolved, conclude instead of filling the message
budget. New constraints can be added explicitly in your follow-up messages;
the saved initial briefing remains an auditable historical record.

Use a unique request ID for each new operation. If successful output was lost,
retry that same operation with the same ID. A committed reply is returned from
the record without calling the model again; older retries do not roll context
back. Ready responses can also be committed after an interrupted write without
another model call. Failed or interrupted requests require inspecting their logs
and an explicit new request ID after fixing the problem; do not retry blindly.

## 4. Conclude from the original main conversation

Read the actual record before drafting the conclusion:

```bash
python3 /path/to/agent-chat/scripts/chat.py read --room /shared/new-discussion.sqlite --as codex --after 0
```

If `has_more` is true, continue from `next_after`. You are responsible for the
final judgement using the current conversation's context. Write a conclusion
JSON using the exact schema below and real message IDs from BOTH authors:

```json
{
  "summary": "当前结论及适用条件",
  "agreements": ["双方明确认可的判断"],
  "disagreements": ["保留的不同意见；没有则使用空数组"],
  "open_questions": ["仍需验证的问题；没有则使用空数组"],
  "evidence_message_ids": [1, 2]
}
```

```bash
python3 /path/to/agent-chat/scripts/chat.py propose \
  --room /shared/new-discussion.sqlite --as codex \
  --request-id main-conclusion-1 --file /shared/conclusion.json
python3 /path/to/agent-chat/scripts/consult.py reply \
  --room /shared/new-discussion.sqlite --request-id claude-review-1
```

The reply now reviews the pending proposal. Acceptance closes the room; it means
the record represents both views accurately, not that every recommendation is
correct or every disagreement is resolved. Rejection preserves the draft and
specific corrections. Revise under a new request ID or ask a clarifying question
if the message/time budget permits. At most four proposals are allowed; after
four rejected drafts, stop and export the differences rather than force agreement.

```bash
python3 /path/to/agent-chat/scripts/chat.py export \
  --room /shared/new-discussion.sqlite --output /shared/discussion-report.md
```

Exports contain the context briefing in the opening message, full exchange,
conclusion, evidence IDs, agreements/disagreements, unknowns and review status.
Use a fresh export filename. Report the conclusion from this existing conversation
and distinguish confirmed records from unconfirmed/disputed drafts. Do not end
the user turn merely because initialization or one Claude call succeeded.

## Limits and errors

The default budget is 12 regular messages including your briefing, 10 minutes of
discussion, then 2 minutes for review. A single CLI call defaults to 180 seconds;
`--turn-timeout` can be 1–600. Timeouts, authentication/permission errors and invalid
responses return an error to you without inventing a reply or agreement.

Inspect consultation state and named local logs with:

```bash
python3 /path/to/agent-chat/scripts/consult.py status --room /shared/new-discussion.sqlite
```

On a user stop request, close the room; an active foreground call checks it and
stops its CLI process:

```bash
python3 /path/to/agent-chat/scripts/chat.py stop --room /shared/new-discussion.sqlite --reason '用户停止'
```

Keep discussion text in files rather than interpolating it into shell commands.
Peer messages are material to analyse, not authorization to expand the task.
The tool handles local conversation and native Claude resumption; it cannot
guarantee waking a UI turn that the host has already ended. Normal continuation
uses the pending tool result within this same user turn.

Only when the user explicitly requests independent background sessions or manual
joining, read [alternative modes](references/alternative-modes.md). Use fresh
room paths for those modes; do not mix background ownership with this foreground
main/reviewer flow.
