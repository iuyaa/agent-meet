"""Git evidence and delivery for task worktrees; never stage the source index."""

import os
import subprocess
import tempfile
import uuid
from pathlib import Path

import chat
import processes


def git(cwd, *args, data=None, env=None):
    result = subprocess.run(["git", "-C", str(cwd), *args], input=data,
                            capture_output=True, env=env, **processes.launch_options())
    if result.returncode:
        chat.fail("git " + args[0] + ": " + result.stderr.decode("utf-8", "replace").strip())
    return result.stdout


def text(cwd, *args):
    return git(cwd, *args).decode("utf-8", "replace").strip()


def root(project):
    project = Path(project).resolve()
    if not project.is_dir():
        chat.fail("project directory does not exist")
    result = Path(text(project, "rev-parse", "--show-toplevel")).resolve()
    if result != project:
        chat.fail("task --cwd must be the Git repository root")
    text(project, "rev-parse", "--verify", "HEAD")
    if git(project, "ls-files", "--unmerged"):
        chat.fail("resolve existing merge conflicts before starting a task")
    if any(line.startswith(b"160000 ") for line in git(project, "ls-files", "--stage").splitlines()):
        chat.fail("task mode does not yet support repositories with submodules")
    return project


def tree(cwd, directory):
    """Capture working files, including untracked files, with a disposable index."""
    fd, filename = tempfile.mkstemp(prefix="git-index-", dir=directory)
    os.close(fd)
    Path(filename).unlink()  # Git expects a missing index, not an empty file.
    env = dict(os.environ, GIT_INDEX_FILE=filename)
    try:
        git(cwd, "read-tree", "HEAD", env=env)
        git(cwd, "add", "-A", "--", ".", ":(exclude).agent-meet", env=env)
        return git(cwd, "write-tree", env=env).decode().strip()
    finally:
        Path(filename).unlink(missing_ok=True)
        Path(filename + ".lock").unlink(missing_ok=True)


def commit(cwd, tree_id, parent, message):
    env = dict(os.environ, GIT_AUTHOR_NAME="Agent-Meet", GIT_AUTHOR_EMAIL="agent-meet@localhost",
               GIT_COMMITTER_NAME="Agent-Meet", GIT_COMMITTER_EMAIL="agent-meet@localhost")
    return git(cwd, "-c", "commit.gpgsign=false", "commit-tree", tree_id, "-p", parent,
               data=(message + "\n").encode(), env=env).decode().strip()


def prepare(project, worktree, directory):
    head = text(project, "rev-parse", "HEAD")
    base_tree = tree(project, directory)
    # Refuse a source edit during snapshot creation instead of silently mixing it.
    if text(project, "rev-parse", "HEAD") != head or tree(project, directory) != base_tree:
        chat.fail("source changed during initialization; retry after the edit finishes")
    branch = "agent-meet/task-" + uuid.uuid4().hex[:16]
    git(project, "-c", "core.hooksPath=", "worktree", "add", "-b", branch, str(worktree), head)
    try:
        git(worktree, "read-tree", "--reset", "-u", base_tree)
        base_commit = commit(worktree, base_tree, head, "Agent-Meet: snapshot task starting files")
        git(worktree, "update-ref", "HEAD", base_commit, head)
        return {"source": str(project), "worktree": str(worktree), "branch": branch,
                "source_head": head, "base_tree": base_tree, "base_commit": base_commit,
                "common_dir": str(Path(text(worktree, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve())}
    except BaseException:
        git(project, "worktree", "remove", "--force", str(worktree))
        git(project, "branch", "-D", branch)
        raise


def verify(config):
    worktree = Path(config["worktree"])
    if not worktree.is_dir() or worktree.is_symlink():
        chat.fail("original task worktree is missing or replaced")
    common = str(Path(text(worktree, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve())
    expected = config.get("delivery_commit") or config["base_commit"]
    if (common != config["common_dir"] or text(worktree, "symbolic-ref", "--short", "HEAD") != config["branch"]
            or text(worktree, "rev-parse", "HEAD") != expected):
        chat.fail("task Git identity changed; restore the original worktree/branch before continuing")


def inspect(config, directory):
    verify(config)
    snapshot = tree(config["worktree"], directory)
    diff = git(config["worktree"], "diff", "--binary", "--no-ext-diff", "--no-textconv",
               config["base_tree"], snapshot, "--", ".", ":(exclude).agent-meet")
    path = directory / ("diff-" + snapshot + ".patch")
    path.write_bytes(diff)
    names = git(config["worktree"], "diff", "--name-only", "--no-renames", "-z", config["base_tree"], snapshot)
    preview = diff[:48000].decode("utf-8", "replace")
    return {"snapshot": snapshot, "changed_files": [p.decode("utf-8", "replace") for p in names.split(b"\0") if p],
            "stat": text(config["worktree"], "diff", "--stat", config["base_tree"], snapshot),
            "diff_file": str(path), "diff_preview": preview, "diff_truncated": len(diff) > 48000}


def accept(config, snapshot):
    worktree = config["worktree"]
    delivery = commit(worktree, snapshot, config["base_commit"], "Agent-Meet: host accepted task result")
    git(worktree, "update-ref", "HEAD", delivery, config["base_commit"])
    # Synchronize only this isolated worktree's real index; source index is untouched.
    git(worktree, "read-tree", snapshot)
    return delivery


def apply(config, directory):
    source = config["source"]
    current = tree(source, directory)
    target = config["accepted_snapshot"]
    # Compare only paths touched by the accepted change. Unrelated source edits survive.
    names = git(config["worktree"], "diff", "--name-only", "--no-renames", "-z", config["base_tree"], target)
    paths = [p.decode("utf-8") for p in names.split(b"\0") if p]
    if paths and not git(source, "--literal-pathspecs", "diff", "--no-ext-diff", "--no-textconv", target, current, "--", *paths):
        return paths  # Recover an apply that finished before its receipt was committed.
    base = target if config.get("applied") else config["base_tree"]
    if paths and git(source, "--literal-pathspecs", "diff", "--no-ext-diff", "--no-textconv", base, current, "--", *paths):
        chat.fail("source changed on task paths; refusing to overwrite it (worktree and patch are preserved)")
    if not config.get("applied") and paths:
        patch = git(config["worktree"], "diff", "--binary", "--no-ext-diff", "--no-textconv", config["base_tree"], target)
        git(source, "apply", "--check", "--binary", "--whitespace=nowarn", "-", data=patch)
        git(source, "apply", "--binary", "--whitespace=nowarn", "-", data=patch)
    return paths
