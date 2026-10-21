# Reconcile reviews and save the final conclusion

An accepted proposal is a reviewed draft. Its final review can still contain
nonblocking suggestions. Do not end the user turn, export it as a completed final
result, or report only the earlier draft until the original host handles that reply.

New and existing foreground rooms with lifecycle metadata enter `phase=finalizing`
and `finalization_status=pending` after every participant accepts. Their
`conclusion_status=confirmed` remains the draft's review status for compatibility;
it does NOT mean the host's final conclusion has been saved. Use the new fields.
No model is called automatically, and this stage consumes no discussion rounds.

## Read all reviews

Use consult/group status and `chat.py read` (follow pagination) to read every
current review, including the LAST response. `review_feedback` contains current
review events. Split each response into its individual corrections, caveats and
suggestions. Compare them against the accepted proposal and original host context.

- Incorporate clarifications that preserve the accepted plan and its constraints.
- If already covered, point to how the conclusion covers it.
- If not adopted, give a public reason; do not imply the reviewer endorsed that choice.
- If evidence is missing, preserve the point as an uncertainty or follow-up.
- Factual corrections, changed constraints, changed recommendations or unresolved
  material objections require re-review, even when the reviewer labelled its reply
  accept. Record a fresh conclude assessment, submit a revised proposal, and call
  the original participants to review it. Preserve native sessions and the usual
  four-proposal cap. If review time has expired, explain the needed extension and
  await the user's decision; do not automatically add budget.

## Save a finalization record

Write JSON to `DISCUSSION_DIR/finalization.json`, following
[the example](../examples/finalization.json). Replace its sample IDs and quoted
text with real records. Fields:

- `proposal_id`: current accepted proposal ID.
- `review_ids`: every current review ID, exactly once.
- `change_type`: `none` preserves the reviewed conclusion exactly;
  `clarification` only adds nonmaterial explanation. `substantive` is rejected:
  use the re-review flow instead.
- `conclusion`: the same summary/agreements/disagreements/open_questions/
  evidence_message_ids schema as a proposal. Include real discussion evidence
  from every participant. Make all accepted clarifications and retained unknowns
  visible here, not only in the resolution notes.
- `resolutions`: one entry PER feedback point. Each entry has `review_id`, `point`
  (an exact excerpt of that review), `disposition` (`incorporated`, `already_covered`,
  `not_adopted`, `follow_up`), and `resolution` (what changed or why, in public language).
  A review with no requested changes still needs an explicit already_covered entry.

```bash
python3 /path/to/agent-meet/scripts/chat.py finalize \
  --room ROOM --as HOST --request-id final-1 --file DISCUSSION_DIR/finalization.json
```

Only the original host may finalize. All current reviews and their resolutions
must be present; pending/rejected reviews, stale proposal IDs and invented quotes
are refused. Retries of the same successful request return its saved event.
Changed retries fail. These checks verify structure, evidence and review coverage;
they cannot judge whether every semantic point is handled correctly. The host
must not collapse multiple distinct feedback points into a generic acknowledgement.

Success returns `finalization_status=finalized`, `latest_finalization`, and a closed
agreement state. The immutable event contains the exact final conclusion and
resolution notes. The original proposal and all reviews remain in history.
Clarification text is labelled as a host reconciliation based on the accepted
draft, rather than falsely claiming the new wording was reviewed again.

## Export and report the same result

The page and Markdown export select `latest_finalization.body.conclusion` as the
current result. They display the feedback resolutions too. Before finalization,
exports remain available as snapshots labelled "reviewed draft, awaiting host".
Stopped or incomplete rooms do not acquire an invented final conclusion.

Read the saved finalization back. Write its EXACT `conclusion` object to
`DISCUSSION_DIR/final-conclusion.json` using the file-writing tool, then export the
current report. Link that final file/report to the user. Keep `conclusion.json`
labelled as the earlier draft; never link it as the final result after clarifications.
Base the user-facing answer on the saved final conclusion, including adopted
additions, disagreements and remaining uncertainties. Do not summarize from the
older proposal or omit the last reviewer response.

After a user-approved continuation, the old finalization is history and no longer
the current result. Reuse the same room and native sessions, then reassess, review
and finalize the new conclusion. Old exports remain unchanged snapshots.
