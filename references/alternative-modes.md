# Alternative modes — explicit opt-in only

The default in v0.4 is the current main agent plus foreground Claude calls.
Use this reference only when the user explicitly requests a different mode.
Always use fresh discussion paths when changing modes; do not mix ownership of
the same identity between foreground calls and background/manual participants.

## Independent background discussion

This starts TWO new CLI sessions. Neither inherits the original window's history.
Use only for an independent task where the supplied topic/briefing is sufficient
and the user accepts that context boundary. Both CLIs must be installed/configured.

```bash
python3 /path/to/agent-chat/scripts/discuss.py run --room /shared/independent.sqlite --cwd /project --topic-file /shared/question.txt
```

`start` launches without waiting. `status` and `wait --timeout 25` inspect the job.
`stop` closes it. A detached controller manages both identities, their native
session resumption, conclusion review, error handling and report export. Inspect
`job.state` and `job.report_path`, not just startup success. This does not control
an already-open UI or inject notifications into an ended UI turn.

## Current main plus a background peer

This is the v0.2-style mode. The original main joins a room, sends messages and
actively calls read/wait. Only the peer is managed in the background. Prefer
foreground consult.py for the normal bounded discussion; this mode is useful
only when the user explicitly wants a persistent mailbox participant.

Create a room with `chat.py create`, join and send as the main, then:

```bash
python3 /path/to/agent-chat/scripts/peer.py start --room /shared/mailbox.sqlite --as claude --cwd /project
python3 /path/to/agent-chat/scripts/peer.py status --room /shared/mailbox.sqlite --as claude
python3 /path/to/agent-chat/scripts/peer.py stop --room /shared/mailbox.sqlite --as claude
```

`--backend codex` selects a Codex CLI peer. Read returned messages with
`chat.py read/wait --as MAIN --after CURSOR`; advance the cursor only from the
read result. This mode cannot wake an original main window that ends its turn.

## Two manually opened windows

Both sessions read SKILL.md and agree to manual mode. Create one room, give both
its exact absolute path, and join under distinct identities. The first listed
participant speaks first; normal messages alternate. Use `chat.py send`,
`read`, `wait`, `propose`, `review`, `stop` and `export`. A one-time manual
introduction is required here. CLI startup is not performed by this mode.

All modes share the same discussion protocol and limits: default 12 regular
messages, 10 minutes plus 2 minutes for conclusion review, at most 4 proposals.
Acceptance confirms an accurate record of both views, including disagreements.
Silence, timeout and transport/model failures do not count as agreement.
