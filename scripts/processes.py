"""Shared launch policy for noninteractive agent and service processes."""

import os
import subprocess


WINDOWS = os.name == "nt"


def launch_options(*, background=False):
    """Do not allocate a Windows console; detach background services on POSIX."""
    if WINDOWS:
        # DETACHED_PROCESS must not be combined with CREATE_NO_WINDOW: Windows
        # ignores CREATE_NO_WINDOW in that combination. All callers redirect
        # stdin/stdout/stderr, so neither workers nor CLIs need a console.
        flags = subprocess.CREATE_NO_WINDOW
        if background:
            flags |= subprocess.CREATE_NEW_PROCESS_GROUP
        return {"creationflags": flags}
    return {"start_new_session": True} if background else {}
