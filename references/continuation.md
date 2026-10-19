# Assess before concluding; continue the same discussion

This applies to both `consult.py` two-person rooms and `group.py` role rooms.
Keep the original host conversation, room path, identities and native sessions.
Do not initialize a fresh room, clear caches or delete session metadata to get
past a budget limit. A continuation updates the existing room in place.

## 1. Assess readiness before any conclusion draft

After the last planned round (or earlier if considering a conclusion), YOU as
the original host evaluate the actual replies using your long-running context:

- Is the question sufficiently answered for the user's goal?
- Are key claims supported by project evidence and the participants' actual replies?
- Which disagreements can be recorded, and which gaps block a useful conclusion?
- Would another focused exchange resolve those gaps, or is outside evidence needed?

A budget reaching zero is not evidence that a conclusion is ready. Conversely,
unresolved nonblocking uncertainty can be explicitly retained in a limited
conclusion; do not force everyone to agree or require certainty on everything.

Write a short public assessment JSON, not hidden chain-of-thought:

```json
{
  "decision": "continue",
  "reason": "尚缺少失败路径的验收依据，当前不能给出可执行的结论。",
  "blocking_questions": ["失败时是否仍满足业务验收标准？"],
  "accepted_uncertainties": ["真实用户反馈待收集，模拟用户角色不能替代调研"],
  "next_steps": ["请开发和业务角色核对失败路径，再交叉检查验收条件"],
  "evidence_message_ids": [1, 2]
}
```

Use actual event IDs. Evidence may reference messages, drafts or reviews;
`conclude` must include message evidence from every participant. All fields are
required. `conclude` requires an empty `blocking_questions` list and a complete
round with no pending replies/reviews. `continue` needs concrete gaps or next steps.

```bash
python3 /path/to/agent-chat/scripts/chat.py assess \
  --room /shared/discussion.sqlite --as HOST \
  --request-id readiness-1 --file /shared/assessment.json
```

For `decision: "conclude"`, proceed to `chat.py propose` and the normal peer/role
review. New foreground rooms reject a draft without a fresh conclude assessment.
New messages or reviews invalidate the assessment for the next draft, so assess
again before revising after criticism. The gate checks provenance and the
decision's structure, not the semantic truth of the host's judgement.

For `decision: "continue"`, do not produce a conclusion draft. If unused initial
budget remains, continue within it. At a limit, explain the gaps and the expected
benefit of another exchange, propose a concrete extension (e.g. two rounds and
ten minutes), and **wait for the user's decision**. The user explicitly chose
to approve each extension after hearing its reason; default automatic allowance
is zero. Do not silently increase the budget or use a new room as a workaround.

If the user declines, use `chat.py stop` with that reason and export an honest
partial record. Do not erase blockers to manufacture agreement. If the user has
already explicitly requested "再讨论两轮" or "延长十分钟", that is authorization;
perform that extension without asking them to approve the same thing again.

## 2. Extend only after the user's continuation instruction

```bash
python3 /path/to/agent-chat/scripts/chat.py extend \
  --room /shared/discussion.sqlite --as HOST --request-id extension-1 \
  --rounds 2 --minutes 10 --reason '用户确认再讨论两轮，核对失败路径及验收条件'
```

Only the existing host can assess or extend. Use new request IDs for new actions;
repeating the same extension ID returns the original event, adding no more budget.

- `--rounds N` adds N rounds in a role room, or 2N ordinary message slots in a
  two-person room. `--minutes M` adds M discussion minutes from the later of now
  and the existing deadline. Each addition supports 0–20 rounds / 0–120 minutes.
- If only rounds are given and time already expired, ten minutes are renewed so
  the requested continuation can actually run. The returned event records this.
- If only minutes are given after the round/message budget is exhausted, one
  round is also added. To extend time solely for reassessment/a fresh draft and
  review, explicitly use `--rounds 0 --minutes M`.
- The usual review window follows the renewed discussion deadline: 2 minutes for
  two-person rooms, 10 minutes for role rooms. If even the review window expired,
  an explicit extension is needed before a new draft/review can be submitted.
- A room may be resumed after expiry, stopping, or confirmation, when explicitly
  requested. No model is called merely by extending. Stop or wait for any active
  foreground execution before extending; the tool refuses to alter a live call.

Existing native IDs and cursors are retained. Role mode can recover a native ID
from its SQLite session record if the status copy is missing. If an established
session cannot be recovered, report that error; never start a replacement or
silently drop the role. A role that has never established a session may still
make its initial call. Missing/expired provider-side sessions can also fail:
surface the CLI error instead of silently falling back to a new session.

Old drafts and reviews remain visible history. They do not act as the current
conclusion after continuation. A fresh conclusion needs a new assessment and
new explicit reviews from the participants. Request caches and old records remain
intact; committed old requests are readable but uncommitted old responses cannot
be inserted across the continuation boundary. The new period allows four drafts.

## 3. Resume the due participants in this same room

Inspect `chat.py status` or the mode-specific status. If a role round or two-person
exchange was interrupted halfway, finish the due replies using NEW request IDs;
do not duplicate the host's pending message. When the host is due, write a focused
follow-up with the confirmed scope and unresolved questions, then call the roles.

```bash
python3 /path/to/agent-chat/scripts/chat.py send \
  --room /shared/discussion.sqlite --as HOST --request-id host-after-extension \
  --text-file /shared/follow-up.txt
python3 /path/to/agent-chat/scripts/group.py round \
  --room /shared/discussion.sqlite --request-id continued-roles-1
```

For a two-person room, use `consult.py reply` instead of `group.py round`.
Each CLI must resume the SAME native ID. Native role context remains in place;
after continuation, role calls also receive the refreshed public transcript so
earlier replies cannot be skipped by a cursor after an interrupted round. They
receive the same frozen snapshot within each resumed batch/round.

Continue waiting for foreground calls as usual. When considering a draft again,
return to step 1. Do not end a host turn merely because an extension succeeded.
If awaiting the user's extension decision, explain why and what concrete budget
you propose; their response naturally resumes the original host conversation.

Existing v0.6 rooms are supported without reinitialization or copying the room.
They adopt the new assessment gate on their first assessment or continuation;
new foreground rooms have the gate from initialization. Optional old background
modes must first release their runners/locks; this flow retains the original
live host and does not start a replacement coordinator.

In all examples replace `HOST` with the original initiating identity (Codex, Claude,
pi, OpenCode or your configured label). Being host never requires a new host CLI.
