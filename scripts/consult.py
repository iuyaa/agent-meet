#!/usr/bin/env python3
"""Keep the existing main agent and call Claude once per tool execution."""

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from pathlib import Path

import chat
import peer

BRIEF_STRINGS = ("question", "goal", "current_view")
BRIEF_LISTS = ("constraints", "decisions", "rejected_options", "code_references", "unknowns")
CONSULT_RULES = peer.RULES + """
In THIS mode, the main participant is the original live agent with a long-running
conversation, not a new background agent. You have only its context briefing,
project files and discussion events. Do not claim to know its complete history.
Treat empty briefing lists as information not supplied, not proof of absence.
Ask focused questions about missing constraints or decisions. Respect explicitly
recorded constraints; explain conflicts instead of silently replacing decisions.
The original main participant makes the final judgement. You may send a reply
or review its conclusion as allowed_actions specifies; do not propose a conclusion
on its behalf. Return this ONE turn now; the tool will return to that main agent.
"""


def directory(room):
    return Path(str(Path(room).resolve()) + ".consult")


def load_briefing(path):
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict) or set(value) != set(BRIEF_STRINGS + BRIEF_LISTS):
        chat.fail("briefing must contain exactly: " + ", ".join(BRIEF_STRINGS + BRIEF_LISTS))
    for key in BRIEF_STRINGS:
        chat.nonempty(value[key], key)
    for key in BRIEF_LISTS:
        if not isinstance(value[key], list):
            chat.fail(f"{key} must be a list of strings")
        for item in value[key]:
            chat.nonempty(item, key)
    chat.nonempty(json.dumps(value, ensure_ascii=False), "briefing")
    return value


def render_briefing(briefing):
    labels = {"question": "讨论问题", "goal": "目标", "current_view": "当前主参与者的判断",
              "constraints": "约束", "decisions": "已有决策", "rejected_options": "已否决方案及原因",
              "code_references": "代码依据", "unknowns": "待确认信息"}
    lines = ["# 讨论上下文简报", "", "这是当前会话整理的背景摘录，并非完整历史。空列表表示未提供。", ""]
    for key in BRIEF_STRINGS + BRIEF_LISTS:
        lines += ["## " + labels[key], ""]
        value = briefing[key]
        lines += [value] if isinstance(value, str) else ["- " + item for item in value] or ["未提供"]
        lines.append("")
    return chat.nonempty("\n".join(lines), "rendered briefing")


def configuration(room):
    path = directory(room) / "config.json"
    if not path.is_file():
        chat.fail("consultation not found; initialize it with a context briefing first")
    return json.loads(path.read_text(encoding="utf-8"))


def model_state(room):
    return peer.read_status(directory(room))


def snapshot(room, config):
    return peer.snapshot(argparse.Namespace(room=room, agent=config["reviewer"]))


def initialize(args):
    briefing = load_briefing(args.briefing_file)
    opening = render_briefing(briefing)
    root = directory(args.room)
    cwd = str(Path(args.cwd).resolve())
    if (root / "config.json").exists():
        config = configuration(args.room)
        if (config["briefing"], config["cwd"], config["main"], config["reviewer"]) != (
                briefing, cwd, args.main, args.reviewer):
            chat.fail("this consultation has different context or identities; choose a new room path")
        return {"already_initialized": True, **status(args.room)}
    peer.cli_prefix(args.cli, "claude")
    if not Path(cwd).is_dir():
        chat.fail("project directory does not exist")
    with peer.participant_lock(root):
        chat.create(argparse.Namespace(room=args.room, topic=briefing["question"],
                                       participants=[args.main, args.reviewer],
                                       max_messages=args.max_messages, minutes=args.minutes))
        for name in (args.main, args.reviewer):
            chat.join(argparse.Namespace(room=args.room, agent=name))
        config = {"mode": "existing-main", "main": args.main, "reviewer": args.reviewer,
                  "cwd": cwd, "cli": str(Path(shutil.which(args.cli)).resolve()), "briefing": briefing}
        peer.write_json(root / "config.json", config)
        (root / "briefing.md").write_text(opening + "\n", encoding="utf-8")
        peer.write_json(root / "briefing.json", briefing)
        peer.publish(root, {"native_session_id": None, "read_cursor": 0, "next_turn": 1,
                            "completed_turn": 0, "pending_request": None}, "idle")
        chat.append(argparse.Namespace(room=args.room, agent=args.main, command="send",
                                       request_id="consult-opening", text=opening, text_file=None, reply_to=None))
    return {"already_initialized": False, **status(args.room)}


def status(room):
    config = configuration(room)
    current, _ = snapshot(room, config)
    return {"mode": "existing-main", "main": config["main"], "reviewer": config["reviewer"],
            "briefing_file": str(directory(room) / "briefing.md"), "briefing": config["briefing"],
            "model": model_state(room), "status": current,
            "next_action": "finish" if current["phase"] == "closed" else "original main continues after the tool result"}


def reply(args):
    if not 1 <= args.turn_timeout <= 600:
        chat.fail("turn-timeout must be between 1 and 600 seconds")
    request_id = chat.nonempty(args.request_id, "request-id")
    if len(request_id) > 200:
        chat.fail("request-id must be at most 200 characters")
    root = directory(args.room)
    config = configuration(args.room)
    peer_root = peer.paths(args.room, config["reviewer"])
    digest = hashlib.sha256(request_id.encode("utf-8")).hexdigest()
    cache_path = root / (digest + ".json")
    event_request_id = "consult-" + digest + "-0"
    with peer.participant_lock(root), peer.participant_lock(peer_root):
        current, events = snapshot(args.room, config)
        info = model_state(args.room)
        cached = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else None
        existing = next((e for e in events if e["sender"] == config["reviewer"] and
                         e["request_id"] == event_request_id), None)
        if existing:
            # Recover bookkeeping after a committed protocol write whose output
            # or sidecar update was lost. Never move the read cursor backwards.
            if cached and cached.get("result") and cached["turn"] >= info["completed_turn"]:
                info.update(native_session_id=cached["native_session_id"], read_cursor=cached["read_cursor"],
                            completed_turn=cached["turn"], pending_request=None)
                peer.publish(root, info, "idle")
            return {"event": existing, "duplicate": True, **status(args.room)}
        if current["phase"] == "closed":
            chat.fail("discussion is closed; export it instead of calling Claude")
        if info["pending_request"] and info["pending_request"] != request_id:
            peer.publish(root, info, "failed", pending_request=None,
                         detail="an earlier call was interrupted; its result is not confirmed")
            chat.fail("an earlier call was interrupted; inspect its logs, then retry explicitly with a NEW request-id")
        pending = current["latest_proposal"] and not current["latest_review"]
        if pending and current["latest_proposal"]["sender"] == config["main"]:
            allowed = ["review"]
        elif not pending and current["phase"] == "discussing" and current["next_speaker"] == config["reviewer"]:
            allowed = ["send"]
        else:
            chat.fail("the original main must send a new message or propose a conclusion first")
        input_event_id = max((e["id"] for e in events), default=0)
        if cached and cached["phase"] != "response_ready":
            peer.publish(root, info, "failed", pending_request=None,
                         detail="this request failed or was interrupted")
            chat.fail("this request failed or was interrupted; inspect its logs, then retry explicitly with a NEW request-id")
        if cached and cached["input_event_id"] != input_event_id:
            chat.fail("discussion changed since this response; use a new request-id to ask against current context")
        if not cached:
            turn = info["next_turn"]
            cached = {"phase": "pending", "request_id": request_id, "turn": turn, "input_event_id": input_event_id}
            peer.write_json(cache_path, cached)
            info.update(next_turn=turn + 1, pending_request=request_id)
            peer.publish(root, info, "calling")
            run_directory = root / ("turn-" + str(turn))
            run_directory.mkdir()
            model_info = {"mode": "foreground-consultation", "native_session_id": info["native_session_id"]}
            namespace = argparse.Namespace(room=args.room, agent=config["reviewer"], backend="claude",
                                          cli=config["cli"], cwd=config["cwd"], turn_timeout=args.turn_timeout)
            context = {"your_identity": config["reviewer"], "main_identity": config["main"],
                       "project_directory": config["cwd"], "topic": current["topic"],
                       "briefing": config["briefing"], "allowed_actions": allowed, "status": current,
                       "new_events": [e for e in events if e["id"] > info["read_cursor"]]}
            try:
                result = peer.model_response(namespace, peer_root, run_directory, model_info,
                                             CONSULT_RULES + "\nDiscussion data:\n" + json.dumps(context, ensure_ascii=False), turn)
                cached.update(phase="response_ready", result=result,
                              native_session_id=model_info["native_session_id"], read_cursor=input_event_id)
                peer.write_json(cache_path, cached)
                peer.publish(root, info, "response_ready", native_session_id=model_info["native_session_id"])
            except BaseException as exc:
                cached.update(phase="failed", error=str(exc))
                peer.write_json(cache_path, cached)
                peer.publish(root, info, "failed", pending_request=None, detail=str(exc))
                raise
        try:
            latest, latest_events = snapshot(args.room, config)
            if max((e["id"] for e in latest_events), default=0) != cached["input_event_id"]:
                chat.fail("discussion changed while Claude was responding; no stale reply was recorded")
            applied = peer.apply_response(argparse.Namespace(room=args.room, agent=config["reviewer"]), root,
                                          cached["result"], allowed, "consult-" + digest, 0, latest)
            info.update(native_session_id=cached["native_session_id"], read_cursor=cached["read_cursor"],
                        completed_turn=cached["turn"], pending_request=None)
            cached["phase"] = "committed"
            peer.write_json(cache_path, cached)
            peer.publish(root, info, "idle", detail=None)
            return {"event": applied["event"], "duplicate": False, **status(args.room)}
        except BaseException as exc:
            # Keep a ready response for safe retry without another model call.
            peer.publish(root, info, "failed", pending_request=None, detail=str(exc))
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "reply", "status"):
        p = sub.add_parser(name)
        p.add_argument("--room", required=True)
        if name == "init":
            p.add_argument("--cwd", required=True)
            p.add_argument("--briefing-file", required=True)
            p.add_argument("--main", default="codex")
            p.add_argument("--reviewer", default="claude")
            p.add_argument("--cli", default="claude")
            p.add_argument("--max-messages", type=int, default=12)
            p.add_argument("--minutes", type=float, default=10)
        elif name == "reply":
            p.add_argument("--request-id", required=True)
            p.add_argument("--turn-timeout", type=int, default=180)
    args = parser.parse_args()
    try:
        if args.command == "init":
            result = initialize(args)
        elif args.command == "reply":
            result = reply(args)
        else:
            result = status(args.room)
        print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
        return 0
    except (chat.ChatError, peer.Interrupted, peer.AlreadyRunning, OSError, sqlite3.Error, ValueError) as exc:
        detail = str(exc) or "this participant already has an active call; wait for that execution"
        print(json.dumps({"ok": False, "error": detail}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
