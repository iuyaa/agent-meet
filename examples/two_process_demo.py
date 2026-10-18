#!/usr/bin/env python3
"""Protocol demonstration with scripted peers, not model-generated dialogue."""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "chat.py"


def call(room, command, *args):
    run = subprocess.run([sys.executable, str(SCRIPT), command, "--room", str(room), *map(str, args)],
                         check=True, capture_output=True, text=True, encoding="utf-8", timeout=8)
    return json.loads(run.stdout)


def peer(room, who):
    call(room, "join", "--as", who)
    cursor = 0
    sent = 0
    proposed = False
    lines = {
        "codex": ["第一版是同机、两个进程共享讨论记录，我建议 SQLite。你担心什么？",
                  "同意需要控制并发。通信工具通过短事务串行写入；跨机器存储留到后续评估。"],
        "claude": ["SQLite 适合本地，但两个进程并发写入时需要事务和忙等待。",
                   "同意这个边界。第一版用 SQLite；跨机器方案仍待确认，不在本轮定论。"],
    }
    until = time.monotonic() + 25
    while time.monotonic() < until:
        response = call(room, "wait", "--as", who, "--after", cursor, "--timeout", 0.5)
        cursor = response["next_after"]
        status = response["status"]
        if status["phase"] == "closed":
            return
        if response["next_action"] == "review":
            call(room, "review", "--as", who, "--request-id", who + "-review",
                 "--proposal", status["latest_proposal"]["id"], "--decision", "accept",
                 "--text", "确认：这准确记录了本轮共识和待确认问题。")
            continue
        if status["phase"] == "summarizing" and who == "codex" and not proposed:
            conclusion = {"summary": "同机第一版采用 SQLite，以短事务协调并发写入。",
                          "agreements": ["第一版使用 SQLite。", "并发写入需要事务与忙等待。"],
                          "disagreements": [], "open_questions": ["跨机器通信时的存储方案。"],
                          "evidence_message_ids": [1, 2, 3, 4]}
            path = room.parent / "demo-conclusion.json"
            path.write_text(json.dumps(conclusion, ensure_ascii=False, indent=2), encoding="utf-8")
            call(room, "propose", "--as", who, "--request-id", "codex-proposal", "--file", path)
            proposed = True
        elif response["next_action"] == "send_or_propose" and sent < 2:
            call(room, "send", "--as", who, "--request-id", f"{who}-{sent}", "--text", lines[who][sent])
            sent += 1
    raise RuntimeError("scripted discussion did not complete within 25 seconds")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--peer", choices=["codex", "claude"], help=argparse.SUPPRESS)
    parser.add_argument("--room", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.peer:
        peer(args.room, args.peer)
        return
    if args.output is None:
        parser.error("--output is required")
    args.output.mkdir(parents=True, exist_ok=False)
    room = args.output.resolve() / "discussion.sqlite"
    call(room, "create", "--topic", "协议演示（预写消息，非真实模型）：第一版使用什么数据库？",
         "--max-messages", 4)
    processes = []
    try:
        for who in ("codex", "claude"):
            processes.append(subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                                               "--peer", who, "--room", str(room)],
                                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                              text=True, encoding="utf-8"))
        for process in processes:
            stdout, stderr = process.communicate(timeout=30)
            if process.returncode:
                raise RuntimeError(stderr or stdout)
        result = call(room, "export", "--output", args.output.resolve() / "discussion-report.md")
        print(json.dumps({"demo": "scripted peers; no models invoked", **result}, ensure_ascii=False, indent=2))
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate()


if __name__ == "__main__":
    main()
