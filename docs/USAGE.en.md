# Meet usage guide

[简体中文](USAGE.md) · English

[Back to README](../README.en.md) · [Skill instructions](../SKILL.md) · [Finalization](../references/finalization.md)

The README covers installation and natural-language examples. This guide covers role settings, continuation, and low-level commands.
Replace every placeholder path with the actual path returned by initialization.

## Set roles and rounds

Describe your requirements when starting a discussion; you do not need to write configuration files yourself:

> $agent-meet Discuss the agent redesign for glp-content for up to 3 rounds.
> You host. Invite five roles: product manager, architect, developer, user, and business owner.
> Use Claude by default and Codex for the architect. Report agreement, disagreements, and questions requiring verification.

A role's name, focus, and CLI backend are separate settings. Invited roles default to Claude.
To use Claude for every role, omit the Codex assignment. An extra role assigned to Codex needs a configured local Codex CLI; the current host can remain in the desktop application.

The five-role example means **the host plus the five requested roles**, for six participants in total.
If you want the original host to serve as architect, say: “Host as the architect and invite the other four roles.” The user role simulates a user's perspective.

**One round = a question from the host plus one reply from each role.** With up to three rounds and five extra roles, there can be up to 18 ordinary messages. Conclusion drafts and reviews are counted separately.
The first round collects independent judgments. Later rounds include all roles' views from the previous round and the host's follow-up, allowing participants to respond to one another.
The default is up to three rounds; supported settings are 1–20 rounds and 1–8 extra roles.
A resolved discussion can conclude after a complete round. An explicit request for exactly N rounds is followed.

Roles and rounds are set when creating a discussion, and the page displays the configuration and progress.
Existing two-agent discussions remain readable. Create a new discussion to switch to multiple roles or change role configuration.
See [role discussions](../references/role-discussions.md) for commands and retry behavior, and [examples/roles.json](../examples/roles.json) for a five-role template.

![Five-role discussion demo using simulated CLIs](../examples/group-preview.png)

The screenshot uses simulated CLI processes, without real model calls.
Each round calls the roles in parallel within one foreground tool execution. After it returns, the original host continues judging against the long-term context.
Every role must explicitly accept the draft. The host then addresses final feedback and saves the final conclusion.
Objections, timeouts, and missing replies retain their actual status.

## Continue after reaching a limit

Both two-agent and multi-role discussions can continue in the **original room**. For example:

> Discuss for two more rounds, focusing on failure paths. Resume the original participants' sessions and keep the same discussion.

Or:

> Extend this discussion by ten minutes.

The original host keeps the long conversation, and each role resumes its native session ID.
Messages, the briefing, previous conclusions, and reviews remain in the record.
Old conclusions remain as history after an extension; they no longer represent the current result, which needs fresh review.
Existing v0.6 rooms also support continuation in place without migration or initialization.

**Assess readiness before drafting; exhausting the rounds does not make a discussion ready to conclude.**
The host records “ready to conclude” or “needs more discussion,” evidence, critical gaps, acceptable uncertainties, and next steps.
If more rounds or time are needed, the host explains why and proposes an extension for you to decide. There is no automatic extension by default.
An explicit request for “two more rounds” already authorizes that extension. If you decline, preserve and export the actual progress and unresolved issues.

```bash
python3 /absolute/path/agent-meet/scripts/chat.py assess --room ROOM --as codex --request-id readiness-1 --file DISCUSSION_DIR/assessment.json
python3 /absolute/path/agent-meet/scripts/chat.py extend --room ROOM --as codex --request-id approved-more-1 --rounds 2 --minutes 10 --reason 'User approved two more rounds to check failure paths'
```

See [examples/assessment.json](../examples/assessment.json) for the `assess` schema.
New foreground discussions reject drafts without a valid “ready to conclude” assessment. New messages or reviews require reassessment.
The original host makes the assessment; tools validate the record and structure, which cannot replace factual checks.
If a role's session cannot be resumed, the tool reports an error instead of silently creating a replacement session.

Adding only rounds after time has expired also grants ten minutes. Adding only time when rounds are exhausted also grants one round.
To extend only the time for reassessment and review, explicitly use `--rounds 0 --minutes 10`.
Wait for an active call to finish, or stop it, before extending. See [continuation](../references/continuation.md) for the full rules.

## Choose the host and participants

The host, role, and backend are separate settings. A role describes responsibility, a backend is the agent running that role, and the host is the current initiating conversation.
For example:

> Use agent-meet in this Claude conversation to ask Codex to review the proposal, preserving our current context.
>
> Use agent-meet in this pi conversation. Have a product manager on Claude, an architect on Codex, and a developer on OpenCode discuss for three rounds. You continue hosting.

For a two-agent discussion, `--main claude --backend codex` lets Claude invite Codex, while `--main pi --backend opencode` lets pi invite OpenCode.
Use `--reviewer` for a separate participant identity and `--model` for a model supported by that CLI.
Multi-role configuration sets `backend` for each role without changing the host.
Older rooms without a saved backend continue to use Claude and retain their existing sessions.

See [adapters and hosts](../references/agent-adapters.md).
The examples below use Codex inviting Claude. For other hosts, replace `--main` and every `--as` value with the actual host identity and select the appropriate `--backend`.

## Default workflow

1. The current host prepares a briefing from existing context: question, goal, current judgment, constraints, prior decisions, rejected approaches, code evidence, and unknowns.
2. The tool saves an inspectable briefing and records it as the current host's opening message.
3. Open the local group chat page. The host calls Claude once and waits for that tool execution to return.
4. Claude reads the briefing and relevant project files, then responds with views, evidence, or questions.
5. The original host follows up, challenges a point, or adds information using the long conversation. The next call resumes the same Claude session.
6. The original host assesses readiness, submits a draft for review, addresses each final feedback point, saves the final conclusion, and exports. If an extension is needed, the host explains why and lets you decide.

**The briefing is not an automatic copy of the full history.** It contains excerpts needed for this discussion.
The original host remains responsible for checking against long-term context omitted from the briefing.
Claude can flag missing information and should not assume it knows the entire history.
Agreement on a record does not replace factual verification.

Normal discussions progress within one user turn: tool execution → result → original host continues.
You do not need to copy an invitation or send another “continue” message.
If the host tool returns a running execution ID, the host should wait for that execution to finish.
If the host has ended the entire turn, the skill cannot force its UI to wake up.

## Tool entry points

Write the context as UTF-8 JSON; see `examples/briefing.json` for the complete schema.
All eight fields are required. Unknown lists may be empty; do not invent prior decisions.

```bash
python3 /absolute/path/agent-meet/scripts/consult.py init --cwd /absolute/path/project --briefing-file /absolute/path/work/briefing.json --main codex --backend claude
python3 /absolute/path/agent-meet/scripts/view.py start --room ROOM --open
python3 /absolute/path/agent-meet/scripts/consult.py reply --room ROOM --request-id claude-1
```

`ROOM` means the actual `room` path returned by initialization. Do not pass the placeholder literally.
`init` joins both identities and records the briefing as the host's first message without calling a model.
The briefing is directly inspectable at `<ROOM>.consult/briefing.json` and `briefing.md`.
Initialization without `--room` creates a separate directory under the project's `.agent-meet/`.
`reply` performs one Claude call and records and returns its reply; it does not run a background chat loop.

For a follow-up, the original host first writes a UTF-8 message file, then runs:

```bash
python3 /absolute/path/agent-meet/scripts/chat.py send --room ROOM --as codex --request-id main-2 --text-file DISCUSSION_DIR/follow-up.txt
python3 /absolute/path/agent-meet/scripts/consult.py reply --room ROOM --request-id claude-2
```

If Claude is not on PATH, add `--cli /absolute/path/to/claude` during initialization, using the executable path.
On Windows, `py -3` can replace `python3`; quote paths containing spaces.
Native Claude executables and standard npm wrappers are supported. Update older CLIs that lack the required flags.

Ordinary messages alternate. Use a new request ID for each new operation.
If a successful result is lost, retrying its original ID returns the saved reply without another model call.
After an error or interruption, inspect the logs before explicitly retrying with a new ID.
If a resumed CLI returns a different native session ID, the tool reports an error instead of silently replacing the session.

## Local group chat page

![Local discussion page using prewritten demo messages](../examples/chat-preview.png)

The screenshot is a scripted demo record without model calls.

The page refreshes approximately once per second. It shows complete recorded messages, which participant is being called or awaited, call errors, drafts, reviews, and supporting messages.
The message stream is on the left, with the briefing and results on the right.
Model replies appear only after completion and recording. Private model reasoning is not displayed.

Messages, briefings, drafts, and reviews support Markdown: headings, bold, italics, strikethrough, inline code, code blocks, nested lists, task lists, blockquotes, links, and tables.
Code keeps its indentation; wide code and tables scroll within their content area.
HTML is displayed as text, images become clickable links, and exports preserve raw Markdown.
Individual messages can be folded, and long messages start collapsed. Expand-all and collapse-all controls are available; refreshes and new messages preserve your choices.
Folding affects only the display. Full records and exported text remain available.

- **Stop discussion:** asks for confirmation, closes the discussion, and cancels active model calls while preserving messages.
- **Export record:** saves a Markdown snapshot containing all original messages, drafts, and actual review status.
- **Ask a follow-up:** use the original host conversation to retain its context.

Running the page requires no Node.js, frontend dependencies, or Golutra.
`start` selects a free local port and reuses an existing viewer when run again.
`--open` attempts to launch the default browser and also returns the full local URL.
The URL contains the room's access token; keep the part after `#`. Frontend files use no external CDN.
The service binds only to `127.0.0.1` for browsers on the same machine.
Remote environments need a local tunnel supported by the host; otherwise use the CLI and exports. The service does not automatically expose itself publicly.

On Windows, internal viewer, worker, and CLI launches suppress new console windows.
On Linux and macOS, these entry points do not launch a terminal application.
The viewer stays running after discussion completion for reading history; that does not mean a model call is still active.
Run Python entry points directly through the host's command tool, without wrapping them in `Start-Process`, `cmd /k`, or a new terminal.
If a leftover window belongs to an older viewer service, an upgrade does not replace it automatically: close that service, then start it with the updated version.

The page remains viewable after the discussion ends. Closing the browser tab does not stop the discussion; neither does closing the viewer service:

```bash
python3 /absolute/path/agent-meet/scripts/view.py status --room ROOM
python3 /absolute/path/agent-meet/scripts/view.py close --room ROOM
```

The page cannot inject messages into an ended Codex Desktop turn or wake the host UI.
Normal progress relies on tool results awaited in the current turn. A failure to open the page does not prevent the discussion from continuing.

## Conclusions and checks

The original host submits a draft with `chat.py propose`, then calls `consult.py reply` once for Claude to review it.
The conclusion must reference real messages from both participants and may retain disagreements and open questions.
See `SKILL.md` for commands. A draft that fails review is not marked as consensus; timeouts, errors, and missing replies are not consent.
After acceptance, the room awaits finalization. The host must address every feedback point in the last reply and run `chat.py finalize` before exporting and reporting.
See [finalization](../references/finalization.md).

```bash
python3 /absolute/path/agent-meet/scripts/consult.py status --room ROOM
python3 /absolute/path/agent-meet/scripts/chat.py stop --room ROOM --reason 'User requested stop'
python3 /absolute/path/agent-meet/scripts/chat.py export --room ROOM --output DISCUSSION_DIR/report.md
```

The two-agent defaults are 12 ordinary messages including the briefing, ten minutes of discussion, two minutes of conclusion review, and at most four drafts.
Each CLI call defaults to a 180-second timeout; `reply --turn-timeout` accepts 1–600 seconds.
Stopping a discussion terminates the CLI for an active call.
Logs, request caches, and Claude's native session ID are in `<ROOM>.consult/`; active call state is in `<ROOM>.peers/`.
Keep discussion data out of version control. The tools do not rewrite project configuration or user login data.

Adapters restrict project write access; Python tools handle communication writes.
pi disables extensions and skills. OpenCode uses a dedicated discussion agent with read-only tool permissions; version 2.x uses a separate service for each call to avoid reusing stale configuration.
Model calls use existing CLI model settings and accounts. The tools do not provide model access.
