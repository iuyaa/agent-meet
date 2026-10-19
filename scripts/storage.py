#!/usr/bin/env python3
"""Prepare a project-local directory for a new Meet discussion."""

import argparse
import json
import re
import secrets
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import chat


def managed_root(cwd):
    project = Path(cwd).resolve()
    if not project.is_dir():
        chat.fail("project directory does not exist")
    root = project / ".agent-meet"
    if root.is_symlink():
        chat.fail(".agent-meet must be a project-local directory; use --room for custom storage")
    root.mkdir(mode=0o700, exist_ok=True)
    ignore = root / ".gitignore"
    if ignore.is_symlink():
        chat.fail(".agent-meet/.gitignore must be a regular file")
    try:
        with ignore.open("x", encoding="utf-8") as handle:
            handle.write("# Local Meet discussion data, including this ignore file.\n*\n")
    except FileExistsError:
        current = ignore.read_text(encoding="utf-8-sig")
        if "*" not in current.splitlines():
            with ignore.open("a", encoding="utf-8") as handle:
                handle.write(("" if not current or current.endswith("\n") else "\n") + "*\n")
    return root


def prepare(cwd, topic):
    topic = chat.nonempty(topic, "topic")
    root = managed_root(cwd)
    slug = re.sub(r"[^\w-]+", "-", unicodedata.normalize("NFKC", topic)).strip("-_")[:32] or "discussion"
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    for _ in range(10):
        directory = root / (timestamp + "-" + slug + "-" + secrets.token_hex(3))
        try:
            directory.mkdir(mode=0o700)
            break
        except FileExistsError:
            continue
    else:
        chat.fail("cannot allocate a unique discussion directory; retry explicitly")
    return {"room": str(directory / "discussion.sqlite"), "discussion_directory": str(directory),
            "briefing_file": str(directory / "briefing.json"), "roles_file": str(directory / "roles.json")}


def resolve_room(cwd, room, topic):
    if not room:
        return prepare(cwd, topic)["room"]
    target = Path(room).resolve()
    root = Path(cwd).resolve() / ".agent-meet"
    if root in target.parents:
        managed_root(cwd)
    return str(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--cwd", required=True, help="project directory")
    p.add_argument("--topic", required=True, help="used for the discussion folder label")
    args = parser.parse_args()
    try:
        print(json.dumps({"ok": True, **prepare(args.cwd, args.topic)}, ensure_ascii=False, indent=2))
        return 0
    except (chat.ChatError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
