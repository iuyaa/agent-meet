# Agent-Meet

[简体中文](README.md) · English

Bring different AI agents into a discussion from your current conversation.

When you need a second opinion or several roles to examine a problem, ask your current agent to start a discussion.
Meet calls the invited agents, records the exchange, and lets the original host draw conclusions using the context already in your conversation.
It supports **Codex, Claude Code, pi, and OpenCode** and runs independently of Golutra.

```text
$agent-meet Ask Claude to review this proposal, focusing on boundaries and failure paths.
```

Follow the messages, drafts, reviews, and final conclusion in a local group chat page.

## Get started

You need Python 3.9+ and an installed, configured local CLI for each invited agent.
Only the initiating agent needs the skill; the original host stays in its current conversation.

Run this from the project where you want to use it, then select the initiating agent when prompted:

```bash
npx skills add iuyaa/agent-meet --skill agent-meet
```

The default installation is local to the project; add `-g` to use it across projects.
Command installation requires Node.js 22.20+ and uses the existing Skills CLI to install from the repository.
The initiating agent must also be able to read and write files, run Python commands, and wait for tool results.
See [Installation](docs/INSTALLATION.en.md) for agent selection, updates, and manual installation.

Keep your current conversation and ask it to read the installed `SKILL.md`, then describe the discussion you want.
Skill discovery depends on the host version. In Codex, use `$agent-meet`; other hosts can use the skill name or path directly.

## Ways to use it

**Ask another agent to review a proposal**

```text
Use agent-meet to ask Codex to check whether this design is feasible.
Keep hosting with the constraints we have already agreed on, then report agreement and disagreements.
```

The initiating agent hosts from its original conversation. For example, Claude can invite Codex, and pi can invite OpenCode.

**Invite several roles**

```text
$agent-meet Have a product manager, architect, and business owner discuss this requirement for up to 3 rounds.
Use Claude by default and Codex for the architect. You host the discussion.
```

You choose the roles, their number, and their responsibilities. Invited roles default to Claude when no backend is specified.
Different roles using the same backend have separate sessions. The host can also take one of the requested roles.

**Continue the same discussion**

```text
Continue the previous discussion for two more rounds, focusing on the two remaining questions.
```

Extensions reuse the original room and role sessions. When the budget is exhausted and critical gaps remain, the host explains why more discussion is needed and lets you decide whether to extend it.

## How a discussion reaches a result

1. **Prepare the background:** the original host extracts the question, constraints, prior decisions, and unknowns from the current conversation into a briefing.
2. **Discuss in rounds:** participants read the briefing and discussion record, share views and evidence, and ask questions. The host follows up and adds context.
3. **Assess readiness:** the host checks whether the evidence supports a draft or explains what still needs discussion.
4. **Review and address final feedback:** participants review the draft. The host records whether each feedback point was incorporated, already covered, not adopted, or left for follow-up.
5. **Save the final conclusion:** the final text and feedback dispositions are saved together. The page, exports, and host's report use that result.

The host can finalize minor clarifications. Changes to factual judgments, constraints, or the proposed plan require another review.
The result preserves agreement, disagreements, open questions, and supporting messages. Review acceptance does not establish that every recommendation has been factually verified.

## View the process and find the data

<details>
<summary>Local discussion page example (scripted demo messages)</summary>

![Meet local discussion page with scripted demo messages](examples/chat-preview.png)

</details>

The local page shows recorded public messages and supports Markdown, folding, stopping, and exporting.
Ask follow-up questions in the original host conversation. Replies appear after they are complete and saved; private reasoning is not displayed.

Each discussion is saved in a separate directory within the project being discussed:

```text
PROJECT/.agent-meet/<timestamp-topic-ID>/discussion.sqlite
```

The briefing, role state, and call records stay in the same discussion directory, which is ignored by Git by default.
Explicit storage paths are also supported. Back up the entire discussion directory and each CLI's own native session data.

## Before you use it

- The original host retains your long conversation. Invited roles receive a briefing and later resume their own discussion sessions; they do not automatically receive the full original chat history.
- Model calls use each CLI's account and configuration and may incur charges. Meet does not provide model access.
- The page displays progress and results. It cannot wake a host UI turn that has already ended. Normal progress relies on waiting for tool results within the same turn.
- Automated validation currently uses simulated CLIs. Real accounts, models, and operating system combinations still need local verification.

When upgrading, preserve the room and state directories and have the current conversation reread the new `SKILL.md`.
Keep the original host and its history. An accepted older draft whose final feedback has not been reconciled will appear as awaiting finalization.

## More documentation

- [Installation and updates](docs/INSTALLATION.en.md): command installation, global installation, host selection, and manual setup.
- [Usage guide](docs/USAGE.en.md): roles, rounds, continuation, the viewer, and low-level commands.
- [Skill instructions](SKILL.md): the complete workflow for the hosting agent.
- [Final feedback and conclusions](references/finalization.md): finalization rules and input format.
- [Adapters and support](references/agent-adapters.md): CLIs, native session resumption, and version boundaries.
- [Development](docs/DEVELOPMENT.en.md) · [Validation record](VALIDATION.en.md) · [Changelog](CHANGELOG.md) · [Migration](MIGRATION.en.md).

Licensed under [MIT](LICENSE). See [third-party notices](web/vendor/README.md) for Marked and DOMPurify.
