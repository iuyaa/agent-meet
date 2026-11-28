# Native session and context failures

For an invited CLI failing during resumption or context compaction, inspect the
actual error before asking the user to approve a replacement. A host's summary
does not establish the CLI's failure cause.

## Inspect the failed call

- Read `consult.py status --room ROOM` or `group.py status --room ROOM`, plus the
  failed call's `.stderr.txt`, `.result.json`, and `.prompt.txt`. Two-person logs
  are under `<ROOM>.consult/turn-N/`; group logs are under
  `<ROOM>.group/<request-digest>-<role-id>/`. Use this room's actual paths.
  For Antigravity, `agy.log` in that same call directory contains the native CLI
  diagnostics. Compare the last stream event with the CLI error and elapsed time.
- Use the call's `error_code` (per role in `group.py round`'s `error_codes`).
  `idle_timeout` means no progress was visible within the idle period. Some
  CLIs buffer their reply, so silence provides no evidence about model activity.
  `turn_timeout` means Agent-Meet reached the hard per-call limit.
  `discussion_budget` means the discussion phase ended while a reply was
  pending. `backend_timeout` means the CLI explicitly reported its own timeout.
  `call_failed` leaves the cause in the error detail and logs. These outcomes
  leave the reply unrecorded.
- Check the configured executable's version. Distinguish explicit compaction or
  context errors from authentication, usage limits, invalid output, and Meet's
  per-call timeout. A timeout alone does not establish a compaction failure.
  Report relevant errors without exposing credentials.
- Compare prompt sizes and event IDs. Group continuation replays visible history
  once per role after each extension, then sends only unseen events to that same
  native session. The briefing and current protocol state are still included on
  every call. Smaller repeat input does not compact existing native history.

Do not repeatedly retry an unchanged failure. Inspect logs, address the specific
cause, and use a new request ID to retry a failed call explicitly. Successful and
response-ready retries retain their existing idempotent behavior.

Antigravity can initialize a conversation before the first reply is ready.
Agent-Meet retains the ID from the startup frame for that exact role, including
on a timeout. An explicit retry resumes that conversation. An incomplete
reply remains outside the meeting transcript.

## Recover the original session first

Claude's native `/compact` summarizes context within a session. Where supported
by the installed CLI and access method, open `claude --resume SESSION_ID` in the
configured project directory and compact there, after the Meet call has ended.
Do not send `/compact` through `consult.py reply` as a structured discussion
reply. `--fork-session` and `/clear` do not recover the same native session.
Meet has no native compaction command and cannot guarantee successful compaction
or complete preservation of facts. Check the saved evidence after recovery.

## If the original session remains unusable

Preserve the room, transcripts, native records, successful replies from other
roles, unresolved issues, and actual review status. Export an unfinished snapshot
if needed; a failed call does not count as agreement or review acceptance.

The default continuation contract requires original native sessions. The user
can authorize changing that contract, but this version has **no supported
in-place native-session handoff command**. Approval alone does not add one.
Do not clear status fields, rewrite `group_sessions`, delete caches, or silently
substitute a new session to bypass the guards. Explain the limitation accurately.

A future handoff must record the old/new IDs, reason, authorization, and an
inspectable evidence brief. It must distinguish transferred evidence from native
conversation memory and require fresh review where earlier approval is no
longer valid. That is a separate recovery feature, not ordinary continuation.

Official Claude references: [context management](https://code.claude.com/docs/en/context-window)
and [CLI session flags](https://code.claude.com/docs/en/cli-reference).
