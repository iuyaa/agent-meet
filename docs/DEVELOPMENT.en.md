# Meet development guide

[简体中文](DEVELOPMENT.md) · English

[Back to README](../README.en.md) · [Usage guide](USAGE.en.md)

Meet uses the Python standard library, SQLite, and a local static web page. It requires neither the Golutra application nor a frontend build.
The repository root is also the skill root.

## Code layout

| File | Responsibility |
| --- | --- |
| `scripts/chat.py` | Event protocol, drafts, reviews, exports, and CLI entry point |
| `scripts/consult.py` | Individual two-agent calls that preserve the original host |
| `scripts/group.py` | Multi-role rounds, parallel calls, and review by all roles |
| `scripts/lifecycle.py` | Readiness assessments, user-approved extensions, and continuation in the original room |
| `scripts/finalization.py` | Final feedback reconciliation and conclusion finalization |
| `scripts/storage.py` | Separate project-local discussion directories and Git ignore rules |
| `scripts/adapters.py` | Command construction and output parsing for Claude, Codex, pi, and OpenCode |
| `scripts/peer.py` | Shared process control, timeouts, stopping, and native ID validation |
| `scripts/processes.py` | Console-free Windows launches and POSIX background session policy |
| `scripts/view.py`, `web/` | Local viewer service and message display |

`conclusion_status` continues to indicate whether a draft has been accepted in review.
Once all participants accept a foreground discussion's draft, it enters `phase=finalizing`.
Only `finalization_status=finalized` means the host has saved the final conclusion.
The page and exports use `latest_finalization.body.conclusion`. New events preserve the original drafts and reviews; older results remain as history after continuation.
The original manual/background protocol keeps its previous behavior when lifecycle metadata is absent.

Tools check that feedback comes from current reviews, every review has a disposition record, evidence refers to real messages, and native IDs have not been replaced.
They do not judge natural-language completeness or factual correctness; the host must assess those against project evidence.

## Local validation

```bash
python3 -m unittest discover -s tests -v
```

Tests use real temporary files, SQLite, and simulated CLI subprocesses. They do not call paid models.
Optional browser checks require Playwright and Chromium in the development environment; running the skill does not require them:

```bash
CHROMIUM=/path/to/chromium node tests/browser_view.cjs
CHROMIUM=/path/to/chromium node tests/browser_group.cjs
```

See the [validation record](../VALIDATION.en.md) for coverage, results, and real-environment limitations.

## Extensions and contributions

Read the [adapter guide](../references/agent-adapters.md) before adding an agent backend.
Command construction and output parsing belong in the adapters. Shared code manages stopping, timeouts, and session consistency.
Cover native session resumption, errors and truncated output, repeated requests, and interruption behavior.

This package is independently implemented and contains no copied Golutra application source or assets.
See [Migration](../MIGRATION.en.md) for its history and [alternative modes](../references/alternative-modes.md) for the original background workflows.
