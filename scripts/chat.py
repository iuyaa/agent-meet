#!/usr/bin/env python3
"""Local, two-participant discussions. Python standard library only."""

import argparse
import contextlib
import datetime as dt
import json
import math
import re
import sqlite3
import sys
import time
from pathlib import Path

VERSION = 1
MAX_TEXT = 24000
SCHEMA = """
CREATE TABLE room (
  singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
  version INTEGER NOT NULL, topic TEXT NOT NULL, participants TEXT NOT NULL,
  created REAL NOT NULL, discuss_until REAL NOT NULL, expires REAL NOT NULL,
  max_messages INTEGER NOT NULL, stop_reason TEXT
);
CREATE TABLE members (name TEXT PRIMARY KEY, joined REAL NOT NULL);
CREATE TABLE events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, sender TEXT NOT NULL,
  kind TEXT NOT NULL, body TEXT NOT NULL, reply_to INTEGER,
  request_id TEXT NOT NULL, created REAL NOT NULL,
  UNIQUE(sender, request_id), FOREIGN KEY(reply_to) REFERENCES events(id)
);
"""


class ChatError(Exception):
    pass


def fail(message):
    raise ChatError(message)


def nonempty(value, label="text"):
    if not isinstance(value, str) or not value.strip():
        fail(f"{label} must be a nonempty string")
    if len(value) > MAX_TEXT:
        fail(f"{label} exceeds {MAX_TEXT} characters")
    return value.strip()


def utc(timestamp):
    return dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).isoformat()


@contextlib.contextmanager
def database(path, write=False):
    target = Path(path).resolve()
    if not target.is_file():
        fail("discussion not found; create it first")
    conn = sqlite3.connect(target.as_uri() + "?mode=rw", uri=True, timeout=5,
                           isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        row = conn.execute("SELECT * FROM room WHERE singleton = 1").fetchone()
        if not row or row["version"] != VERSION:
            fail("unsupported discussion format")
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def event(row):
    result = dict(row)
    result["created"] = utc(result["created"])
    if result["kind"] in ("proposal", "review"):
        result["body"] = json.loads(result["body"])
    return result


def state(conn):
    room = dict(conn.execute("SELECT * FROM room").fetchone())
    names = json.loads(room["participants"])
    joined = [r[0] for r in conn.execute("SELECT name FROM members ORDER BY joined, name")]
    count = conn.execute("SELECT COUNT(*) FROM events WHERE kind = 'message'").fetchone()[0]
    last = conn.execute("SELECT * FROM events WHERE kind = 'message' ORDER BY id DESC LIMIT 1").fetchone()
    proposal = conn.execute("SELECT * FROM events WHERE kind = 'proposal' ORDER BY id DESC LIMIT 1").fetchone()
    review = None
    if proposal:
        review = conn.execute("SELECT * FROM events WHERE kind = 'review' AND reply_to = ?",
                              (proposal["id"],)).fetchone()
    now = time.time()
    reason = None
    if room["stop_reason"]:
        reason = room["stop_reason"]
    elif review and json.loads(review["body"])["decision"] == "accept":
        reason = "agreement"
    elif now >= room["expires"]:
        reason = "expired"
    phase = "closed" if reason else (
        "summarizing" if count >= room["max_messages"] or now >= room["discuss_until"]
        else "discussing")
    return {
        "topic": room["topic"], "participants": names, "joined": joined,
        "phase": phase, "close_reason": reason,
        "message_count": count, "max_messages": room["max_messages"],
        "next_speaker": names[0] if not last else next(n for n in names if n != last["sender"]),
        "discuss_until": utc(room["discuss_until"]), "expires_at": utc(room["expires"]),
        "latest_proposal": event(proposal) if proposal else None,
        "latest_review": event(review) if review else None,
        "conclusion_status": "none" if not proposal else (
            "unconfirmed" if not review else
            "confirmed" if json.loads(review["body"])["decision"] == "accept" else "disputed"),
    }


def identity(conn, name):
    if name not in json.loads(conn.execute("SELECT participants FROM room").fetchone()[0]):
        fail("identity is not one of the two participants")
    if not conn.execute("SELECT 1 FROM members WHERE name = ?", (name,)).fetchone():
        fail("join with this identity first")


def next_action(status, name):
    if status["phase"] == "closed":
        return "export"
    proposal = status["latest_proposal"]
    if proposal and not status["latest_review"]:
        return "wait" if proposal["sender"] == name else "review"
    if status["phase"] == "summarizing" or (
            status["latest_review"] and status["conclusion_status"] == "disputed"):
        return "propose" if name == status["participants"][0] else "wait_or_propose"
    return "send_or_propose" if status["next_speaker"] == name else "wait"


def create(args):
    topic = nonempty(args.topic, "topic")
    names = args.participants
    if len(set(names)) != 2 or any(not re.fullmatch(r"[a-zA-Z0-9_-]{1,48}", n) for n in names):
        fail("choose two different identities using letters, digits, '_' or '-' (1–48 characters)")
    if not 2 <= args.max_messages <= 100:
        fail("max-messages must be between 2 and 100")
    if not math.isfinite(args.minutes) or not 0 < args.minutes <= 120:
        fail("minutes must be greater than 0 and at most 120")
    target = Path(args.room).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation refuses to overwrite an existing discussion.
    with target.open("xb"):
        pass
    now = time.time()
    conn = sqlite3.connect(target)
    try:
        conn.executescript(SCHEMA)
        conn.execute("INSERT INTO room VALUES (1, ?, ?, ?, ?, ?, ?, ?, NULL)",
                     (VERSION, topic, json.dumps(names), now, now + args.minutes * 60,
                      now + args.minutes * 60 + 120, args.max_messages))
        conn.commit()
    finally:
        conn.close()
    with database(target) as conn:
        return {"room": str(target), "status": state(conn)}


def join(args):
    with database(args.room, write=True) as conn:
        status = state(conn)
        if args.agent not in status["participants"]:
            fail("identity is not one of the two participants")
        if status["phase"] == "closed":
            fail("discussion is closed")
        conn.execute("INSERT OR IGNORE INTO members VALUES (?, ?)", (args.agent, time.time()))
        status = state(conn)
        return {"agent": args.agent, "status": status, "next_action": next_action(status, args.agent),
                "read_from": 0}


def body_text(args):
    text = Path(args.text_file).read_text(encoding="utf-8") if args.text_file else args.text
    return nonempty(text)


def proposal_body(conn, args):
    data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    required = {"summary", "agreements", "disagreements", "open_questions", "evidence_message_ids"}
    if not isinstance(data, dict) or set(data) != required:
        fail("proposal must contain exactly: " + ", ".join(sorted(required)))
    nonempty(data["summary"], "summary")
    for key in ("agreements", "disagreements", "open_questions"):
        if not isinstance(data[key], list):
            fail(f"{key} must be a list of strings")
        for value in data[key]:
            nonempty(value, key)
    ids = data["evidence_message_ids"]
    if not isinstance(ids, list) or not ids or any(type(i) is not int or i <= 0 for i in ids):
        fail("evidence_message_ids must be a nonempty list of positive integer message IDs")
    authors = set()
    for message_id in ids:
        row = conn.execute("SELECT sender FROM events WHERE id = ? AND kind = 'message'", (message_id,)).fetchone()
        if not row:
            fail(f"evidence message {message_id} does not exist or is not a discussion message")
        authors.add(row["sender"])
    names = set(json.loads(conn.execute("SELECT participants FROM room").fetchone()[0]))
    if authors != names:
        fail("a proposal needs evidence from both participants")
    return nonempty(json.dumps(data, ensure_ascii=False), "proposal")


def append(args):
    kind = {"send": "message", "propose": "proposal", "review": "review"}[args.command]
    request_id = nonempty(args.request_id, "request-id")
    with database(args.room, write=True) as conn:
        identity(conn, args.agent)
        reply_to = getattr(args, "reply_to", None)
        if kind == "message":
            body = body_text(args)
        elif kind == "proposal":
            body = proposal_body(conn, args)
        else:
            reply_to = args.proposal
            body = json.dumps({"decision": args.decision, "comment": body_text(args)}, ensure_ascii=False)
        existing = conn.execute("SELECT * FROM events WHERE sender = ? AND request_id = ?",
                                (args.agent, request_id)).fetchone()
        if existing:
            if (existing["kind"], existing["body"], existing["reply_to"]) != (kind, body, reply_to):
                fail("request-id already used with different content; choose a new ID")
            return {"event": event(existing), "duplicate": True, "status": state(conn)}
        status = state(conn)
        if status["phase"] == "closed":
            fail("discussion is closed; read or export the existing record")
        pending = status["latest_proposal"] and not status["latest_review"]
        if kind == "message":
            if status["phase"] != "discussing":
                fail("discussion budget reached; propose or review a conclusion instead")
            if pending:
                fail("review the pending proposal before continuing the discussion")
            if args.agent != status["next_speaker"]:
                fail("wait for the other participant's reply")
            if reply_to is not None:
                parent = conn.execute("SELECT sender, kind FROM events WHERE id = ?", (reply_to,)).fetchone()
                if not parent or parent["kind"] != "message" or parent["sender"] == args.agent:
                    fail("reply-to must reference the other participant's discussion message")
        elif kind == "proposal":
            if pending:
                fail("a conclusion proposal is already awaiting review")
            proposals = conn.execute("SELECT COUNT(*) FROM events WHERE kind = 'proposal'").fetchone()[0]
            if proposals >= 4:
                fail("four proposal attempts used; stop and export remaining disagreements")
        else:
            proposal = status["latest_proposal"]
            if not pending or proposal["id"] != reply_to:
                fail("review must target the current unreviewed proposal")
            if proposal["sender"] == args.agent:
                fail("the other participant must review the proposal")
        cursor = conn.execute(
            "INSERT INTO events(sender, kind, body, reply_to, request_id, created) VALUES (?, ?, ?, ?, ?, ?)",
            (args.agent, kind, body, reply_to, request_id, time.time()))
        row = conn.execute("SELECT * FROM events WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return {"event": event(row), "duplicate": False, "status": state(conn)}


def read_once(args):
    with database(args.room) as conn:
        identity(conn, args.agent)
        rows = conn.execute("SELECT * FROM events WHERE id > ? ORDER BY id LIMIT 101", (args.after,)).fetchall()
        messages = [event(row) for row in rows[:100]]
        status = state(conn)
        return {"events": messages, "next_after": messages[-1]["id"] if messages else args.after,
                "has_more": len(rows) > 100, "status": status,
                "next_action": next_action(status, args.agent)}


def read(args):
    if args.after < 0:
        fail("after must be nonnegative")
    timeout = getattr(args, "timeout", 0)
    if not math.isfinite(timeout) or not 0 <= timeout <= 30:
        fail("timeout must be between 0 and 30 seconds")
    until = time.monotonic() + timeout
    while True:
        result = read_once(args)
        if result["events"] or result["status"]["phase"] == "closed" or time.monotonic() >= until:
            result["timed_out"] = not result["events"] and result["status"]["phase"] != "closed"
            return result
        time.sleep(min(0.2, max(0, until - time.monotonic())))


def get_status(args):
    with database(args.room) as conn:
        return {"status": state(conn)}


def stop(args):
    reason = nonempty(args.reason, "reason")
    with database(args.room, write=True) as conn:
        if state(conn)["phase"] != "closed":
            conn.execute("UPDATE room SET stop_reason = ?", ("stopped: " + reason,))
        return {"status": state(conn)}


def export(args):
    with database(args.room) as conn:
        status = state(conn)
        events = [event(row) for row in conn.execute("SELECT * FROM events ORDER BY id")]
    lines = ["# 双 Agent 讨论记录", "", "## 讨论问题", "", status["topic"], "",
             "参与者：" + ", ".join(status["participants"]),
             "阶段：" + status["phase"], "结束原因：" + str(status["close_reason"] or "尚未结束"), ""]
    proposal = status["latest_proposal"]
    labels = {"none": "尚无结论", "unconfirmed": "单方草案，尚未得到另一方确认",
              "confirmed": "双方已确认（可包含已确认保留的分歧）", "disputed": "另一方提出异议，尚未确认"}
    lines.extend(["## 讨论结果", "", labels[status["conclusion_status"]], ""])
    if proposal:
        body = proposal["body"]
        lines.extend([f"草案 #{proposal['id']}，作者：{proposal['sender']}", "", body["summary"], ""])
        for key, label in (("agreements", "共识"), ("disagreements", "分歧"), ("open_questions", "待确认问题")):
            lines.extend([f"### {label}", ""] + ["- " + v for v in body[key]] + ([] if body[key] else ["未列出"]) + [""])
        lines.extend(["依据消息：" + ", ".join("#" + str(i) for i in body["evidence_message_ids"]), ""])
    lines.extend(["## 完整记录", ""])
    for item in events:
        content = item["body"] if isinstance(item["body"], str) else json.dumps(item["body"], ensure_ascii=False, indent=2)
        lines.extend([f"### #{item['id']} {item['sender']} · {item['kind']} · {item['created']}", "", content, ""])
    output = Path(args.output).resolve()
    if output == Path(args.room).resolve():
        fail("export path cannot be the discussion database")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Keep prior exports intact; choose a different filename to refresh a snapshot.
    with output.open("x", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return {"output": str(output), "event_count": len(events), "conclusion_status": status["conclusion_status"]}


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    sub = result.add_subparsers(dest="command", required=True)
    for name in ("create", "join", "status", "send", "read", "wait", "propose", "review", "stop", "export"):
        p = sub.add_parser(name)
        p.add_argument("--room", required=True, help="absolute path of the shared SQLite discussion file")
        if name in ("join", "send", "read", "wait", "propose", "review"):
            p.add_argument("--as", dest="agent", required=True)
        if name in ("send", "propose", "review"):
            p.add_argument("--request-id", required=True, help="reuse unchanged on retries")
        if name in ("send", "review"):
            group = p.add_mutually_exclusive_group(required=True)
            group.add_argument("--text")
            group.add_argument("--text-file", help="UTF-8 file; preferred for multiline or shell-sensitive content")
        if name == "create":
            p.add_argument("--topic", required=True)
            p.add_argument("--participants", nargs=2, default=["codex", "claude"])
            p.add_argument("--max-messages", type=int, default=12)
            p.add_argument("--minutes", type=float, default=10)
        elif name == "send":
            p.add_argument("--reply-to", type=int)
        elif name in ("read", "wait"):
            p.add_argument("--after", type=int, default=0)
            if name == "wait":
                p.add_argument("--timeout", type=float, default=25)
        elif name == "propose":
            p.add_argument("--file", required=True, help="UTF-8 conclusion JSON")
        elif name == "review":
            p.add_argument("--proposal", type=int, required=True)
            p.add_argument("--decision", choices=["accept", "reject"], required=True)
        elif name == "stop":
            p.add_argument("--reason", default="user requested stop")
        elif name == "export":
            p.add_argument("--output", required=True)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    handlers = {"create": create, "join": join, "status": get_status,
                "send": append, "read": read, "wait": read, "propose": append,
                "review": append, "stop": stop, "export": export}
    try:
        result = handlers[args.command](args)
        print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
        return 0
    except (ChatError, OSError, sqlite3.Error, ValueError, OverflowError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
