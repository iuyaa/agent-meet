#!/usr/bin/env python3
"""Run a complete Codex/Claude discussion without a manual continue message."""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path

import chat
import peer

TERMINAL = {"completed", "failed", "stopped", "expired"}


def directory(room):
    return Path(str(Path(room).resolve()) + ".job")


def room_status(room):
    with chat.database(room) as conn:
        return chat.state(conn)


def status(room):
    root = directory(room)
    info = peer.read_status(root)
    if info["state"] == "not_started":
        chat.fail("managed discussion not found; start a new one first")
    result = {"job": info, "status": room_status(room), "finished": info["state"] in TERMINAL}
    result["peers"] = {name: peer.read_status(peer.paths(room, name)) for name in ("codex", "claude")}
    # A lost controller is an error, not a reason to wait forever. The short
    # startup grace avoids reporting the gap between parent and worker as a crash.
    if not result["finished"] and time.time() - info["created"] > 15:
        try:
            with peer.participant_lock(root):
                result["job"] = {**info, "state": "failed", "detail": "discussion controller is no longer running"}
                result["finished"] = True
        except peer.AlreadyRunning:
            pass
    return result


def finish(room, root, info, state, detail):
    if state == "failed":
        chat.stop(argparse.Namespace(room=room, reason="managed discussion failed; see job status"))
    for name in ("codex", "claude"):
        location = peer.paths(room, name)
        if location.exists():
            (location / "stop.request").touch()
    # The room is closed before export, so the snapshot cannot gain new events.
    chat.export(argparse.Namespace(room=room, output=info["report_path"]))
    peer.publish(root, info, state, detail=detail,
                 conclusion_status=room_status(room)["conclusion_status"])


def worker(room):
    root = directory(room)
    args = argparse.Namespace(**json.loads((root / "job.json").read_text(encoding="utf-8")))
    info = peer.read_status(root)
    ready = root / "ready.json"
    try:
        with peer.participant_lock(root):
            try:
                peer.publish(root, info, "starting", pid=os.getpid())
                for backend in ("claude", "codex"):
                    peer.start(argparse.Namespace(room=room, agent=backend, backend=backend,
                                                  cwd=args.cwd, cli=getattr(args, backend + "_cli"),
                                                  turn_timeout=args.turn_timeout))
                peer.publish(root, info, "running")
                peer.write_json(ready, {"ok": True})
                while True:
                    current = room_status(room)
                    if current["phase"] == "closed":
                        reason = current["close_reason"]
                        final = "completed" if reason == "agreement" else "expired" if reason == "expired" else "stopped"
                        finish(room, root, info, final, reason)
                        return 0
                    for name in ("codex", "claude"):
                        location = peer.paths(room, name)
                        managed = peer.read_status(location)
                        if managed["state"] in ("failed", "stopped"):
                            chat.fail(f"{name} participant failed/stopped: {managed.get('detail', '')}")
                        if managed["state"] in ("waiting", "thinking", "running"):
                            try:
                                with peer.participant_lock(location):
                                    chat.fail(f"{name} participant process is no longer running")
                            except peer.AlreadyRunning:
                                pass
                    time.sleep(0.3)
            except Exception as exc:
                finish(room, root, info, "failed", str(exc))
                peer.write_json(ready, {"ok": False, "error": str(exc)})
                return 1
    except peer.AlreadyRunning:
        return 1


def start(args):
    root = directory(args.room)
    requested_topic = Path(args.topic_file).read_text(encoding="utf-8") if args.topic_file else args.topic
    if (root / "status.json").exists():
        previous = status(args.room)
        if requested_topic is not None and requested_topic.strip() != previous["status"]["topic"]:
            chat.fail("this discussion path belongs to a different topic; choose a new path")
        return {"already_started": True, **previous}
    # Verify both executables before creating a room or starting either model.
    peer.cli_prefix(args.codex_cli, "codex")
    peer.cli_prefix(args.claude_cli, "claude")
    cwd = str(Path(args.cwd).resolve())
    if not Path(cwd).is_dir():
        chat.fail("project directory does not exist")
    if not 1 <= args.turn_timeout <= 600:
        chat.fail("turn-timeout must be between 1 and 600 seconds")
    topic = requested_topic
    chat.nonempty(topic, "topic")
    with peer.participant_lock(root):
        if (root / "status.json").exists():
            return {"already_started": True, **status(args.room)}
        chat.create(argparse.Namespace(room=args.room, topic=topic, participants=["codex", "claude"],
                                       max_messages=args.max_messages, minutes=args.minutes))
        run_id = uuid.uuid4().hex
        report = Path(args.room).resolve().with_name(Path(args.room).stem + "-report-" + run_id[:8] + ".md")
        config = {"room": str(Path(args.room).resolve()), "cwd": cwd,
                  "codex_cli": args.codex_cli, "claude_cli": args.claude_cli, "turn_timeout": args.turn_timeout}
        peer.write_json(root / "job.json", config)
        info = {"state": "starting", "created": time.time(), "run_id": run_id,
                "room": config["room"], "cwd": cwd, "report_path": str(report)}
        peer.publish(root, info, "starting")
    command = [sys.executable, str(Path(__file__).resolve()), "_worker", "--room", config["room"]]
    options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS} if os.name == "nt" else {"start_new_session": True}
    with (root / "controller.log").open("wb") as log:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                   close_fds=True, **options)
    ready = root / "ready.json"
    until = time.monotonic() + 12
    while not ready.exists() and process.poll() is None and time.monotonic() < until:
        time.sleep(0.05)
    if not ready.exists():
        chat.fail(f"controller startup did not report readiness; inspect {root / 'controller.log'}")
    outcome = json.loads(ready.read_text(encoding="utf-8"))
    if not outcome["ok"]:
        chat.fail(outcome["error"])
    return {"already_started": False, **status(args.room)}


def wait(room, timeout):
    if not 0 <= timeout <= 30:
        chat.fail("timeout must be between 0 and 30 seconds")
    until = time.monotonic() + timeout
    while True:
        result = status(room)
        if result["finished"] or time.monotonic() >= until:
            return result
        time.sleep(0.2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("start", "run", "status", "wait", "stop", "_worker"):
        p = sub.add_parser(name)
        p.add_argument("--room", required=True)
        if name in ("start", "run"):
            p.add_argument("--cwd", required=True)
            topic = p.add_mutually_exclusive_group()
            topic.add_argument("--topic")
            topic.add_argument("--topic-file")
            p.add_argument("--codex-cli", default="codex")
            p.add_argument("--claude-cli", default="claude")
            p.add_argument("--turn-timeout", type=int, default=180)
            p.add_argument("--max-messages", type=int, default=12)
            p.add_argument("--minutes", type=float, default=10)
        elif name == "wait":
            p.add_argument("--timeout", type=float, default=25)
    args = parser.parse_args()
    try:
        if args.command == "_worker":
            return worker(args.room)
        if args.command in ("start", "run"):
            result = start(args)
            if args.command == "run":
                print(json.dumps({"event": "started", **result}, ensure_ascii=False), flush=True)
                while not result["finished"]:
                    result = wait(args.room, 25)
        elif args.command == "wait":
            result = wait(args.room, args.timeout)
        elif args.command == "stop":
            chat.stop(argparse.Namespace(room=args.room, reason="user stopped managed discussion"))
            result = status(args.room)
        else:
            result = status(args.room)
        print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
        return 1 if args.command == "run" and result["job"]["state"] == "failed" else 0
    except (chat.ChatError, peer.AlreadyRunning, OSError, sqlite3.Error, ValueError) as exc:
        detail = str(exc) or "managed discussion is starting; query status or retry the same room"
        print(json.dumps({"ok": False, "error": detail}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
