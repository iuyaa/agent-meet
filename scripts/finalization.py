"""Reconcile every final review before publishing the host's final conclusion."""

import json
from pathlib import Path

import chat
import lifecycle

DISPOSITIONS = ("incorporated", "already_covered", "not_adopted", "follow_up")


def reviews(value):
    if value.get("mode") == "group":
        return value["reviews"]
    return [value["latest_review"]] if value["latest_review"] else []


def enrich(conn, value):
    proposal = value["latest_proposal"]
    row = conn.execute("SELECT * FROM events WHERE kind='finalization' AND id>? ORDER BY id DESC LIMIT 1",
                       (lifecycle.metadata(conn)["anchor"],)).fetchone()
    final = chat.event(row) if row else None
    if not proposal or (final and final["body"]["proposal_id"] != proposal["id"]):
        final = None
    required = lifecycle.installed(conn)
    pending = required and value["conclusion_status"] == "confirmed" and not final
    value.update(finalization_required=required, latest_finalization=final,
                 finalization_status="finalized" if final else "pending" if pending else "not_ready" if required else "legacy",
                 review_feedback=reviews(value))
    if pending and value["close_reason"] == "agreement":
        value.update(phase="finalizing", close_reason=None)
        if value.get("mode") == "group":
            value["pending_speakers"] = []
    return value


def validate(conn, body, value):
    keys = {"proposal_id", "review_ids", "change_type", "conclusion", "resolutions"}
    if not isinstance(body, dict) or set(body) != keys:
        chat.fail("finalization must contain exactly: " + ", ".join(sorted(keys)))
    proposal = value["latest_proposal"]
    if type(body["proposal_id"]) is not int or not proposal or body["proposal_id"] != proposal["id"]:
        chat.fail("finalization must target the current proposal")
    if body["change_type"] == "substantive":
        chat.fail("substantive changes require a fresh assessment, revised proposal and participant reviews before finalizing")
    if body["change_type"] not in ("none", "clarification"):
        chat.fail("change_type must be none or clarification; substantive revisions require re-review")
    items = reviews(value)
    expected = {item["id"]: item for item in items}
    ids = body["review_ids"]
    if not isinstance(ids, list) or any(type(i) is not int for i in ids) or len(set(ids)) != len(ids) or set(ids) != set(expected):
        chat.fail("review_ids must include every current review exactly once, including the last response")
    conclusion = json.loads(chat.validate_conclusion(conn, body["conclusion"]))
    if body["change_type"] == "none" and conclusion != proposal["body"]:
        chat.fail("unchanged finalization must preserve the reviewed conclusion exactly")
    resolutions = body["resolutions"]
    if not isinstance(resolutions, list) or not resolutions:
        chat.fail("resolutions must explicitly handle every review and each of its feedback points")
    covered = set()
    for item in resolutions:
        if not isinstance(item, dict) or set(item) != {"review_id", "point", "disposition", "resolution"}:
            chat.fail("each resolution requires review_id, point, disposition and resolution")
        review_id = item["review_id"]
        if type(review_id) is not int or review_id not in expected:
            chat.fail("resolution must reference a current review")
        point = chat.nonempty(item["point"], "review point")
        if point not in expected[review_id]["body"]["comment"]:
            chat.fail("quote each feedback point from the referenced review; do not invent reviewer statements")
        if item["disposition"] not in DISPOSITIONS:
            chat.fail("invalid review resolution disposition")
        chat.nonempty(item["resolution"], "resolution and reason")
        covered.add(review_id)
    if covered != set(expected):
        chat.fail("every review must have explicit resolutions; do not omit the last role")
    chat.nonempty(json.dumps(body, ensure_ascii=False), "finalization")


def finalize(args):
    body = json.loads(Path(args.file).read_text(encoding="utf-8-sig"))
    request_id = chat.nonempty(args.request_id, "request-id")
    with chat.database(args.room, write=True) as conn:
        value = chat.state(conn)
        chat.identity(conn, args.agent)
        if args.agent != lifecycle.main_identity(value):
            chat.fail("only the original host may reconcile reviews and save the final conclusion")
        existing = conn.execute("SELECT * FROM events WHERE sender=? AND request_id=?", (args.agent, request_id)).fetchone()
        if existing:
            event = chat.event(existing)
            if event["kind"] != "finalization" or event["body"] != body:
                chat.fail("request-id already used with different content")
            return {"event": event, "duplicate": True, "status": value}
        if value["conclusion_status"] != "confirmed":
            chat.fail("wait for every participant to accept the current proposal before finalizing")
        if value["close_reason"] not in (None, "agreement"):
            chat.fail("discussion is stopped or expired; preserve its actual state")
        if value["latest_finalization"]:
            chat.fail("this proposal already has a final conclusion; explicitly continue to reopen the discussion")
        if value["assessment_fresh"] and value["assessment_status"] == "continue":
            chat.fail("the host assessed that more discussion is needed; resolve that assessment first")
        validate(conn, body, value)
        event = lifecycle.record(conn, args.agent, "finalization", request_id, body, value.get("current_round", 1))
        return {"event": event, "duplicate": False, "status": chat.state(conn)}
