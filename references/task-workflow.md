# Implementation and review tasks

Use this workflow when the user asks you to have Claude implement, fix, test or
review code. YOU remain the host in this conversation. First release supports
one Claude Code worker; discussion adapters for Codex/pi/OpenCode remain available
for discussion, not editable task workers. Any capable agent can host this workflow.
Do not launch a replacement host or a discussion runner for an implementation task.

## Scope and preparation

Derive the task from the user's actual request and your existing context. Inspect
relevant files and AGENTS.md first. Write a UTF-8 task JSON with exactly:

```json
{
  "title": "Fix the concrete issue",
  "instructions": "What to implement or review, with expected deliverables",
  "context": "Relevant decisions, evidence, file locations and unknowns",
  "constraints": ["Preserve unrelated edits; respect the repository instructions"],
  "acceptance_criteria": ["Concrete behavior the host can verify"]
}
```

`title`, `instructions`, `context` must be nonempty. `constraints` may be empty;
`acceptance_criteria` must not be empty. Entire JSON must fit 24,000 characters.
For a review-only assignment explicitly prohibit edits and request findings with
file locations, evidence, severity and remaining uncertainty. Do not turn review
findings into an implementation assignment without the user's instruction.

Require Git 2.31+ and an existing commit; `PROJECT` must be the repository root.
Repositories with submodules or unresolved merge conflicts are currently rejected.
Use `storage.py prepare --cwd PROJECT --topic SHORT_TOPIC` and save task.json in
its returned directory, then use its returned ROOM. Explicit custom storage must
be outside the repository or under PROJECT/.agent-meet/.

```bash
python3 /path/to/agent-meet/scripts/task.py init --room ROOM --cwd PROJECT \
  --main HOST --task-file TASK_JSON --minutes 60 --attempts 5
python3 /path/to/agent-meet/scripts/view.py start --room ROOM --open
```

Pass your actual host identity with `--main`. Optional `--cli` is a Claude
executable path, not a shell command. Use `--model` only if requested. Keep the
user's model gateway and authentication configuration.

Initialization does not call a model. It snapshots current tracked and untracked,
nonignored working files, including staged and unstaged edits, into an isolated
Git worktree. The original worktree, HEAD and real index stay unchanged. Ignored
files, installed dependencies and submodules are not copied. Report this honestly
if it affects builds; the worker may install dependencies when the task requires
it. Source files already staged remain staged when results are later applied.

The worktree and its local branch are retained for inspection and recovery.
Worktree separation is not an OS security sandbox: the Claude CLI runs with the
user's local account and can use Bash. Its task prompt restricts modifications to
the assigned worktree, disables MCP and forbids commits, pushes, other agents and
leftover background services. Follow the user's existing execution permissions;
do not imply those prompt restrictions prevent all filesystem access.

## Execute one attempt, then inspect

```bash
python3 /path/to/agent-meet/scripts/task.py run --room ROOM --request-id implement-1
python3 /path/to/agent-meet/scripts/task.py inspect --room ROOM
```

Run in the host's foreground tool, waiting for completion; no extra terminal.
Default call timeout is 900 seconds (`--turn-timeout`, at most 3600).
The task defaults to 60 minutes total and 5 worker attempts, including failed
attempts. These are task budgets, not discussion rounds. Do not automatically
extend them. Explain why more work is needed and let the user decide; an explicit
request to continue already authorizes the requested addition.

`run` returns the worker's report separately from Git evidence: exact `snapshot`,
`changed_files`, `stat`, `diff_file`, a capped `diff_preview` and its truncation flag.
READ the actual diff and relevant files. Open `diff_file` when the preview is
truncated. Check the acceptance criteria and user constraints yourself; do not
accept based on the worker saying "done" or claiming tests passed.
For review-only tasks, verify findings against the current source and include
remaining uncertainty; a zero diff can be a valid review deliverable.
The baseline snapshot commit in the task branch has the original HEAD as parent,
so `git diff HEAD^ HEAD` at initialization shows the user's preexisting changes.

## Record actual host checks

Write a JSON argv array for each meaningful command. Commands run in the task
worktree with no shell interpolation. On Windows, use an actual executable or
Node/Python entry point; `.cmd` wrappers are not shell-expanded. A shell is allowed
only when deliberately provided as an argv command and authorized by task scope.

```json
["python3", "-m", "unittest", "discover", "-s", "tests", "-v"]
```

```bash
python3 /path/to/agent-meet/scripts/task.py check --room ROOM --as HOST \
  --request-id test-1 --command-file COMMAND_JSON --timeout 300
```

The receipt records exit code, output, full log paths and snapshots before/after.
`ok: true` means the check was recorded; inspect `passed`, `exit_code` and `error`.
A check that changes files cannot support acceptance: inspect those changes and
run a fresh check. Output previews may be capped; use full logs when necessary.
Use a new request ID for a deliberate rerun; retrying an unchanged successful ID
returns its old receipt. Choose checks that demonstrate behavior; don't add tests
that merely mirror a low-impact documentation or formatting edit.

## Original host review and same-session rework

Write substantive UTF-8 review feedback: criterion-by-criterion findings, actual
Git/file evidence and check results. For changes that need correction:

```bash
python3 /path/to/agent-meet/scripts/task.py review --room ROOM --as HOST \
  --request-id review-1 --decision revise --snapshot SNAPSHOT \
  --text-file FEEDBACK --check-id test-1
python3 /path/to/agent-meet/scripts/task.py run --room ROOM --request-id rework-1
```

The next attempt resumes the exact original Claude session and worktree, with
the host feedback and selected check receipts. Do not initialize a new task to
rework this one. A stale snapshot or check is rejected. Independent checks and
worker-reported tests are deliberately separate.

When the implementation satisfies the task, record host acceptance:

```bash
python3 /path/to/agent-meet/scripts/task.py review --room ROOM --as HOST \
  --request-id accept-1 --decision accept --snapshot SNAPSHOT \
  --text-file REVIEW --check-id test-2
```

Repeat `--check-id` for relevant passing checks. Acceptance requires a current
ready_for_review result and exact snapshot. An unresolved failing check on that
snapshot blocks acceptance; a later passing rerun of the same command supersedes
its failure. If executable checks would add no value (e.g. small prose-only edits),
record the concrete reason using `--no-check-reason` instead of inventing a test.
This flag does not bypass recorded failing checks. The tools validate receipts,
identities and snapshots, not the semantic quality of your review; YOU own that.

Acceptance creates a delivery commit only on the isolated task branch. It does
not apply changes to the original project. When integration is within the user's
request, complete it without adding a redundant permission question:

```bash
python3 /path/to/agent-meet/scripts/task.py apply --room ROOM --as HOST --request-id apply-1
```

Apply refuses changed destination paths; unrelated source edits are preserved.
It does not stage, commit or push the source branch. Resolve conflicts deliberately
with the user context; never reset/stash user files to make apply succeed. Report
actual integration and tests, including limits, instead of claiming an isolated
accepted result is already in the original project.

## Stop, recover, extend and export

```bash
python3 /path/to/agent-meet/scripts/task.py status --room ROOM
python3 /path/to/agent-meet/scripts/chat.py stop --room ROOM --reason "user stop"
python3 /path/to/agent-meet/scripts/task.py extend --room ROOM --as HOST \
  --request-id extend-1 --minutes 20 --attempts 2 --reason "User asked to finish the remaining fix"
python3 /path/to/agent-meet/scripts/chat.py export --room ROOM --output NEW_REPORT.md
```

The page shows task events, Markdown/folding, actual checks, review and whether
changes are merely accepted or applied. Stop cancels the active managed process
and ordinary descendants, preserving worktree, logs and native identity. The
page remains a viewer; review and application belong to the original host.

On failure, `run` prints its log directory. Inspect `turn-001.stderr.txt`,
`turn-001.result.json`, `turn-001.prompt.txt`, the current diff and task status.
Claude's `is_error: true` is failure even if `subtype` says `success`. Compaction
errors preserve edited files and the original native session; this workflow does
not repair CLI/gateway compaction or silently replace sessions. A session UUID
is reserved before the first call. Retries use `--resume` with that SAME UUID.
If that first CLI call never created a session, diagnose it and explain the limit
rather than silently creating another.

Completed request IDs are idempotent; changed inputs require a new ID. Failed or
interrupted requests are not automatically replayed: inspect evidence, then use a
new request ID for an explicit retry in the original session. If a run was
interrupted after producing output, inspect its saved response as well as its diff
before retrying. Keep the database plus `.task/`, `.worktree/`, `.view/` siblings
and the CLI's native session records. Do not remove a live worktree with a generic
file deletion; after delivery, use Git worktree removal deliberately if requested.
