# Changelog

## 0.12.0 — Skill update preflight

- Guide the current host to check published Agent-Meet versions before each operation, with a one-hour cache and explicit forced checks. Update the same installation when idle and unmodified, then re-read SKILL.md.
- Add verified package inventories, staged file replacement, complete backups, fast-forward-only Git updates, and cross-process installation leases. Preserve room data, native sessions, custom files and directory symlinks.
- Offline, unpublished, edited, pinned or busy installations defer instead of resetting state or interrupting active agents. Retained viewers pin loaded code/assets; their next start refreshes old services without resetting rooms. Existing pre-v0.12 skills require one initial upgrade.
- Add reproducible release inventory/package tooling and Chinese/English update documentation. Model CLIs and credentials are outside the update scope.

## 0.11.0 — Claude implementation tasks

- Delegate implementation, tests and code review to one Claude worker in an isolated Git worktree while the initiating conversation retains host context.
- Snapshot current source edits without staging or changing source HEAD; inspect real Git evidence, record host checks, review exact snapshots and resume the same native session for rework.
- Apply accepted changes without overwriting changed destination files or unrelated edits. Show task events, checks, reviews and application state in the existing local viewer.
- Task budgets default to 60 minutes and five worker attempts; extensions require the user's decision. Preserve partial work and native identity after failures.

## 0.10.2 — Incremental context after continuation

- Fixed group continuation replaying the entire transcript on every subsequent role call. Each role now receives a full replay once per extension, then only unseen events in the same native session.
- Preserve history replay for interrupted rounds, frozen round snapshots, native IDs, and complete stored/exported records. Successful retries cannot roll back the recorded history epoch.
- Added session-failure diagnosis and clarified that native compaction belongs to the CLI. An in-place native-session handoff is not implemented; user approval alone does not make it available.
- This reduces redundant prompt growth; it does not repair an already-failed Claude compaction or establish the cause of a particular CLI failure.

## 0.10.1 — Console-free Windows launches

- Centralized subprocess launch options for the viewer, optional background workers, agent calls, and CLI capability probes.
- Windows uses `CREATE_NO_WINDOW`, without the incompatible `DETACHED_PROCESS` flag; background launches retain their own process groups. POSIX foreground and background session behavior is unchanged.
- Documented direct host-tool invocation and closing/restarting older viewer services. The viewer remains available after discussions for reading and export.
- Added launch-policy regression checks and a native Python subprocess check. Actual Windows/macOS window behavior still needs verification on those systems.

## 0.10.0 — Final review reconciliation

- Accepted foreground drafts now wait for host reconciliation before closing.
- Added chat.py finalize, current-review coverage, quoted feedback points, per-point dispositions and an immutable final conclusion.
- Page, export and skill instructions use the saved final conclusion; clarification wording is labelled as host reconciliation, while substantive changes require re-review.
- Existing rooms/native sessions are retained. Original manual/background protocol behavior is unchanged.
- Reorganized README around scenarios and quick start; moved detailed commands and development notes into docs.

## 0.9.0 — Project-local discussions

- New consult/group rooms default to PROJECT/.agent-meet/TIMESTAMP-TOPIC-ID/discussion.sqlite.
- Added storage.py prepare so briefing, role inputs, follow-ups and exports can share the discussion directory.
- Each discussion gets a separate directory; local ignore rules keep new discussion data out of Git without changing project-root configuration.
- Init/status/reply/round return the absolute room path. Follow-ups still require an explicit room; existing paths and native sessions remain unchanged.

## 0.8.1 — Meet

- Extracted the standalone project from `golutra/skills/agent-chat`, preserving the nine skill commits.
- Product name: **Meet**. Repository, install folder and skill name: **agent-meet**.
- Updated the page, exports, installation examples and archive naming.
- Retained v0.8 behavior, room schemas, session sidecars, browser storage keys and the internal OpenCode discussion-agent identity.
- Existing rooms continue through their original paths and native sessions; no migration script or new room is needed.
- Previous `agent-chat` release archives remain unchanged for historical reference.

The original releases through v0.8.0 are recorded in the extracted commit history.
