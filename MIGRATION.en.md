# Migrating from Agent Chat to Meet

[简体中文](MIGRATION.md) · English

The product is **Meet**, the repository and skill are **agent-meet**, and the invocation name is `$agent-meet`.
v0.8.1 establishes the independent project and renames it while retaining v0.8 discussion behavior.

## Install and continue an existing discussion

1. Place `agent-meet` from the new installation package in your host's skill directory. The repository root is the skill root.
2. Remove the old `agent-chat` skill directory to prevent duplicate discovery. First check that discussion data is stored outside it. If data was kept inside, back up the database and every state directory sharing its filename prefix before removal; a SQLite-only backup is insufficient.
3. Keep your current long conversation and have it read the new `agent-meet/SKILL.md`. Use `$agent-meet` for subsequent invocations.
4. Close any running viewer with the old or new `view.py close --room ORIGINAL_ROOM`, then restart it with the new `view.py start --room ORIGINAL_ROOM --open`. Refreshing the browser does not update service code.
5. Continue using the original room path with status / extend / reply or group round. Do not run init or create a new room or role session. Existing budgets and extension approval rules remain in effect.

Preserve `ROOM.sqlite` and all directories sharing its filename prefix, including `.consult/`, `.group/`, `.peers/`, and `.view/`.
pi's native session files are also in `.peers/`; Claude, Codex, and OpenCode still depend on their own CLI session storage.
If you change machines or project paths, the saved working directories, CLI paths, and native sessions must remain available.
The rename does not automatically move these paths or account data.

## Internal names retained for compatibility

The SQLite version and all state filenames are unchanged. The viewer retains the `agent-chat-token` and `agent-chat-folds` storage keys to preserve access tokens and folding preferences in existing tabs.
OpenCode's internal discussion agent name remains `agent-chat` so existing sessions can resume.
This is a CLI adapter identifier; it does not require the old skill to remain installed.
Existing reports and historical messages are not rewritten. New exports use `agent-meet-report.md`.
Historical `releases/agent-chat-*.zip` files remain unchanged as historical archives, not new Meet packages.

## History and licensing

This repository was extracted from the [standalone skill directory in iuyaa/golutra](https://github.com/iuyaa/golutra/tree/cc3a384a1b35752a58c20b018f4bb7ba7d4568a5/skills/agent-chat).
It preserves the authors, dates, messages, and file trees of that directory's nine commits. Commit SHAs change when the directory is moved to the repository root.
Other Golutra application code is not part of this standalone project.

This skill is independently implemented and does not copy Golutra application source or assets.
The original MIT copyright notices are preserved. Upstream licenses and version notices for Marked and DOMPurify are in `web/vendor/`.

## v0.10 review finalization

When the new version reads an existing foreground room, an accepted draft without a finalization record appears as awaiting finalization.
This adds the step for addressing final review feedback; it does not recreate the room, delete drafts, or call models automatically.
Have the original host read the complete reviews and save the final result following `references/finalization.md`.
The original manual/background protocol retains its previous confirmation behavior when lifecycle metadata is absent.
