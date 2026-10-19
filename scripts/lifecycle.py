"""Assess readiness and extend an existing room without replacing native sessions."""

import contextlib
import json
import math
import os
import time
from pathlib import Path

import chat


def installed(conn):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='discussion_lifecycle'").fetchone())


def setup(conn, auto_rounds=0, auto_minutes=0):
    if not 0 <= auto_rounds <= 20 or not math.isfinite(auto_minutes) or not 0 <= auto_minutes <= 120:
        chat.fail("automatic extension limits must be 0–20 rounds and 0–120 minutes")
    conn.execute("CREATE TABLE IF NOT EXISTS discussion_lifecycle(singleton INTEGER PRIMARY KEY,epoch INTEGER NOT NULL,anchor INTEGER NOT NULL,policy TEXT NOT NULL)")
    policy = {"auto_rounds": auto_rounds, "auto_minutes": auto_minutes,
              "used_rounds": 0, "used_minutes": 0}
    conn.execute("INSERT OR IGNORE INTO discussion_lifecycle VALUES(1,0,0,?)", (json.dumps(policy),))


def metadata(conn):
    if not installed(conn):
        return {"epoch": 0, "anchor": 0, "policy": {"auto_rounds": 0, "auto_minutes": 0, "used_rounds": 0, "used_minutes": 0}}
    row = dict(conn.execute("SELECT * FROM discussion_lifecycle WHERE singleton=1").fetchone())
    row["policy"] = json.loads(row["policy"])
    return row


def activity(conn):
    return conn.execute("SELECT COALESCE(MAX(id),0) FROM events WHERE kind IN ('message','review','extension')").fetchone()[0]


def enrich(conn, value):
    info = metadata(conn)
    row = conn.execute("SELECT * FROM events WHERE kind='assessment' AND id>? ORDER BY id DESC LIMIT 1", (info["anchor"],)).fetchone()
    assessment = chat.event(row) if row else None
    fresh = bool(assessment and assessment["body"]["based_on"] == activity(conn))
    policy = info["policy"]
    value.update(epoch=info["epoch"], assessment_required=installed(conn), latest_assessment=assessment,
                 assessment_fresh=fresh, assessment_status=assessment["body"]["assessment"]["decision"] if fresh else "stale" if assessment else "missing",
                 auto_extension={"remaining_rounds": policy["auto_rounds"] - policy["used_rounds"],
                                 "remaining_minutes": policy["auto_minutes"] - policy["used_minutes"]},
                 latest_extension=chat.event(conn.execute("SELECT * FROM events WHERE kind='extension' ORDER BY id DESC LIMIT 1").fetchone()) if info["anchor"] else None)
    value["continuation_needs_approval"] = bool(fresh and value["assessment_status"] == "continue" and value["phase"] != "discussing"
                                                 and not str(value["close_reason"] or "").startswith("stopped:"))
    return value


def require_conclusion(conn, value):
    if installed(conn) and (not value["assessment_fresh"] or value["assessment_status"] != "conclude"):
        chat.fail("record a fresh host assessment deciding 'conclude' before proposing; use chat.py assess")


def main_identity(value):
    return value.get("main", value["participants"][0])


def validate_assessment(conn, body, value):
    keys = {"decision", "reason", "blocking_questions", "accepted_uncertainties", "next_steps", "evidence_message_ids"}
    if not isinstance(body, dict) or set(body) != keys:
        chat.fail("assessment must contain exactly: " + ", ".join(sorted(keys)))
    if body["decision"] not in ("conclude", "continue"):
        chat.fail("assessment decision must be conclude or continue")
    chat.nonempty(body["reason"], "reason")
    for key in ("blocking_questions", "accepted_uncertainties", "next_steps"):
        if not isinstance(body[key], list):
            chat.fail(key + " must be a list of strings")
        for text in body[key]:
            chat.nonempty(text, key)
    if body["decision"] == "conclude" and body["blocking_questions"]:
        chat.fail("a conclusion assessment cannot leave blocking questions unresolved")
    if body["decision"] == "continue" and not (body["blocking_questions"] or body["next_steps"]):
        chat.fail("continuing needs concrete blocking questions or next steps")
    ids = body["evidence_message_ids"]
    if not isinstance(ids, list) or not ids or any(type(i) is not int or i <= 0 for i in ids):
        chat.fail("assessment evidence must contain positive event IDs")
    authors = set()
    for event_id in ids:
        row = conn.execute("SELECT * FROM events WHERE id=? AND kind IN ('message','proposal','review')", (event_id,)).fetchone()
        if not row:
            chat.fail("assessment evidence does not reference an actual discussion event")
        if row["kind"] == "message":
            authors.add(row["sender"])
    if body["decision"] == "conclude":
        if authors != set(value["participants"]):
            chat.fail("concluding requires evidence from every participant")
        if value.get("mode") == "group":
            current_authors = {r[0] for r in conn.execute("SELECT sender FROM events WHERE kind='message' AND round_index=?", (value["current_round"],))}
            if current_authors != set(value["participants"]) or value["pending_reviewers"]:
                chat.fail("finish the round and pending reviews before concluding")
        elif value["next_speaker"] != main_identity(value) or (value["latest_proposal"] and not value["latest_review"]):
            chat.fail("wait for the peer's reply/review before concluding")
    chat.nonempty(json.dumps(body, ensure_ascii=False), "assessment")


def record(conn, agent, kind, request_id, body, round_index=1):
    columns = "sender,kind,body,request_id,created"
    values = [agent, kind, json.dumps(body, ensure_ascii=False), request_id, time.time()]
    if conn.execute("SELECT version FROM room").fetchone()[0] == 2:
        columns += ",round_index"
        values.append(round_index)
    placeholders = ",".join("?" for _ in values)
    cursor = conn.execute(f"INSERT INTO events({columns}) VALUES({placeholders})", values)
    return chat.event(conn.execute("SELECT * FROM events WHERE id=?", (cursor.lastrowid,)).fetchone())


def assess(args):
    body = json.loads(Path(args.file).read_text(encoding="utf-8-sig"))
    request_id = chat.nonempty(args.request_id, "request-id")
    with chat.database(args.room, write=True) as conn:
        value = chat.state(conn)
        chat.identity(conn, args.agent)
        if args.agent != main_identity(value):
            chat.fail("only the original host may assess whether to conclude or continue")
        existing = conn.execute("SELECT * FROM events WHERE sender=? AND request_id=?", (args.agent, request_id)).fetchone()
        if existing:
            event = chat.event(existing)
            if event["kind"] != "assessment" or event["body"]["assessment"] != body:
                chat.fail("request-id already used with different content")
            return {"event": event, "duplicate": True, "status": value}
        validate_assessment(conn, body, value)
        setup(conn)
        event = record(conn, args.agent, "assessment", request_id,
                       {"assessment": body, "based_on": activity(conn)}, value.get("current_round", 1))
        return {"event": event, "duplicate": False, "status": chat.state(conn)}


@contextlib.contextmanager
def runner_locks(room, participants):
    import peer
    target = str(Path(room).resolve())
    with contextlib.ExitStack() as stack:
        # Lock in the same order as each foreground runner, before opening a write transaction.
        for root in (Path(target + ".consult"), Path(target + ".group")):
            if root.exists():
                stack.enter_context(peer.participant_lock(root))
        for name in sorted(participants):
            root = peer.paths(room, name)
            if root.exists():
                stack.enter_context(peer.participant_lock(root))
                info = peer.read_status(root)
                pid = info.get("child_pid")
                if pid:
                    if os.name == "nt":
                        chat.fail("role status still reports an active CLI; inspect or stop it before extending")
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        pass
                    else:
                        chat.fail("a previous role CLI is still running; wait or stop it before extending")
        yield


def extend(args):
    import peer
    request_id = chat.nonempty(args.request_id, "request-id")
    reason = chat.nonempty(args.reason, "reason")
    rounds, minutes = args.rounds, args.minutes
    if rounds is not None and not 0 <= rounds <= 20:
        chat.fail("added rounds must be 0–20")
    if minutes is not None and (not math.isfinite(minutes) or not 0 <= minutes <= 120):
        chat.fail("added minutes must be 0–120")
    if not rounds and not minutes:
        chat.fail("provide positive --rounds or --minutes")
    intent = {"rounds": rounds, "minutes": minutes, "reason": reason, "automatic": args.automatic}
    with chat.database(args.room) as conn:
        before = chat.state(conn)
    with runner_locks(args.room, before["participants"]):
        with chat.database(args.room, write=True) as conn:
            value = chat.state(conn)
            chat.identity(conn, args.agent)
            if args.agent != main_identity(value):
                chat.fail("only the original host may extend this discussion")
            existing = conn.execute("SELECT * FROM events WHERE sender=? AND request_id=?", (args.agent, request_id)).fetchone()
            if existing:
                event = chat.event(existing)
                if event["kind"] != "extension" or event["body"]["intent"] != intent:
                    chat.fail("request-id already used with different extension settings")
                return {"event": event, "duplicate": True, "status": value}
            setup(conn)
            info = metadata(conn)
            room = dict(conn.execute("SELECT * FROM room").fetchone())
            is_group = value.get("mode") == "group"
            exhausted = value["completed_rounds"] >= value["max_rounds"] if is_group else value["message_count"] >= value["max_messages"]
            added_rounds = rounds if rounds is not None else 1 if exhausted else 0
            added_minutes = minutes if minutes is not None else 10 if room["discuss_until"] <= time.time() else 0
            if room["discuss_until"] <= time.time() and added_minutes <= 0:
                chat.fail("discussion time expired; add minutes to continue")
            policy = info["policy"]
            if args.automatic:
                if value["close_reason"] and value["close_reason"] != "expired":
                    chat.fail("automatic continuation cannot reopen a stopped or confirmed discussion")
                if not value["assessment_fresh"] or value["assessment_status"] != "continue":
                    chat.fail("automatic extension needs a fresh host assessment deciding continue")
                if (policy["used_rounds"] + added_rounds > policy["auto_rounds"] or
                        policy["used_minutes"] + added_minutes > policy["auto_minutes"]):
                    chat.fail("automatic extension allowance exhausted; ask the user for a concrete extension")
                policy["used_rounds"] += added_rounds
                policy["used_minutes"] += added_minutes
            if is_group:
                import group
                settings = group.config(conn)
                settings["rounds"] += added_rounds
                conn.execute("UPDATE group_config SET body=?", (json.dumps(settings, ensure_ascii=False),))
                messages = settings["rounds"] * (len(settings["roles"]) + 1)
            else:
                messages = room["max_messages"] + 2 * added_rounds
            deadline = max(room["discuss_until"], time.time()) + added_minutes * 60 if added_minutes else room["discuss_until"]
            review_window = 600 if is_group else 120
            conn.execute("UPDATE room SET max_messages=?,discuss_until=?,expires=?,stop_reason=NULL", (messages, deadline, deadline + review_window))
            event = record(conn, args.agent, "extension", request_id,
                           {"intent": intent, "reason": reason, "added_rounds": added_rounds, "added_minutes": added_minutes,
                            "previous_close_reason": value["close_reason"], "previous_proposal_id": value["latest_proposal"]["id"] if value["latest_proposal"] else None,
                            "epoch": info["epoch"] + 1}, value.get("current_round", 1))
            conn.execute("UPDATE discussion_lifecycle SET epoch=?,anchor=?,policy=? WHERE singleton=1",
                         (info["epoch"] + 1, event["id"], json.dumps(policy)))
            result = {"event": event, "duplicate": False, "status": chat.state(conn)}
        # Retain native IDs, cursors, history and caches. Only clear obsolete in-flight markers.
        for root in [Path(str(Path(args.room).resolve()) + ".consult")] + [peer.paths(args.room, name) for name in before["participants"]]:
            if (root / "status.json").is_file():
                status = peer.read_status(root)
                status["pending_request"] = None
                status["child_pid"] = None
                peer.publish(root, status, "idle", detail=None)
        return result
