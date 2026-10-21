# Validation record

[简体中文](VALIDATION.md) · English

Environment: Linux and Python 3.12. Runtime tools use only the Python standard library.

`python3 -m unittest discover -s tests -v` passed **115 tests**: 14 for the original communication protocol, 9 for foreground calls preserving the host conversation, 9 for a single invited participant, 7 for bilateral orchestration and Codex wrappers, 8 for the local viewer service, 15 for multi-role protocol and parallel calls, 14 for continuation and readiness assessment, 12 for cross-agent adapters, 12 for project-local storage, and 15 for review finalization.

## Command installation compatibility

Verified with Skills CLI 1.7.4 and Node.js 24.19.0:

- `skills add iuyaa/agent-meet --skill agent-meet --list` against the public GitHub repository correctly discovered the sole skill, agent-meet.
- In an isolated temporary project, `npx skills@1.7.4 add iuyaa/agent-meet --skill agent-meet -a codex claude-code opencode pi --yes --copy` accepted all four targets.
- Installation created the shared `.agents/skills/agent-meet` directory and the Claude project's `.claude/skills/agent-meet`. Scripts, web assets, `SKILL.md`, and adapter documentation matched the source byte for byte.
- Both the default symlink mode and `--copy` mode succeeded. CLI entry points worked from the shared directory and the Claude link.
- Running storage prepare and consult init from the installed directory succeeded, confirming that execution does not depend on the original repository path. No real models were called.
- Installer cache, state, and project files were confined to temporary directories, with telemetry disabled. No global installation or changes to existing user skills were performed.

## v0.10: review finalization and final conclusions

- Accepted two-agent and multi-role drafts enter `finalizing`, awaiting the original host's reconciliation of all current reviews. Acceptance does not prematurely mark the discussion complete.
- Finalization must reference all review IDs, including the last review, and provide point-by-point dispositions from actual review text. Missing or fabricated references and attempts by another role are rejected.
- Unchanged finalization must exactly match the reviewed draft. Minor additions are shown as host-edited text; substantive changes require a new draft and review in the original role sessions.
- Final conclusions are immutable events. Repeated requests are idempotent. After continuation, previous finalizations remain history and no longer serve as the current result.
- If the host reassesses the discussion as needing more work, it waits for the user's extension decision. Stopping or partial review does not produce a final conclusion.
- The page and Markdown export select the same latest finalized conclusion and display feedback dispositions. Exports without finalization explicitly show that finalization is pending.
- The two-agent Chromium check verified: final review with additions → pending finalization → final text incorporating additions → matching page and export.
- The multi-role Chromium check covered: unanimous acceptance → pending finalization → reconciliation of five roles' feedback → finalization. Existing continuation, folding, and privacy checks were retained.
- The original manual/background protocol without lifecycle metadata retains its behavior. All model output came from simulated CLIs; no real models were called.

## v0.9: project-local discussion storage

- Two-agent and multi-role initialization without a room creates separate subdirectories under the project's `.agent-meet/` and returns actual absolute paths.
- Sequential or concurrent preparation for the same topic creates separate directories. Topic text containing Chinese characters, spaces, or path separators cannot escape the project directory.
- `storage.py prepare` prepares directories and input paths without creating a database or calling models. Subsequent explicit initialization reuses that directory.
- Checks in a real Git repository confirmed that SQLite and role state files are ignored. The project's root `.gitignore` remained byte-for-byte unchanged.
- Existing local ignore rules are preserved. Missing project paths and symlinks at the default storage directory do not create data outside the project.
- Explicit older room paths retain their location and idempotent behavior. Subsequent commands cannot omit the room or guess the latest discussion.
- A two-agent room at the default path completed replies, budget extension, and native ID resumption with a simulated CLI. The full 100-test suite covered compatibility with older workflows.

## v0.8.1: standalone project and Meet naming

- The original skill's nine commits were extracted to a standalone repository root. Comparing each Git tree confirmed identical file trees to the source directory.
- All 88 tests and both Chromium checks ran from the standalone directory, with no runtime dependency on Golutra application code or assets.
- The page brand became Meet, the skill name became agent-meet, and new exports use `agent-meet-report.md`.
- A room created with the old v0.8 tools called a simulated pi CLI once. Meet then closed the old viewer, extended the original budget, and continued replies. The native ID, session file, and all messages were preserved without creating a new room or role. No real models were called.
- SQLite, state directories, browser storage keys, and OpenCode's internal agent identifier were retained. Old packages remain historical archives.

## v0.8: cross-agent hosting and calls

- Claude hosted and invited Codex; follow-ups resumed the same Codex ID without creating a replacement host.
- pi hosted OpenCode, and OpenCode hosted pi. After the round budget ran out, explicit user-approved extensions resumed original IDs and completed draft review.
- A group mixed Claude, Codex, pi, and OpenCode while retaining parallel round replies and continuation in the same room.
- pi reused an explicit session file. Missing files, mismatched IDs, malformed replies, and truncated replies were rejected without recording fabricated messages.
- OpenCode 1.x and 2.x checks covered run arguments, original ID resumption, read-only configuration, and the isolated 2.x service. Parsing ignored text describing earlier tool steps and selected only the final assistant reply.
- New backends used shared timeouts and process cleanup. Existing conflicting `OPENCODE_CONFIG_CONTENT` was not overwritten.
- Older consult configurations without a backend were read as Claude. A host and participant using the same agent type retained distinct identities. Windows entry points for both old and new pi npm packages were simulated.
- Both existing Chromium checks continued to cover messages, folding, assessment, extensions, review, exports, and narrow screens.

These checks used simulated CLI subprocesses, without real Claude, pi, or OpenCode model calls.
Interfaces implemented from upstream source still need integration with the user's installed versions and accounts. These results do not certify real environments for all four agents.

## v0.7: continuation and readiness assessment

- New foreground rooms rejected drafts when an assessment was absent, requested continuation, reported critical gaps, or had become stale.
- A final-round assessment requesting continuation displayed a wait for the user's extension decision. The default automatic extension allowance was zero. Declining an extension stopped the discussion while preserving gaps.
- Two-agent message extensions, multi-role round extensions, interruption at the deadline, and renewed discussion after unanimous acceptance all reused the original room and native session IDs.
- Older two-agent and multi-role rooms without lifecycle tables continued in place without copying or initializing rooms.
- Role native IDs could be restored from SQLite. Failure to restore the original ID explicitly rejected replacement sessions, without an extra model call.
- After continuation, previous conclusions and reviews remained history. Uncommitted replies spanning a continuation boundary could not be inserted, while successful earlier requests remained readable.
- Continuing an interrupted round did not skip other roles' actual earlier messages because of cursor advancement. Resumption retained original IDs and supplied the updated public record.
- Extensions were idempotent and rejected while calls were active. Time and round extension rules had end-to-end simulated CLI coverage.
- The five-role Chromium check covered: assessment requesting continuation → waiting for the user → explicit extension → resumption of all five original sessions → reassessment → review by all roles. Each role's resume arguments matched its native ID before continuation. The page displayed assessment reasons, critical gaps, and continuation events; exports included the actual history.

All model output above came from simulated CLIs, not real-model end-to-end integration. Native resumption on actual Windows and macOS systems remains unverified.

## v0.6: multiple roles and folding

- Five independent simulated CLIs used a startup barrier to verify actual parallel invocation, with the same discussion snapshot for every role in a round.
- Batched calls and retries after failure retained the original round or draft snapshot, without exposing other same-round replies or review votes early.
- Each role received a distinct native session ID. The second round resumed each role's own session and provided all previous-round views and the host's follow-up.
- Role titles, focus, Claude/Codex backends, and optional model settings reached their corresponding CLIs. The host could also fill one role.
- The protocol enforced round limits for ordinary messages. Discussions could conclude after complete rounds, and reviews did not consume discussion rounds.
- The host could not self-confirm. Evidence had to come from the host and every role. Every role had to explicitly accept; majority approval did not override minority objections.
- When some roles failed, other actual replies were preserved. New requests called only missing roles. Retries of successful or earlier requests neither repeated calls nor rewound read cursors.
- A saved reply whose database commit failed could be committed on recovery without a second model call.
- Accidentally sharing a native session between roles was rejected. Stopping canceled all active role calls. Expiration did not turn partial review into unanimous consent.
- `tests/browser_view.cjs` added long-message default folding, individual and global expand/collapse controls, and persistence after refreshes and new messages.
- `tests/browser_group.cjs` checked five-role state, round separators, 1/5 partial review, objections and unanimous review, multi-role exports, exclusion of private fields from the API, a 390px viewport, and absence of JavaScript errors in Chromium.

```bash
CHROMIUM=/path/to/chromium node tests/browser_group.cjs /tmp/agent-meet-group-preview.png
```

`examples/group-preview.png` comes from that browser test. Messages were generated by simulated CLIs, without real model calls.

## v0.5.1: Markdown

- Chromium checked headings, bold, italics, strikethrough, inline and fenced code, nested/ordered/task lists, blockquotes, reference-style links, and tables. Code indentation and literal `<` and `&` characters were preserved.
- Briefings, messages, conclusion agreement items, and review comments rendered Markdown.
- HTML, event attributes, and IDs impersonating UI elements could not be injected. JavaScript, data, and file links were not clickable. Remote images became links, and browser checks confirmed no external subresource requests.
- Markdown tables and long code did not overflow a 390px page. Exports contained raw Markdown.
- The static-file allowlist included both bundled rendering libraries. Existing stop, export, and disconnection checks still passed.
- Marked 17.0.5 and DOMPurify 3.4.17 were bundled locally with upstream licenses. The DOMPurify package passed npm SHA-512 integrity verification. Installing and running the skill added no npm dependencies or network requirement.

## v0.5: local viewer

- Repeated starts reused the same process. Recorded events were immediately visible through the API. Status responses did not expose CLI configuration or native session IDs.
- The service bound only to loopback and required an API token. Invalid Host headers, external Origins, and arbitrary file paths were rejected.
- Stopping from the page preserved records without fabricating consensus. Markdown exports retained original messages and actual review status.
- A delayed simulated CLI verified that the page's stop request canceled an active foreground call without producing a fabricated reply.
- Closing the viewer preserved discussion state and allowed restarting. Attempts to view a missing discussion did not create it.
- Chromium and Playwright ran `tests/browser_view.cjs`, checking automatic message updates, the briefing, literal display of HTML input, token preservation through refresh and evidence anchors, draft and review states, export saving, no horizontal overflow at 390px, stop/cancel controls, and disconnection notices. There were no browser JavaScript errors.

Optional browser reproduction requires Playwright and Chromium in the development environment; running the skill does not:

```bash
CHROMIUM=/path/to/chromium node tests/browser_view.cjs /tmp/agent-meet-preview.png
```

`examples/chat-preview.png` comes from this browser check. All UI test messages were prewritten demo data, without real model calls.
Only Windows npm entry points were simulated. Browser auto-opening and the new viewer service process have not been tested on actual Windows or macOS systems.

## Foreground workflow coverage

The default foreground workflow was checked with a simulated Claude CLI:

- Initialization saved a complete briefing including constraints, previous decisions, and rejection reasons as the original host's opening message, without model calls.
- Only Claude was called, with one reply per tool execution. No replacement Codex host or bilateral background job was started.
- Follow-ups resumed the same native Claude session and supplied new discussion messages plus the saved briefing.
- Briefing changes could not silently enter an old discussion. Ordinary replies required Claude's turn.
- Retrying successful requests did not repeat model calls. Retrying earlier requests did not rewind read positions. Saved responses could be recovered for commit.
- Claude returning a different ID during resumption caused an error and preserved the original ID, without discarding context automatically.
- The original host submitted the conclusion; Claude only reviewed it, after which the record could be exported.
- Missing briefing fields, CLI errors, and timeouts did not generate fabricated replies. Error retries required an explicit new request ID.
- Foreground calls held a participant lock to prevent another background process from taking the same identity.

## Original protocol and optional background modes

Protocol checks covered:

- Bidirectional communication between two identities, full rereading after reconnection, and explicit cursors that did not delete messages.
- A waiting process waking when another process sent a message.
- Concurrent retries of the same request ID producing only one message.
- Concurrent distinct sends from one identity strictly preserving a single speaking turn.
- Draft confirmation within the review window after message or discussion-time limits were reached.
- Rejection of one-sided or nonexistent evidence, self-confirmation, and confirmation of expired drafts.
- Draft rejection, preserved objections, and confirmation by the other participant after revision.
- At most four drafts, and no new messages after stopping.
- Timeouts not counting as consent, and unconfirmed drafts retaining their status.
- Exact round trips for Chinese paths, paths containing spaces, multiline text, and shell metacharacters.
- Existing databases and export files not being overwritten.

Automatic joining used a separate simulated Claude executable and covered:

- Automatic background joining and replies after the opening message, without copying an invitation.
- Subsequent turns resuming the native session ID returned by the CLI.
- Automatic conclusion review followed by exit, with a complete exportable record.
- Repeated starts returning the existing participant instead of starting another model process.
- Explicit failure when the CLI was missing, without a false join report.
- Explicit errors for unwritable runtime directories, without misreporting an existing running participant.
- Explicit failure for nonzero exits, non-JSON replies, missing structured results, permission denials, and invalid actions.
- Stopping canceling an active CLI, and per-turn timeouts terminating and reporting the call.
- Windows npm wrappers resolving to Node entry points to avoid batch/shell argument interpretation.

Bilateral orchestration used two independent simulated CLI processes and covered:

- The initiating process starting a job whose participants then completed four messages, a draft, review, and automatic export.
- `run` waiting for that job and returning the result without an extra manual “continue” message.
- Each participant resuming its own native session, with correct parsing of Codex JSONL, thread IDs, and structured output.
- Repeated initiation returning the original result without more model calls or report overwrites.
- Missing either CLI failing before a discussion was created.
- Codex failure terminating the Claude participant, preserving partial records, and explicitly marking no consensus.
- Stopping canceling both active participants. Missing thread IDs, invalid results, and failure events did not count as success.
- Codex Windows npm wrappers also resolving to Node entry points.

The locally installed Codex CLI was checked with `--help` to confirm that generated exec/resume arguments could be parsed. This did not call a model.

`python3 examples/two_process_demo.py --output ...` ran two independent Python processes through four messages, a conclusion draft, and confirmation by the other participant, exporting all six events.

**The demo uses prewritten messages and calls no models.** At the time of this verification, the environment had Codex CLI but no Claude Code CLI, so real Codex ↔ Claude Code end-to-end integration had not been completed.
Actual Windows process creation, macOS, and native automatic skill discovery across hosts were also unverified in that environment.
Simulated Windows npm path checks do not replace testing on Windows. Use the automatic-start workflow in the README for real-model verification.
