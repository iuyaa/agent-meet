# Changelog

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
